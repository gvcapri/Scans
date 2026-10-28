"""Logging do LexScan.

REGRA DE OURO (LGPD): nunca registrar conteúdo de documento — nem nome de
arquivo original, nem texto extraído, nem caminho completo. Logamos apenas
identificadores opacos (job_id, file_id), tamanho e tempos.
"""

from __future__ import annotations

import logging
import re

# Padrões que jamais devem aparecer nos logs (conteúdo potencialmente sigiloso).
_FORBIDDEN = re.compile(r"(\.pdf|\.docx?|\.png|\.jpe?g|\.tiff?|/storage/|\\storage\\)", re.I)


class _RedactFilter(logging.Filter):
    """Remove trechos que parecem conter dados de documento."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:  # pragma: no cover - segurança do logger
            return True
        if _FORBIDDEN.search(msg):
            record.msg = "[mensagem suprimida: possivelmente contém dado de documento] args=%s"
            record.args = ()
        return True


def setup_logging(level: int = logging.INFO) -> None:
    """Configura o logger raiz com redação automática."""
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    )
    handler.addFilter(_RedactFilter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    # Silencia bibliotecas barulhentas, mantendo as nossas.
    for noisy in ("uvicorn.access", "multipart", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
