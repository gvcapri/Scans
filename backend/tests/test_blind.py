"""Testes do PDF Blindado (Fase 1) — o módulo mais crítico do produto."""

from __future__ import annotations

from pathlib import Path

import pikepdf
import pymupdf

from app.services.blind import BlindOptions, blind_pdf


def test_blind_achata_documento(text_pdf: Path, tmp_path: Path):
    """PDF com texto vira PDF só-imagem: nada de texto selecionável."""
    result = blind_pdf(
        text_pdf,
        tmp_path,
        BlindOptions(dpi=150, jpeg_quality=70),
    )

    assert result.pages == 1
    assert result.file.exists() and result.file.stat().st_size > 1000

    doc = pymupdf.open(result.file)
    try:
        # sem camada de texto...
        assert doc[0].get_text().strip() == ""
        # ...mas com imagem cobrindo a página
        assert doc[0].get_images(full=True), "página deveria conter imagem"
    finally:
        doc.close()


def test_blind_remove_metadados(text_pdf: Path, tmp_path: Path):
    """Autor, software e histórico de edição saem zerados (DocInfo + XMP)."""
    result = blind_pdf(text_pdf, tmp_path, BlindOptions(dpi=150))

    with pikepdf.open(result.file) as pdf:
        docinfo_keys = list(pdf.docinfo.keys())
        assert "/Metadata" not in pdf.Root
        for key in ("/OpenAction", "/AA", "/AcroForm"):
            assert key not in pdf.Root
    # nenhum metadado de identificação (DocInfo zerado)
    leftovers = [k for k in docinfo_keys if k != "/ID"]
    assert not leftovers, f"metadados restantes: {leftovers}"


def test_blind_com_senha_restringe_permissoes(text_pdf: Path, tmp_path: Path):
    """Senha de proprietário criptografa e bloqueia cópia/edição."""
    result = blind_pdf(
        text_pdf,
        tmp_path,
        BlindOptions(dpi=150, owner_password="segredo-forte-123"),
    )

    with pikepdf.open(result.file) as pdf:
        assert pdf.is_encrypted
        perms = pdf.allow
        # extração/cópia bloqueadas (não mantivemos camada de texto)
        assert perms.extract is False
        assert perms.modify_other is False

    # sem senha de abertura o arquivo abre normalmente (owner password only)
    doc = pymupdf.open(result.file)
    try:
        assert doc.page_count == 1
        assert not doc.needs_pass
    finally:
        doc.close()


def test_blind_mantem_camada_pesquisavel(text_pdf: Path, tmp_path: Path):
    """Toggle de camada de texto: OCR invisível por cima da imagem."""
    result = blind_pdf(
        text_pdf,
        tmp_path,
        BlindOptions(dpi=300, keep_text_layer=True, lang="por+eng"),
    )

    assert result.has_text_layer
    doc = pymupdf.open(result.file)
    try:
        text = doc[0].get_text().upper()
        images = doc[0].get_images(full=True)
    finally:
        doc.close()
    assert images, "continua sendo imagem (achatado)"
    assert "CONTRATO" in text, "camada invisível deve permitir busca"


def test_blind_tamanho_configuravel(text_pdf: Path, tmp_path: Path):
    """Mais DPI/qualidade = arquivo maior: a escolha impacta o tamanho."""
    low = blind_pdf(text_pdf, tmp_path / "l", BlindOptions(dpi=150, jpeg_quality=40))
    high = blind_pdf(text_pdf, tmp_path / "h", BlindOptions(dpi=300, jpeg_quality=95))
    assert high.size > low.size
