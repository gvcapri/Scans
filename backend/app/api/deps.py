"""Dependências comuns das rotas.

`current_user` é o ponto único de identidade: a Fase 5 troca a implementação
por JWT + 2FA e nenhum outro código muda (todo acesso a arquivo já passa
por aqui — é isso que garante o isolamento entre usuários).
"""

from __future__ import annotations

from fastapi import Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import User
from app.db.session import get_db

LOCAL_USER_EMAIL = "local@lexscan.local"


def current_user(db: Session = Depends(get_db)) -> User:
    """Usuário da requisição (Fase 1: usuário local único)."""
    user = db.scalar(select(User).where(User.email == LOCAL_USER_EMAIL))
    if user is None:
        user = User(email=LOCAL_USER_EMAIL)
        db.add(user)
        db.commit()
        db.refresh(user)
    return user


def owned_or_404(row, user: User) -> None:
    """Garante que o registro pertence ao usuário atual."""
    if row is None or getattr(row, "user_id", None) != user.id:
        raise HTTPException(status_code=404, detail="Registro não encontrado.")
