"""Aplicação principal do JudiFiles.

Cria o estado da API (create_app), aplica o middleware ModSecurity e monta
os routers. Separados por seção para facilitar a leitura e futuras alterações.
"""

import logging
import threading
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.core.config import settings
from app.core.modsecurity import setup_modsecurity
from app.core.rate_limit import setup_rate_limit
from app.api.routes import (
    auth,
    cases,
    compare,
    files,
    integrity,
    jobs,
    meta,
    ocr,
    presets,
    redact,
    search,
)
from app.api.routes import blind  # noqa: F401

log = logging.getLogger("lexscan")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Lifespan: inicializa persistência e rotas. Chamado uma vez por processo."""
    # Persistência: cria tabelas se não existirem (SQLAlchemy 2.0 / sync engine).
    from app.db import init_tables

    init_tables()
    # Seção de rotas: registra todas as APIs do sistema (meta, auth, files,
    # jobs, presets, redact, search, compare, cases). Nenhum outro módulo
    # deve incluir um router manualmente.
    stop_purge = _start_purge_loop()
    yield
    if stop_purge is not None:
        stop_purge.set()


def _start_purge_loop() -> threading.Event | None:
    """Expurgo LGPD (RETENTION_HOURS) em segundo plano — modo local.

    Roda no startup e a cada PURGE_INTERVAL_MINUTES dentro do próprio
    processo da API (TASK_BACKEND=local, o padrão nesta VM de 1 GB),
    garantindo que o derrame automático aconteça mesmo sem worker Celery.
    `PURGE_INTERVAL_MINUTES=0` desliga o agendador (o "Apagar agora" da
    rota DELETE /files/{id} continua valendo).
    """
    from app.services.retention import purge_expired

    try:
        purge_expired()
    except Exception:
        log.error("Expurgo LGPD no startup falhou", exc_info=True)

    interval = settings.purge_interval_minutes
    if interval <= 0:
        return None

    stop = threading.Event()

    def _loop() -> None:
        while not stop.wait(interval * 60):
            try:
                purge_expired()
            except Exception:  # nunca derruba o loop
                log.error("Expurgo LGPD periódico falhou", exc_info=True)

    threading.Thread(target=_loop, daemon=True, name="lgpd-purge").start()
    log.info("Expurgo LGPD agendado a cada %d minuto(s)", interval)
    return stop


def create_app() -> FastAPI:
    """Factory da aplicação (usada também nos testes)."""
    app = FastAPI(
        title="JudiFiles API",
        version="1.0.0",
        description=(
            "API de conversão e tratamento de documentos jurídicos: OCR, "
            "PDF Blindado, compressão para tribunais, redação de dados, "
            "numeração, certificado de integridade e pesquisa em acervo."
        ),
        lifespan=lifespan,
        contact={"name": "JudiFiles"},
        license_info={"name": "Proprietário"},
    )

    # Middleware de segurança base (robustez de entrada, não bloqueio ativo).
    setup_modsecurity(app)

    # Rate limiting (APIs, não rotas estáticas).
    setup_rate_limit(app)

    # Roteamento dos módulos.
    prefix = settings.api_prefix or "/api"
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(meta.router, prefix=prefix)
    app.include_router(auth.router, prefix=prefix)
    app.include_router(files.router, prefix=prefix)
    app.include_router(jobs.router, prefix=prefix)
    app.include_router(presets.router, prefix=prefix)
    app.include_router(redact.router, prefix=prefix)
    app.include_router(search.router, prefix=prefix)
    app.include_router(compare.router, prefix=prefix)
    app.include_router(integrity.router, prefix=prefix)
    app.include_router(ocr.router, prefix=prefix)
    app.include_router(blind.router, prefix=prefix)
    app.include_router(cases.router, prefix=prefix)

    return app


# Instância publicada para WSGI/uvicorn e para o entrypoint do Docker.
app = create_app()
setup_modsecurity(app)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
