"""Testes dos serviços da Fase 3: redação, numeração, sumário, metadados e certificado."""

from __future__ import annotations

from pathlib import Path

import pytest

import pymupdf


# --------------------------------------------------------------------------- #
# fixtures                                                                     #
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def sensitive_pdf(tmp_path_factory) -> Path:
    """PDF nasceu-digital com dados sensíveis de verdade (CPFs válidos)."""
    work = tmp_path_factory.mktemp("sensitive")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    lines = [
        "CONTRATO DE PRESTACAO DE SERVICOS",
        "CPF do autor: 529.982.247-25",
        "CNPJ da empresa: 11.222.333/0001-81",
        "E-mail: contato@escritorio.adv.br",
        "Telefone: (11) 98765-4321",
        "Endereco: Rua das Flores, 123",
        "Cartao: 4111 1111 1111 1111",
    ]
    y = 72
    for line in lines:
        page.insert_text(pymupdf.Point(72, y), line, fontsize=12)
        y += 30
    out = work / "contrato_dados.pdf"
    doc.save(out)
    doc.close()
    return out


@pytest.fixture(scope="session")
def three_page_pdf(tmp_path_factory) -> Path:
    """PDF de 3 páginas para sumário e numeração."""
    work = tmp_path_factory.mktemp("tres")
    doc = pymupdf.open()
    for i in range(1, 4):
        page = doc.new_page(width=595, height=842)
        page.insert_text(pymupdf.Point(72, 100), f"Pagina {i}", fontsize=14)
    out = work / "peticao_com_anexos.pdf"
    doc.save(out)
    doc.close()
    return out


def _text(pdf: Path) -> str:
    doc = pymupdf.open(pdf)
    try:
        return "".join(page.get_text() for page in doc)
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# redação                                                                      #
# --------------------------------------------------------------------------- #
def test_redact_detecta_dados_pelas_regex(sensitive_pdf, tmp_path):
    from app.services.redact import detect_sensitive

    result = detect_sensitive(sensitive_pdf)
    assert result.has_text_layer is True
    by_type = {g.type: g for g in result.groups}
    assert by_type["cpf"].value == "529.982.247-25"
    assert by_type["cnpj"].value == "11.222.333/0001-81"
    assert by_type["email"].value == "contato@escritorio.adv.br"
    assert by_type["phone"].value == "(11) 98765-4321"
    assert "card" in by_type and "address" in by_type
    # prioridade: o CPF não pode ser reivindicado pelo padrão de telefone/RG
    assert all(g.type != "rg" for g in result.groups)
    assert result.total >= 6


def test_redact_apaga_irreversivelmente(sensitive_pdf, tmp_path):
    from app.services.redact import RedactOptions, redact_pdf

    opts = RedactOptions.from_dict(
        {"terms": ["529.982.247-25", "contato@escritorio.adv.br"], "mode": "black"}
    )
    result = redact_pdf(sensitive_pdf, tmp_path, opts)
    assert result.redacted >= 2

    texto = _text(result.file)
    assert "529.982.247-25" not in texto
    assert "contato@escritorio.adv.br" not in texto
    # os dados NÃO aprovados na revisão continuam lá
    assert "(11) 98765-4321" in texto
    # nada sobrou da busca visual
    doc = pymupdf.open(result.file)
    try:
        assert not doc[0].search_for("529.982.247-25")
    finally:
        doc.close()


def test_redact_rejeita_pdf_sem_camada_de_texto(scanned_pdf, tmp_path):
    from app.services.redact import RedactOptions, redact_pdf

    opts = RedactOptions.from_dict({"terms": ["529.982.247-25"]})
    with pytest.raises(ValueError):
        redact_pdf(scanned_pdf, tmp_path, opts)


def test_redact_auto_detecta_quando_sem_terms(sensitive_pdf, tmp_path):
    from app.services.redact import RedactOptions, redact_pdf

    opts = RedactOptions.from_dict({"types": ["cpf"]})
    result = redact_pdf(sensitive_pdf, tmp_path, opts)
    assert "529.982.247-25" not in _text(result.file)


# --------------------------------------------------------------------------- #
# numeração / marca d'água                                                     #
# --------------------------------------------------------------------------- #
def test_numero_fls_com_marca_dagua(three_page_pdf, tmp_path):
    from app.services.number import NumberOptions, number_pdf

    opts = NumberOptions.from_dict(
        {"style": "fls", "start": 1, "pad": 3, "watermark": "SIGILOSO"}
    )
    result = number_pdf(three_page_pdf, tmp_path, opts)
    assert result.stamped == 3
    texto = _text(result.file)
    assert "Fls. 001" in texto
    assert "Fls. 003" in texto
    assert "SIGILOSO" in texto


def test_numero_bates_com_prefixo(three_page_pdf, tmp_path):
    from app.services.number import NumberOptions, number_pdf

    opts = NumberOptions.from_dict(
        {"style": "bates", "prefix": "PROC", "start": 100, "pad": 6}
    )
    result = number_pdf(three_page_pdf, tmp_path, opts)
    texto = _text(result.file)
    assert "PROC000100" in texto
    assert "PROC000102" in texto


