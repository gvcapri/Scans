"""Aplicação FastAPI do LexScan.

Montagem: logging (sem conteúdo de documento) → CORS → rotas `/api/*` →
lifespan cria as tabelas, garante o usuário local e configura o Tesseract.
A documentação interativa fica em `/docs` (OpenAPI em `/openapi.json`).
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import files, jobs, meta, presets, redact
from app.core.config import settings
from app.core.logging_setup import setup_logging
from app.db.session import init_db, session_scope
from app.db.models import User
from app.services.ocr import configure_tesseract

log = logging.getLogger("lexscan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialização da aplicação."""
    setup_logging()
    init_db()
    with session_scope() as db:
        from sqlalchemy import select

        if not db.scalar(select(User).limit(1)):
            db.add(User(email="local@lexscan.local"))
    try:
        cmd = configure_tesseract()
        log.info("Tesseract configurado")
    except Exception:
        cmd = "ausente"
        log.warning("Tesseract não encontrado — OCR indisponível")
    log.info("LexScan pronto (storage=%s, fila=%s)", settings.storage_root, settings.task_backend)
    yield


def create_app() -> FastAPI:
    """Factory da aplicação (usada também nos testes)."""
    app = FastAPI(
        title="LexScan API",
        version="1.0.0",
        description=(
            "API de conversão e tratamento de documentos jurídicos: OCR, "
            "PDF Blindado, compressão para tribunais, redação de dados, "
            "numeração, certificado de integridade e pesquisa em acervo.\n\n"
            "Documentos são tratados como sigilosos: armazenamento cifrado "
            "em repouso, expurgo automático e isolamento por usuário."
        ),
        lifespan=lifespan,
        contact={"name": "LexScan"},
        license_info={"name": "Proprietário"},
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    prefix = settings.api_prefix or "/api"
    app.include_router(meta.router, prefix=prefix)
    app.include_router(files.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)
    app.include_router(presets.router, prefix=prefix)
    app.include_router(redact.router, prefix=prefix)
    return app


app = create_app()
