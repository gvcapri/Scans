"""Varredura antivírus opcional (ClamAV) — Fase 5.

Com `CLAMAV_ENABLED=true` todo upload é verificado no daemon `clamd`
(protocolo INSTREAM na porta 3310) **antes** de tocar o storage:

* `FOUND` → 415 e o arquivo nunca é gravado;
* daemon inacessível → 503 (falha fechada: não entra nada sem varredura).

Desligado por padrão (dev local não precisa do daemon); no Compose o
serviço `clamav` existe sob profile opcional.
"""

from __future__ import annotations

import logging
import socket
from typing import BinaryIO

from fastapi import HTTPException

from app.core.config import settings

log = logging.getLogger("lexscan.antivirus")

_CHUNK = 1024 * 1024
_TIMEOUT = 15.0


def scan_stream(stream: BinaryIO, filename: str = "arquivo") -> None:
    """Varre um fluxo no clamd; levanta 415/503 quando aplicável."""
    if not settings.clamav_enabled:
        return

    try:
        sock = socket.create_connection(
            (settings.clamav_host, settings.clamav_port), timeout=_TIMEOUT
        )
    except OSError as exc:
        log.error("ClamAV inacessível em %s:%s", settings.clamav_host, settings.clamav_port)
        raise HTTPException(
            status_code=503,
            detail="Antivírus indisponível: envio temporariamente bloqueado.",
        ) from exc

    try:
        sock.settimeout(_TIMEOUT)
        sock.sendall(b"zINSTREAM\0")
        sent = 0
        while True:
            chunk = stream.read(_CHUNK)
            if not chunk:
                break
            sock.sendall(len(chunk).to_bytes(4, "big") + chunk)
            sent += len(chunk)
        sock.sendall(b"\x00\x00\x00\x00")  # fim do fluxo
        if sent == 0:
            raise HTTPException(status_code=400, detail="Arquivo vazio.")

        data = b""
        while b"\0" not in data:
            part = sock.recv(4096)
            if not part:
                break
            data += part
    except OSError as exc:
        raise HTTPException(
            status_code=503,
            detail="Antivírus indisponível: envio temporariamente bloqueado.",
        ) from exc
    finally:
        sock.close()
        stream.seek(0)

    reply = data.decode("utf-8", errors="replace").strip()
    if "FOUND" in reply:
        log.warning("Malware bloqueado: %s", filename)
        raise HTTPException(
            status_code=415,
            detail="Arquivo bloqueado pelo antivírus. Envio recusado.",
        )
    if not reply.startswith("OK"):
        log.error("Resposta inesperada do clamd: %r", reply[:200])
        raise HTTPException(
            status_code=503,
            detail="Antivírus indisponível: envio temporariamente bloqueado.",
        )
