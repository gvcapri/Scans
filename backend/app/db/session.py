"""Sessões do SQLAlchemy (SQLite em dev, PostgreSQL no Docker)."""

from __future__ import annotations

from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings


class Base(DeclarativeBase):
    """Base comum para todos os modelos."""


_connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine = create_engine(
    settings.database_url,
    connect_args=_connect_args,
    pool_pre_ping=True,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Session:
    """Dependência FastAPI: uma sessão por requisição."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@contextmanager
def session_scope() -> Session:
    """Sessão autocommit para uso fora das rotas (worker, jobs, expurgo)."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    """Cria as tabelas (MVP; em produção usaríamos Alembic)."""
    from app.db import models  # noqa: F401  (registra os modelos)
    from app.db.search import init_search

    Base.metadata.create_all(bind=engine)
    init_search(engine)  # índice full-text da Fase 4
