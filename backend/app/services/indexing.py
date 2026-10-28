"""Extração de texto para o índice de busca (Fase 4).

O texto de um PDF nasceu-digital mora no próprio PDF; aqui nós o
extrairmos (com teto de páginas/tamanho) e alimentamos o índice
full-text. Documentos só-imagem não são OCRizados na indexação (custo
alto demais para um upload) — depois de rodar o OCR, a **saída** já é
indexada com o texto reconhecido.

A indexação é *best-effort*: falha aqui nunca derruba o upload nem um
job; só deixa o documento fora da busca.
"""

from __future__ import annotations

import logging
import re
import tempfile
import zipfile
from html import unescape
from pathlib import Path

from app.db.search import index_file, remove_file
from app.db.session import engine

log = logging.getLogger("lexscan.indexing")

MAX_PAGES = 200
MAX_CHARS = 300_000


def extract_text(path: Path) -> str:
    """Texto de um documento para indexação ('' quando não há como extrair)."""
    ext = path.suffix.lower()
    try:
        if ext == ".pdf":
            import pymupdf

            with pymupdf.open(path) as doc:
                parts: list[str] = []
                total = 0
                for page in doc:
                    if page.number >= MAX_PAGES:
                        break
                    text = page.get_text() or ""
                    total += len(text)
                    parts.append(text)
                    if total >= MAX_CHARS:
                        break
                return "".join(parts)[:MAX_CHARS]
        if ext in {".txt", ".md", ".csv", ".log"}:
            raw = path.read_bytes()[:MAX_CHARS]
            for encoding in ("utf-8", "latin-1"):
                try:
                    return raw.decode(encoding)
                except UnicodeDecodeError:
                    continue
            return ""
        if ext == ".docx":
            return _docx_text(path)[:MAX_CHARS]
    except Exception:
        log.debug("Não foi possível extrair texto de %s", path.name, exc_info=True)
    return ""


def _docx_text(path: Path) -> str:
    """Texto de um .docx (word/document.xml, sem dependência extra)."""
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="replace")
    xml = re.sub(r"</w:p>", "\n", xml)
    text = re.sub(r"<[^>]+>", "", xml)
    return unescape(text)


def index_stored_file(file_id: str, user_id: str, name: str, path: Path) -> None:
    """Extrai o texto de `path` e grava no índice (substitui a entrada)."""
    content = extract_text(path)
    index_file(file_id, user_id, name, content, engine)


def index_from_storage(file_id: str, user_id: str, name: str) -> None:
    """Materializa o arquivo cifrado do storage e o indexa no lugar."""
    from app.services.storage import get_storage

    with tempfile.TemporaryDirectory(prefix="lexscan-index-") as tmp:
        path = get_storage().materialize(user_id, file_id, Path(tmp), name)
        index_stored_file(file_id, user_id, name, path)


def drop_from_index(file_id: str) -> None:
    """Apaga do índice (chamado junto com o 'Apagar agora' / expurgo)."""
    try:
        remove_file(file_id, engine)
    except Exception:
        log.debug("Não foi possível remover %s do índice", file_id, exc_info=True)
