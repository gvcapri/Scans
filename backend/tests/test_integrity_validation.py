"""Testes de hash/integridade e de validação de uploads."""

from __future__ import annotations

import hashlib

import pytest
from fastapi import HTTPException

from app.services.hashing import sha256_bytes, sha256_file, sha256_stream
from app.services.validation import sanitize_filename, validate_upload, validate_zip_bytes

MAX = 10 * 1024 * 1024


# --------------------------------------------------------------------- hash
def test_sha256_file_confere_com_hashlib(tmp_path):
    data = b"LexScan - documento juridico" * 1000
    path = tmp_path / "doc.bin"
    path.write_bytes(data)

    assert sha256_file(path) == hashlib.sha256(data).hexdigest()
    assert sha256_bytes(data) == hashlib.sha256(data).hexdigest()
    with open(path, "rb") as fh:
        assert sha256_stream(fh)[0] == hashlib.sha256(data).hexdigest()


def test_sha256_stream_retorna_tamanho(tmp_path):
    data = b"abc" * 100
    path = tmp_path / "x.bin"
    path.write_bytes(data)
    with open(path, "rb") as fh:
        digest, size = sha256_stream(fh)
    assert size == len(data)
    assert len(digest) == 64


# ---------------------------------------------------------------- validação
def test_detecta_pdf_real():
    info = validate_upload("peticao.pdf", "text/plain", 100, b"%PDF-1.7 ...", MAX)
    # mente sobre o MIME declarado: o magic bytes manda
    assert info.mime == "application/pdf"


def test_rejeita_arquivo_com_extensao_falsa():
    with pytest.raises(HTTPException) as err:
        validate_upload("nota.jpg", "image/jpeg", 100, b"%PDF-1.4", MAX)
    assert err.value.status_code == 400


def test_rejeita_formato_desconhecido():
    with pytest.raises(HTTPException) as err:
        validate_upload("malware.exe", "application/octet-stream", 100, b"MZ\x90", MAX)
    assert err.value.status_code == 415


def test_rejeita_acima_do_limite():
    with pytest.raises(HTTPException) as err:
        validate_upload("grande.pdf", "application/pdf", MAX + 1, b"%PDF-", MAX)
    assert err.value.status_code == 413


def test_rejeita_arquivo_vazio():
    with pytest.raises(HTTPException) as err:
        validate_upload("vazio.pdf", "application/pdf", 0, b"", MAX)
    assert err.value.status_code == 400


@pytest.mark.parametrize(
    "brutal,esperado",
    [
        ("../../etc/passwd", "etc/passwd".split("/")[-1]),
        ("..\\..\\windows\\system32\\cmd.exe", "cmd.exe"),
        ("/home/advogado/peticao.pdf", "peticao.pdf"),
        ("...", "documento"),
        ("", "documento"),
        ("nome:invalido?.pdf", "nomeinvalido.pdf"),
    ],
)
def test_nome_de_arquivo_anti_traversal(brutal, esperado):
    assert sanitize_filename(brutal) == esperado


def test_docx_e_reconhecido_como_word():
    # DOCX é um ZIP com word/document.xml
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("[Content_Types].xml", "<Types/>")
        zf.writestr("word/document.xml", "<w:document/>")
    info = validate_upload("contrato.docx", "application/zip", 100, buf.getvalue()[:400], MAX)
    assert info.mime.endswith("wordprocessingml.document")


def test_zip_malicioso_com_travessia_e_rejeitado():
    import io
    import zipfile

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("../../etc/passwd", "x")
    with pytest.raises(HTTPException):
        validate_zip_bytes(buf.getvalue())
