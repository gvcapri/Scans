"""Testes dos serviços da Fase 2: mesclar, dividir, converter e comprimir."""

from __future__ import annotations

from pathlib import Path

import PIL.Image
import pytest
import pymupdf

from app.core.config import settings
from app.services.convert import ConvertOptions, auto_target, convert_document, detect_kind
from app.services.merge import MergeOptions, merge_pdfs
from app.services.split import SplitOptions, parse_ranges, split_pdf


# --------------------------------------------------------------------- fixtures
def _make_pdf(path: Path, pages: int, label: str) -> Path:
    doc = pymupdf.open()
    for i in range(pages):
        page = doc.new_page(width=595, height=842)
        page.insert_text(pymupdf.Point(72, 120), f"{label} pagina {i + 1}", fontsize=18)
    doc.save(path)
    doc.close()
    return path


@pytest.fixture()
def sample_pair(tmp_path: Path) -> tuple[Path, Path]:
    return (
        _make_pdf(tmp_path / "contrato.pdf", 2, "CONTRATO"),
        _make_pdf(tmp_path / "procuracao.pdf", 3, "PROCURACAO"),
    )


@pytest.fixture()
def heavy_pdf(tmp_path: Path) -> Path:
    """PDF 'pesado': páginas com imagens de ruído (o que trava o limite do PJe)."""
    import io

    pages = 4
    doc = pymupdf.open()
    for _ in range(pages):
        page = doc.new_page(width=595, height=842)
        noise = PIL.Image.effect_noise((1400, 1900), 64).convert("RGB")
        buf = io.BytesIO()
        noise.convert("RGB").save(buf, "JPEG", quality=95)
        page.insert_image(page.rect, stream=buf.getvalue())
    out = tmp_path / "anexo_pesado.pdf"
    doc.save(out)
    doc.close()
    return out


# ------------------------------------------------------------------------ merge
def test_merge_respeita_ordem_e_cria_sumario(sample_pair, tmp_path: Path):
    a, b = sample_pair
    result = merge_pdfs([b, a], tmp_path / "out", MergeOptions())  # invertido

    assert result.parts == 2
    assert result.pages == 5

    doc = pymupdf.open(result.file)
    try:
        assert doc.page_count == 5
        # primeira página é a do segundo arquivo enviado (procuração)
        assert "PROCURACAO" in doc[0].get_text()
        assert "CONTRATO pagina 1" in doc[3].get_text()
        toc = doc.get_toc()
        assert [entry[2] for entry in toc] == [1, 4], "bookmark por arquivo de origem"
    finally:
        doc.close()


def test_merge_rejeita_nao_pdf(sample_pair, tmp_path: Path):
    a, _ = sample_pair
    wrong = tmp_path / "imagem.png"
    PIL.Image.new("RGB", (10, 10), "white").save(wrong)
    with pytest.raises(ValueError, match="apenas PDF"):
        merge_pdfs([a, wrong], tmp_path / "out", MergeOptions())


# ------------------------------------------------------------------------- split
def test_parse_ranges_valida_e_normaliza():
    assert parse_ranges("1-3, 5, 7-8", 10) == [(1, 3), (5, 5), (7, 8)]
    assert parse_ranges("3-1", 10) == [(1, 3)], "intervalo invertido é normalizado"
    with pytest.raises(ValueError, match="fora do documento"):
        parse_ranges("9-20", 5)
    with pytest.raises(ValueError, match="inválido"):
        parse_ranges("abc", 5)
    with pytest.raises(ValueError):
        parse_ranges("", 5)


def test_split_por_intervalos(sample_pair, tmp_path: Path):
    a, _ = sample_pair  # 2 páginas
    result = split_pdf(a, tmp_path / "out", SplitOptions(mode="ranges", ranges="1,2"))
    assert len(result.files) == 2
    for path in result.files:
        assert pymupdf.open(path).page_count == 1


def test_split_extrai_paginas(sample_pair, tmp_path: Path):
    a, _ = sample_pair
    result = split_pdf(a, tmp_path / "out", SplitOptions(mode="extract", ranges="2,1"))
    assert len(result.files) == 1
    doc = pymupdf.open(result.files[0])
    try:
        assert doc.page_count == 2
        assert "CONTRATO pagina 1" in doc[1].get_text(), "ordem pedida é preservada"
    finally:
        doc.close()


def test_split_blocos_fixos(tmp_path: Path):
    src = _make_pdf(tmp_path / "grande.pdf", 10, "DOC")
    result = split_pdf(src, tmp_path / "out", SplitOptions(mode="every", every=4))
    assert len(result.files) == 3  # 4 + 4 + 2
    sizes = [pymupdf.open(f).page_count for f in result.files]
    assert sizes == [4, 4, 2]


