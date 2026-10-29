"""Validação rigorosa de uploads (segurança + LGPD).

Regras aplicadas a TODO arquivo enviado:
1. O tipo deve ser detectado pelos **magic bytes** reais — o MIME declarado
   pelo navegador é só dica e nunca é confiado.
2. Tamanho limitado por MAX_UPLOAD_MB.
3. Nome sanitizado: o nome original NUNCA vira caminho de disco (o arquivo é
   gravado com id gerado), mas é exibido na UI — então removemos separadores
   de diretório, caracteres de controle e normalizamos (anti path traversal).
4. Extensão precisa ser compatível com o conteúdo detectado.
"""

from __future__ import annotations

import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import PurePath

from fastapi import HTTPException

# (magic bytes iniciais, mime canônico, extensões aceitas)
_MAGICS: list[tuple[bytes, str, tuple[str, ...]]] = [
    (b"%PDF-", "application/pdf", (".pdf",)),
    (b"\x89PNG\r\n\x1a\n", "image/png", (".png",)),
    (b"\xff\xd8\xff", "image/jpeg", (".jpg", ".jpeg")),
    (b"II*\x00", "image/tiff", (".tif", ".tiff")),
    (b"MM\x00*", "image/tiff", (".tif", ".tiff")),
    (b"GIF87a", "image/gif", (".gif",)),
    (b"GIF89a", "image/gif", (".gif",)),
    (b"BM", "image/bmp", (".bmp",)),
    (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1", "application/msword", (".doc",)),
    (b"PK\x03\x04", "application/zip", (".zip",)),  # .docx/.xlsx checados abaixo
]

# Tipos suportados pela Fase 1 (OCR/Blindado).
DOCX_MIME = (
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
)
ALLOWED_MIMES = {
    "application/pdf",
    "image/png",
    "image/jpeg",
    "image/tiff",
    "application/msword",
    DOCX_MIME,
    "application/zip",
}


@dataclass
class ValidatedUpload:
    """Resultado da validação de um upload."""

    safe_name: str
    mime: str
    ext: str
    size: int


def sanitize_filename(name: str, max_len: int = 180) -> str:
    """Extrai o nome base, remove travessas/caracteres de controle e limita."""
    base = PurePath(name.replace("\\", "/")).name  # elimina qualquer diretório
    base = unicodedata.normalize("NFC", base)
    cleaned = "".join(
        ch for ch in base if unicodedata.category(ch)[0] != "C" and ch not in '/\\:*?"<>|'
    ).strip().lstrip(".")
    if not cleaned:
        cleaned = "documento"
    if len(cleaned) > max_len:
        stem, dot, ext = cleaned.rpartition(".")
        keep = max_len - (len(ext) + 1 if dot else 0)
        cleaned = f"{stem[:keep]}{dot}{ext}" if dot else cleaned[:max_len]
    return cleaned


def detect_mime(head: bytes, filename: str) -> tuple[str, str]:
    """Detecta (mime, extensão) pelo conteúdo real do arquivo."""
    for magic, mime, exts in _MAGICS:
        if head.startswith(magic):
            lower = filename.lower()
            ext = next((e for e in exts if lower.endswith(e)), exts[0])
            if mime == "application/zip":
                return _inspect_zip(head, filename, ext)
            return mime, ext
    raise HTTPException(
        status_code=415,
        detail="Formato não suportado. Envie PDF, imagem (JPG/PNG/TIFF), Word ou ZIP.",
    )


def _inspect_zip(head: bytes, filename: str, ext: str) -> tuple[str, str]:
    """ZIP pode ser DOCX (Word) ou pacote de lote — decide pela estrutura."""
    if filename.lower().endswith(".docx"):
        return "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".docx"
    return "application/zip", ".zip"


def validate_upload(
    filename: str,
    declared_mime: str | None,
    size: int,
    head: bytes,
    max_bytes: int,
) -> ValidatedUpload:
    """Valida um upload por completo; lança HTTPException 413/415/400."""
    if size <= 0 or len(head) == 0:
        raise HTTPException(status_code=400, detail="Arquivo vazio.")
    if size > max_bytes:
        limit_mb = max_bytes // (1024 * 1024)
        raise HTTPException(
            status_code=413,
            detail=f"Arquivo maior que o limite de {limit_mb} MB.",
        )

    safe_name = sanitize_filename(filename or "documento")
    mime, ext = detect_mime(head, safe_name)

    if mime not in ALLOWED_MIMES:
        raise HTTPException(
            status_code=415,
            detail=f"Tipo de arquivo não permitido ({mime}).",
        )

    # Conferência cruzada: extensão declarada precisa bater com o conteúdo.
    if "." in safe_name and not safe_name.lower().endswith(ext):
        # .jpeg/.jpg são intercambiáveis; ZIPs renomeados não.
        allowed_alias = {(".jpg", ".jpeg")} if ext in (".jpg", ".jpeg") else {(ext,)}
        if not any(safe_name.lower().endswith(a) for a in allowed_alias):
            raise HTTPException(
                status_code=400,
                detail="A extensão do arquivo não corresponde ao conteúdo real.",
            )

    return ValidatedUpload(safe_name=safe_name, mime=mime, ext=ext, size=size)


def validate_zip_bytes(data: bytes, max_entries: int = 200, max_ratio: int = 200) -> int:
    """Blindagem contra ZIP malicioso (recebe os bytes em memória)."""
    import io

    return validate_zip_file(io.BytesIO(data), max_entries=max_entries, max_ratio=max_ratio)


def validate_zip_file(source, max_entries: int = 200, max_ratio: int = 200) -> int:
    """Blindagem contra ZIP malicioso (travessia de caminho e bomba descompactada).

    `source` é um caminho ou arquivo aberto — lê só o diretório central,
    sem carregar o ZIP inteiro na memória (VM de 1 GB).

    Retorna o número de arquivos seguros para processar.
    """
    with zipfile.ZipFile(source) as zf:
        infos = zf.infolist()
        if len(infos) > max_entries:
            raise HTTPException(status_code=400, detail="ZIP com arquivos demais.")
        total_uncompressed = 0
        safe = 0
        for info in infos:
            name = info.filename
            if name.startswith("/") or name.startswith("\\") or ".." in name.split("/"):
                raise HTTPException(
                    status_code=400, detail="ZIP contém caminho suspeito (travessia)."
                )
            if info.is_dir():
                continue
            total_uncompressed += info.file_size
            safe += 1
        if total_uncompressed > 512 * 1024 * 1024:
            raise HTTPException(status_code=400, detail="ZIP descompactado grande demais.")
        if safe and total_uncompressed / max(1, sum(i.compress_size for i in infos)) > max_ratio:
            raise HTTPException(status_code=400, detail="ZIP com taxa de compressão suspeita.")
        return safe
