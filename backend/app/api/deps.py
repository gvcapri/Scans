"""Dependências comuns das rotas.

`current_user` é o ponto único de identidade — todo acesso a arquivo passa
por aqui (é isso que garante o isolamento entre usuários). Na Fase 5 ele
resolve a **sessão JWT** (cookie httpOnly ou header `Authorization:
Bearer`); fora de produção (`ENVIRONMENT != prod`) ainda cai no usuário
local para não atrapalhar o desenvolvimento, e `session_user` existe para
os endpoints que exigem sessão real (ex.: configurar 2FA).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import COOKIE_NAME, decode_token
from app.db.models import User
from app.db.session import get_db

LOCAL_USER_EMAIL = "local@lexscan.local"


def local_user(db: Session) -> User:
    """Usuário local único (semeado no startup)."""
    user = db.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))
    if user is None:
        user = User(email=LOCAL_USER_EMAIL)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def _session_token(request: Request) -> str | None:
    auth = request.headers.get("authorization", "")
    if auth.lower().startswith("bearer "):
        token = auth[7:].strip()
        if token:
            return token
    return request.cookies.get(COOKIE_NAME)


def resolve_session(request: Request, db: Session) -> User | None:
    """Usuário da sessão JWT (ou None)."""
    token = _session_token(request)
    if not token:
        return None
    user_id = decode_token(token, "session")
    if not user_id:
        return None
    user = db.get(User, user_id)
    if user is None or not user.is_active:
        return None
    user._session_authenticated = True  # type: ignore[attr-defined]
    return user


def current_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Usuário da requisição: sessão; em dev, cai no usuário local."""
    user = resolve_session(request, db)
    if user is not None:
        return user
    if settings.environment.lower() != "prod":
        dev = local_user(db)
        dev._session_authenticated = False  # type: ignore[attr-defined]
        return dev
    raise HTTPException(status_code=401, detail="Não autenticado. Faça login.")


def session_user(request: Request, db: Session = Depends(get_db)) -> User:
    """Exige sessão JWT real (sem fallback de desenvolvimento)."""
    user = resolve_session(request, db)
    if user is None:
        raise HTTPException(status_code=401, detail="Faça login para continuar.")
    return user


def owned_or_404(row, user: User) -> None:
    """Garante que o registro pertence ao usuário atual."""
    if row is None or getattr(row, "user_id", None) != user.id:
        raise HTTPException(status_code=404, detail="Registro não encontrado.")
