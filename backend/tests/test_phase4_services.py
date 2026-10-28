"""Testes dos serviços da Fase 4: índice de busca, comparador e lote."""

from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest

import pymupdf


# --------------------------------------------------------------------------- #
# fixtures/helpers                                                             #
# --------------------------------------------------------------------------- #
def _make_pdf(path: Path, lines: list[str]) -> Path:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    y = 72
    for line in lines:
        page.insert_text(pymupdf.Point(72, y), line, fontsize=11)
        y += 26
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def v1(tmp_path) -> Path:
    return _make_pdf(
        tmp_path / "peticao_v1.pdf",
        ["PETICAO INICIAL", "honorario de R$ 5.000,00", "clausula 1 - objeto"],
    )


@pytest.fixture()
def v2(tmp_path) -> Path:
    return _make_pdf(
        tmp_path / "peticao_v2.pdf",
        ["PETICAO INICIAL", "honorario de R$ 6.500,00", "clausula 1 - objeto"],
    )


# --------------------------------------------------------------------------- #
# índice de busca                                                              #
# --------------------------------------------------------------------------- #
def test_sanitize_query_evita_erro_de_sintaxe():
    from app.db.search import sanitize_query

    assert sanitize_query("honorário contrato") == '"honorário" AND "contrato"'
    # caracteres especiais do FTS5 não passam adiante
    assert sanitize_query('"(erro[ NEAR ') == '"erro" AND "NEAR"'
    assert sanitize_query("   ") == ""
    assert sanitize_query('termo "solto"') == '"termo" AND "solto"'


def test_extract_text_de_pdf_txt_e_docx(tmp_path):
    from app.services.indexing import extract_text

    pdf = _make_pdf(tmp_path / "a.pdf", ["CLAUSULA 1 - objeto do contrato"])
    assert "CLAUSULA 1" in extract_text(pdf)

    txt = tmp_path / "b.txt"
    txt.write_text("texto simples de teste", encoding="utf-8")
    assert "texto simples" in extract_text(txt)

    # .docx mínimo (word/document.xml)
    import zipfile as zf

    docx = tmp_path / "c.docx"
    with zf.ZipFile(docx, "w") as z:
        z.writestr(
            "[Content_Types].xml", "<Types/>"
        )
        z.writestr(
            "word/document.xml",
            "<w:document><w:body><w:p><w:r><w:t>procuração anexa</w:t></w:r></w:p></w:body></w:document>",
        )
    assert "procuração anexa" in extract_text(docx)


def test_imagem_sem_texto_nao_quebra(tmp_path):
    from app.services.indexing import extract_text

    png = tmp_path / "foto.png"
    from PIL import Image

    Image.new("RGB", (10, 10), "white").save(png)
    assert extract_text(png) == ""


# --------------------------------------------------------------------------- #
# comparador                                                                   #
# --------------------------------------------------------------------------- #
def test_comparador_detecta_trocas_por_pagina(v1, v2):
    from app.services.compare import compare_documents

    result = compare_documents(v1, v2)
    assert result.summary["pages_compared"] == 1
    assert result.summary["pages_changed"] == 1
    assert result.summary["lines_added"] >= 1
    assert result.summary["lines_removed"] >= 1

    types = {op["type"] for op in result.pages[0]["ops"]}
    assert "replace" in types
    trocado = next(op for op in result.pages[0]["ops"] if op["type"] == "replace")
    assert "5.000" in trocado["a"][0]
    assert "6.500" in trocado["b"][0]


def test_comparador_igual_nao_mostra_alteracao(v1):
    from app.services.compare import compare_documents

    result = compare_documents(v1, v1)
    assert result.summary["pages_changed"] == 0
    assert result.summary["lines_added"] == 0


def test_comparador_rejeita_nao_pdf(tmp_path):
    from app.services.compare import compare_documents

    txt = tmp_path / "nota.txt"
    txt.write_text("x", encoding="utf-8")
    with pytest.raises(ValueError):
        compare_documents(txt, txt)


# --------------------------------------------------------------------------- #
# lote                                                                         #
# --------------------------------------------------------------------------- #
def _zip_bytes(entries: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in entries.items():
            zf.writestr(name, data)
    return buf.getvalue()


def test_lote_converte_varios_pdfs_em_txt(tmp_path, v1, v2):
    from app.services.batch import BatchOptions, run_batch

    opts = BatchOptions.from_dict(
        {"steps": [{"kind": "convert", "options": {"target": "txt"}}]}
    )
    result = run_batch([v1, v2], tmp_path, opts)
    assert result.processed == 2
    with zipfile.ZipFile(result.file) as zf:
        names = zf.namelist()
        assert len(names) == 2
        assert all(n.endswith(".txt") for n in names)
        conteudo = zf.read(names[0]).decode("utf-8")
        assert "PETICAO" in conteudo


def test_lote_aceita_entrada_zip_com_subpastas(tmp_path, v1):
    from app.services.batch import BatchOptions, run_batch

    data = _zip_bytes({"documentos/contrato.pdf": v1.read_bytes(), "lido.txt": b"ignora"})
    zip_path = tmp_path / "entrada.zip"
    zip_path.write_bytes(data)

    opts = BatchOptions.from_dict(
        {"steps": [{"kind": "number", "options": {"style": "fls", "pad": 3}}]}
    )
    result = run_batch([zip_path], tmp_path / "out", opts)
    assert result.processed == 1  # .txt de fora não entra
    with zipfile.ZipFile(result.file) as zf:
        assert zf.namelist() == ["contrato_numerado.pdf"]
        doc = pymupdf.open(stream=zf.read("contrato_numerado.pdf"), filetype="pdf")
        try:
            assert "Fls. 001" in doc[0].get_text()
        finally:
            doc.close()


def test_lote_ignora_passo_incompativel_com_aviso(tmp_path):
    from app.services.batch import BatchOptions, run_batch

    # imagem + passo "blind" (só PDF) → passa sem mudar, com aviso
    from PIL import Image

    img = tmp_path / "pagina.png"
    Image.new("RGB", (60, 60), "white").save(img)

    opts = BatchOptions.from_dict({"steps": [{"kind": "blind", "options": {}}]})
    result = run_batch([img], tmp_path / "out", opts)
    assert result.processed == 1
    assert result.warnings and "ignorado" in result.warnings[0]
    with zipfile.ZipFile(result.file) as zf:
        assert zf.namelist() == ["pagina.png"]


def test_lote_rejeita_fluxo_invalido(tmp_path):
    from app.services.batch import BatchOptions

    with pytest.raises(ValueError):
        BatchOptions.from_dict({"steps": []})
    with pytest.raises(ValueError):
        BatchOptions.from_dict({"steps": [{"kind": "explode", "options": {}}]})


def test_lote_rejeita_zip_malicioso(tmp_path):
    from app.services.batch import BatchOptions, run_batch

    evil = _zip_bytes({"../fora.pdf": b"%PDF-1.4"})
    zip_path = tmp_path / "evil.zip"
    zip_path.write_bytes(evil)
    opts = BatchOptions.from_dict({"steps": [{"kind": "convert", "options": {"target": "txt"}}]})
    with pytest.raises(ValueError):
        run_batch([zip_path], tmp_path / "out", opts)
