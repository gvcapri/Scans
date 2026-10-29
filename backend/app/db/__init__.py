"""Camada de acesso a dados do LexScan.

Módulo raiz: acesso ao engine, ao factory de sessões e à inicialização do
esquema. Nada de importações circulares aqui — os modelos são importados
explicitamente por quem precisa.

  * `engine`      — conexão singleton (SQLite dev / PostgreSQL Docker);
  * `get_db()`    — dependência FastAPI: uma sessão por requisição;
  * `session_scope()` — sessão autocommit para workers e jobs;
  * `init_tables()` — cria as tabelas + o índice de busca (Fase 4) de
    forma **idempotente e sem corrida** entre api e worker.
"""

from __future__ import annotations

import logging

from sqlalchemy import text

from app.db.session import engine, get_db, session_scope
from app.db.search import init_search

log = logging.getLogger("lexscan.db")

# Chave arbitrária do advisory lock que serializa o DDL entre processos
# (api e worker sobem ao mesmo tempo no compose).
_DDL_LOCK_KEY = 74_701_001


class _ddl_lock:
    """Advisory lock do Postgres: só um processo cria as tabelas por vez.

    Em outros dialeto (SQLite) não há concorrência entre contêineres e o
    `create_all` já é idempotente — o contexto vira um no-op.
    """

    def __enter__(self):
        self._conn = None
        if engine.dialect.name == "postgresql":
            try:
                self._conn = engine.connect()
                self._conn.execute(
                    text("SELECT pg_advisory_lock(:k)"), {"k": _DDL_LOCK_KEY}
                )
            except Exception:
                log.warning(
                    "Não foi possível obter o advisory lock de DDL; "
                    "seguindo sem ele (create_all continua idempotente).",
                    exc_info=True,
                )
                if self._conn is not None:
                    try:
                        self._conn.close()
                    except Exception:
                        pass
                    self._conn = None
        return self

    def __exit__(self, *exc) -> None:
        if self._conn is not None:
            try:
                self._conn.execute(
                    text("SELECT pg_advisory_unlock(:k)"), {"k": _DDL_LOCK_KEY}
                )
            except Exception:
                log.debug("advisory_unlock falhou (a conexão fecha do mesmo jeito)")
            finally:
                self._conn.close()


def _already_exists(exc: BaseException) -> bool:
    """True quando o erro é 'objeto já existe' (outro processo criou antes)."""
    msg = str(exc).lower()
    return (
        "already exists" in msg
        or "duplicate key" in msg
        or "duplicate table" in msg
        or "relation" in msg and "exists" in msg
    )


def init_tables() -> bool:
    """Cria as tabelas + o índice de busca (Fase 4). Idempotente.

    * Postgres: advisory lock serializa api × worker (sem corrida de DDL).
    * Objeto já existe (corrida residual em outro dialeto): segue em frente.
    * A busca é fail-safe: se `init_search` falhar, só ela desliga (loga o
      erro real) e o app continua subindo.
    """
    from app.db import models  # registra os modelos no Base

    with _ddl_lock():
        try:
            models.Base.metadata.create_all(bind=engine)
        except Exception as exc:
            if not _already_exists(exc):
                log.error("Falha ao criar as tabelas do banco", exc_info=True)
                raise
            log.info("Tabelas já existiam (outro processo criou antes).")

    try:
        ok = init_search(engine)
    except Exception:
        log.error("init_search levantou exceção: busca desabilitada", exc_info=True)
        return False
    if not ok:
        log.error("Índice de busca não pôde ser criado: apenas a busca fica fora.")
    return ok


__all__ = ["engine", "get_db", "session_scope", "init_tables"]