# ----------------------------------------------------------------------- convert
def test_imagem_vira_pdf(tmp_path: Path):
    src = tmp_path / "paginas.tif"
    PIL.Image.new("RGB", (600, 800), "white").save(src)
    result = convert_document(src, tmp_path / "out", ConvertOptions())
    assert len(result.files) == 1
    assert result.files[0].suffix == ".pdf"
    assert pymupdf.open(result.files[0]).page_count == 1
    assert detect_kind(src) == "image"


def test_pdf_digital_vira_txt(text_pdf: Path, tmp_path: Path):
    result = convert_document(
        text_pdf, tmp_path / "out", ConvertOptions(target="txt")
    )
    text = result.files[0].read_text(encoding="utf-8")
    assert "CONTRATO" in text
    assert "Clausula 1" in text


def test_pdf_para_png_uma_pagina(text_pdf: Path, tmp_path: Path):
    result = convert_document(text_pdf, tmp_path / "out", ConvertOptions(target="png"))
    assert len(result.files) == 1
    assert result.files[0].read_bytes()[:4] == b"\x89PNG"


def test_pdf_varias_paginas_vira_zip(tmp_path: Path):
    import zipfile

    src = _make_pdf(tmp_path / "varias.pdf", 3, "DOC")
    result = convert_document(
        src, tmp_path / "out", ConvertOptions(target="png", jpeg_pages=1)
    )
    assert len(result.files) == 1
    assert result.files[0].suffix == ".zip"
    with zipfile.ZipFile(result.files[0]) as zf:
        assert len(zf.namelist()) == 3


def test_word_vira_pdf(tmp_path: Path):
    pytest.importorskip("docx")
    if settings.resolve_soffice() is None:
        pytest.skip("LibreOffice não instalado")
    from docx import Document

    src = tmp_path / "peticao.docx"
    document = Document()
    document.add_paragraph("EXCELENTISSIMO SENHOR DOUTOR JUIZ")
    document.save(src)

    result = convert_document(src, tmp_path / "out", ConvertOptions())
    assert result.files[0].suffix == ".pdf"
    assert result.files[0].exists()
    assert auto_target(src, ConvertOptions()) == "pdf"


def test_convert_rejeita_alvo_invalido(text_pdf: Path, tmp_path: Path):
    with pytest.raises(ValueError, match="formato de saída"):
        convert_document(text_pdf, tmp_path / "out", ConvertOptions(target="zip"))


# ---------------------------------------------------------------------- compress
GS_MISSING = pytest.mark.skipif(
    settings.resolve_ghostscript() is None, reason="Ghostscript não instalado"
)


@GS_MISSING
def test_compress_reduz_tamanho(heavy_pdf: Path, tmp_path: Path):
    from app.services.compress import CompressOptions, compress_pdf

    original = heavy_pdf.stat().st_size
    result = compress_pdf(heavy_pdf, tmp_path / "out", CompressOptions(limit_mb=0))
    assert result.final_size < original, "precisa ficar menor que o original"
    assert result.files[0].exists()
    assert result.pages == 4
    assert 0 < result.final_size <= original


@GS_MISSING
def test_compress_divide_quando_passa_do_limite(heavy_pdf: Path, tmp_path: Path):
    from app.services.compress import CompressOptions, compress_pdf

    limit_mb = 0.15
    result = compress_pdf(
        heavy_pdf,
        tmp_path / "out",
        CompressOptions(limit_mb=limit_mb, split=True, quality="screen"),
    )
    assert result.parts > 1, "deve dividir quando não cabe em um arquivo só"
    limit_bytes = int(limit_mb * 1024 * 1024)
    for path in result.files:
        assert path.stat().st_size <= limit_bytes, f"{path.name} passou do limite"
    total_pages = sum(pymupdf.open(f).page_count for f in result.files)
    assert total_pages == 4, "nenhuma página pode se perder na divisão"


@GS_MISSING
def test_compress_grava_pdf_a(heavy_pdf: Path, tmp_path: Path):
    import pikepdf

    from app.services.compress import CompressOptions, compress_pdf

    result = compress_pdf(
        heavy_pdf, tmp_path / "out", CompressOptions(limit_mb=0, pdfa=True)
    )
    with pikepdf.open(result.files[0]) as pdf:
        assert "/OutputIntents" in pdf.Root, "PDF/A precisa do OutputIntent"
        intent = pdf.Root.OutputIntents[0]
        assert str(intent.S) == "/GTS_PDFA1"
        assert "/DestOutputProfile" in intent


@GS_MISSING
def test_compress_sem_ghostscript_mensagem_amigavel(
    heavy_pdf: Path, tmp_path: Path, monkeypatch
):
    from app.services.compress import GhostscriptMissing, CompressOptions, compress_pdf

    monkeypatch.setattr(settings, "ghostscript_cmd", "inexistente-x")
    monkeypatch.setattr(
        type(settings), "resolve_ghostscript", lambda self: None, raising=False
    )
    with pytest.raises(GhostscriptMissing, match="Ghostscript"):
        compress_pdf(heavy_pdf, tmp_path / "out", CompressOptions())