def test_numero_respeita_intervalo(three_page_pdf, tmp_path):
    from app.services.number import NumberOptions, number_pdf

    opts = NumberOptions.from_dict({"style": "fls", "pages": "2"})
    result = number_pdf(three_page_pdf, tmp_path, opts)
    assert result.stamped == 1
    doc = pymupdf.open(result.file)
    try:
        texts = [page.get_text() for page in doc]
        assert "Fls." in texts[1]
        assert "Fls." not in texts[0]
        assert "Fls." not in texts[2]
    finally:
        doc.close()


# --------------------------------------------------------------------------- #
# sumário / índice                                                            #
# --------------------------------------------------------------------------- #
def test_sumario_com_anexos_e_bookmarks(three_page_pdf, tmp_path):
    from app.services.outline import OutlineOptions, build_outline

    opts = OutlineOptions.from_dict(
        {
            "title": "ÍNDICE",
            "insert_index": True,
            "bookmarks": True,
            "entries": [
                {"label": "ANEXO I — Procuração", "page": 1},
                {"label": "ANEXO II — Contrato", "page": 3},
            ],
        }
    )
    result = build_outline(three_page_pdf, tmp_path, opts)
    assert result.pages == 4  # 3 originais + 1 de índice

    doc = pymupdf.open(result.file)
    try:
        assert doc.page_count == 4
        toc = doc.get_toc()
        assert toc[0][0] == 1 and toc[0][1] == "ÍNDICE"
        assert toc[1] == [2, "ANEXO I — Procuração", 2]   # deslocado pelo índice
        assert toc[2] == [2, "ANEXO II — Contrato", 4]
        indice = doc[0].get_text()
        assert "ANEXO I — Procuração" in indice
        assert "4" in indice  # número da última folha já deslocado
    finally:
        doc.close()


def test_sumario_deriva_dos_bookmarks_existentes(three_page_pdf, tmp_path):
    from app.services.outline import OutlineOptions, build_outline

    base = OutlineOptions.from_dict(
        {"entries": [{"label": "Anexo A", "page": 2}], "insert_index": False}
    )
    first = build_outline(three_page_pdf, tmp_path, base)

    derived = build_outline(first.file, tmp_path, OutlineOptions.from_dict({}))
    assert derived.entries == 1


def test_sumario_sem_entrada_nem_bookmarks_falha(three_page_pdf, tmp_path):
    from app.services.outline import OutlineOptions, build_outline

    with pytest.raises(ValueError):
        build_outline(three_page_pdf, tmp_path, OutlineOptions.from_dict({}))


# --------------------------------------------------------------------------- #
# metadados jurídicos + renomeação                                             #
# --------------------------------------------------------------------------- #
def test_metadados_gravam_cnj_e_renomeia(text_pdf, tmp_path):
    from app.services.metadata import LegalMetaOptions, apply_legal_metadata

    opts = LegalMetaOptions.from_dict(
        {
            "cnj": "0000001-10.2026.8.01.0001",
            "tipo": "Petição inicial",
            "autor": "João da Silva",
            "reu": "Empresa XYZ",
            "data": "2026-10-28",
        }
    )
    result = apply_legal_metadata(text_pdf, tmp_path, opts)
    assert result.file.name == (
        "Petição inicial - 0000001-10.2026.8.01.0001 - João da Silva x "
        "Empresa XYZ.pdf"
    )
    doc = pymupdf.open(result.file)
    try:
        meta = doc.metadata
        assert meta["title"].startswith("Petição inicial")
        assert "0000001-10.2026.8.01.0001" in meta["keywords"]
        assert meta["author"] == "João da Silva x Empresa XYZ"
    finally:
        doc.close()


def test_metadados_normaliza_e_rejeita_cnj_invalido(text_pdf, tmp_path):
    from app.services.metadata import LegalMetaOptions

    ok = LegalMetaOptions.from_dict({"cnj": "00000011020268010001"})
    assert ok.cnj == "0000001-10.2026.8.01.0001"

    with pytest.raises(ValueError):
        LegalMetaOptions.from_dict({"cnj": "123"})
    with pytest.raises(ValueError):
        LegalMetaOptions.from_dict({"data": "28/10/2026"})


# --------------------------------------------------------------------------- #
# certificado de integridade                                                   #
# --------------------------------------------------------------------------- #
def test_certificado_lista_hashes(text_pdf, sensitive_pdf, tmp_path):
    from app.services.hashing import sha256_file
    from app.services.integrity import IntegrityOptions, build_certificate

    opts = IntegrityOptions.from_dict(
        {"emitente": "Escândalo Advogados", "observacao": "Processo 123"}
    )
    result = build_certificate([text_pdf, sensitive_pdf], tmp_path, opts)
    assert result.files == 2

    texto = _text(result.file)
    assert sha256_file(text_pdf) in texto.replace("\n", "")
    assert sha256_file(sensitive_pdf) in texto.replace("\n", "")
    assert "ICP-Brasil" in texto

    doc = pymupdf.open(result.file)
    try:
        assert doc.metadata["title"] == "Certificado de Integridade"
        assert "Escândalo Advogados" == doc.metadata["author"]
    finally:
        doc.close()


def test_certificado_sem_arquivos_falha(tmp_path):
    from app.services.integrity import build_certificate

    with pytest.raises(ValueError):
        build_certificate([], tmp_path)
