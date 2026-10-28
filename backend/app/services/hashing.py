"""Hashes de integridade (SHA-256).

Usado hoje para conferir upload e alimentar o Certificado de Integridade
(Fase 3); a estrutura foi deixada pronta para assinatura digital ICP-Brasil,
onde o hash vira o "conteúdo assinado".
"""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import BinaryIO, Iterable

_CHUNK = 1024 * 1024


def sha256_stream(stream: BinaryIO) -> tuple[str, int]:
    """Devolve (hash_hex, tamanho) lendo o fluxo em blocos."""
    h = hashlib.sha256()
    size = 0
    while True:
        block = stream.read(_CHUNK)
        if not block:
            break
        h.update(block)
        size += len(block)
    return h.hexdigest(), size


def sha256_file(path: str | Path) -> str:
    """Hash SHA-256 (hex) de um arquivo em disco."""
    with open(path, "rb") as fh:
        digest = hashlib.file_digest(fh, "sha256")  # py3.11+
    return digest.hexdigest()


def sha256_bytes(data: bytes) -> str:
    """Hash SHA-256 (hex) de bytes em memória."""
    return hashlib.sha256(data).hexdigest()


def sha256_chunks(chunks: Iterable[bytes]) -> str:
    """Hash de uma sequência de blocos (usado pelo storage cifrado)."""
    h = hashlib.sha256()
    for chunk in chunks:
        h.update(chunk)
    return h.hexdigest()
