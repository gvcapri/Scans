"""Aplicação FastAPI do LexScan.

Montagem: logging (sem conteúdo de documento) → CORS → rotas `/api/*` →
lifespan cria as tabelas, garante o usuário local e configura o Tesseract.
A documentação interativa fica em `/docs` (OpenAPI em `/openapi.json`).
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, cases, compare, files, jobs, meta, presets, redact, search
from app.core.config import settings
from app.core.logging_setup import setup_logging
from app.core.security import hash_password
from app.db.session import init_db, session_scope
from app.db.models import User
from app.api.deps import LOCAL_USER_EMAIL
from app.services.ocr import configure_tesseract
from app.services.retention import purge_expired

log = logging.getLogger("lexscan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Inicialização da aplicação."""
    setup_logging()
    init_db()
    with session_scope() as db:
        from sqlalchemy import select

        user = db.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))
        if user is None:
            user = User(email=LOCAL_USER_EMAIL)
            db.add(user)
        # desenvolvimento: o usuário local ganha uma senha conhecida para
        # a tela de login funcionar; em produção nada é semeado (só registro)
        if settings.environment.lower() != "prod" and not user.password_hash:
            user.password_hash = hash_password(settings.local_dev_password)
    try:
        cmd = configure_tesseract()
        log.info("Tesseract configurado")
    except Exception:
        cmd = "ausente"
        log.warning("Tesseract não encontrado — OCR indisponível")
    log.info("LexScan pronto (storage=%s, fila=%s)", settings.storage_root, settings.task_backend)

    # expurgo LGPD em segundo plano (startup + a cada PURGE_INTERVAL_MINUTES)
    stop_purge = asyncio.Event()

    async def _purge_loop() -> None:
        while True:
            try:
                await asyncio.to_thread(purge_expired)
            except Exception:
                log.exception("Expurgo LGPD falhou")
            try:
                await asyncio.wait_for(
                    stop_purge.wait(),
                    timeout=max(60, settings.purge_interval_minutes * 60),
                )
            except asyncio.TimeoutError:
                continue
            return

    purge_task = asyncio.create_task(_purge_loop())
    yield
    stop_purge.set()
    await purge_task


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
    app.include_router(auth.router, prefix=prefix)
    app.include_router(files.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)
    app.include_router(presets.router, prefix=prefix)
    app.include_router(redact.router, prefix=prefix)
    app.include_router(search.router, prefix=prefix)
    app.include_router(compare.router, prefix=prefix)
    app.include_router(cases.router, prefix=prefix)
    return app


app = create_app()
