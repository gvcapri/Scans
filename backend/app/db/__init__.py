"""Camada de acesso a dados do LexScan.

Módulo raiz: acesso ao engine, ao factory de sessões e à inicialização do
esquema. Nada de importações circulares aqui — os modelos são importados
explicitamente por quem precisa.

  * `engine`      — conexão singleton (SQLite dev / PostgreSQL Docker);
  * `get_db()`    — dependência FastAPI: uma sessão por requisição;
  * `session_scope()` — sessão autocommit para workers e jobs;
  * `init_tables()` — cria as tabelas + o índice de busca (Fase 4) com
    `CREATE ALL`; em deploy focado usaríamos **Alembic**.
"""

from app.db.session import engine, get_db, session_scope
from app.db.search import init_search


def init_tables() -> None:
    """Cria as tabelas + o índice de busca (Fase 4)."""
    from app.db import models  # registra os modelos no Base

    models.Base.metadata.create_all(bind=engine)
    init_search(engine)


__all__ = ["engine", "get_db", "session_scope", "init_tables"]
