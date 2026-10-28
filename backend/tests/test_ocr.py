"""Testes do módulo de OCR (Fase 1)."""

from __future__ import annotations

from pathlib import Path

import pymupdf

from app.services.ocr import OcrOptions, ensure_pdf, ocr_document, render_preview


def test_ocr_gera_pdf_pesquisavel(scanned_pdf: Path, tmp_path: Path):
    """PDF escaneado → PDF com camada de texto extraível."""
    result = ocr_document(
        scanned_pdf,
        tmp_path,
        OcrOptions(lang="por+eng", output="pdf", dpi=300),
    )

    assert result.pages == 1
    assert result.files and result.files[0].exists()

    doc = pymupdf.open(result.files[0])
    try:
        assert doc.page_count == 1
        text = doc[0].get_text()
    finally:
        doc.close()

    # a camada invisível precisa conter as palavras da imagem
    assert "PETICAO" in text.upper()
    assert "8.01.0001" in text
    assert result.preview and "PETICAO" in result.preview.upper()


def test_ocr_preview_de_pagina(scanned_pdf: Path, tmp_path: Path):
    """A pré-visualização PNG da página é gerada."""
    png = render_preview(scanned_pdf, page_index=0, dpi=90)
    assert png.startswith(b"\x89PNG")


def test_ocr_saida_txt(scanned_pdf: Path, tmp_path: Path):
    """Saída TXT contém o texto reconhecido."""
    result = ocr_document(scanned_pdf, tmp_path, OcrOptions(output="txt", dpi=200))
    assert result.files[0].suffix == ".txt"
    content = result.files[0].read_text(encoding="utf-8")
    assert len(content.strip()) > 20


def test_ocr_saida_docx(scanned_pdf: Path, tmp_path: Path):
    """Saída DOCX é um arquivo OOXML válido."""
    result = ocr_document(scanned_pdf, tmp_path, OcrOptions(output="docx", dpi=200))
    assert result.files[0].suffix == ".docx"
    assert result.files[0].read_bytes()[:2] == b"PK"  # pacote OOXML


def test_ocr_preserva_texto_existente(text_pdf: Path, tmp_path: Path):
    """Documento com texto não passa por OCR desnecessário (force_ocr=False)."""
    result = ocr_document(text_pdf, tmp_path, OcrOptions(force_ocr=False))
    assert "CONTRATO" in result.preview.upper()

    doc = pymupdf.open(result.files[0])
    try:
        assert "CONTRATO" in doc[0].get_text().upper()
    finally:
        doc.close()


def test_aceita_imagem_como_entrada(scanned_pdf: Path, tmp_path: Path):
    """Imagem PNG entra no pipeline e vira PDF pesquisável."""
    png = tmp_path / "pagina.png"
    doc = pymupdf.open(scanned_pdf)
    pix = doc[0].get_pixmap(dpi=200)
    pix.save(png)
    doc.close()

    # ensure_pdf normaliza imagem -> PDF
    pdf = ensure_pdf(png, tmp_path)
    assert pdf.exists() and pdf.suffix == ".pdf"

    result = ocr_document(png, tmp_path, OcrOptions(dpi=200))
    assert result.pages == 1


def test_opcoes_invalidas_sao_normalizadas():
    """Limites e idiomas inválidos são corrigidos em vez de quebrar o job."""
    opts = OcrOptions.from_dict(
        {"dpi": 9999, "jpeg_quality": 5, "output": "hacked", "lang": "xx"}
    )
    assert opts.dpi == 600
    assert opts.jpeg_quality == 30
    assert opts.output == "pdf"
    assert "xx" not in opts.lang
