"""Dependências comuns das rotas.

`current_user` é o ponto único de identidade — todo acesso a arquivo passa
por aqui (é isso que garante o isolamento entre usuários). Na Fase 5 ele
resolve a **sessão JWT** (cookie httpOnly ou header `Authorization:
Bearer`); fora de produção (`ENVIRONMENT != prod`) ainda cai no usuário
local para não atrapalhar o desenvolvimento, e `session_user` existe para
os endpoints que exigem sessão real (ex.: configurar 2FA).
"""

from __future__ import annotations

import datetime as dt

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.core.security import cookie_names, decode_claims
from app.db.models import RevokedToken, User
from app.db.session import get_db

LOCAL_USER_EMAIL = "local@lexscan.local"


def _dev_fallback_ok() -> bool:
    """Só `ENVIRONMENT=dev` explícito cai no usuário local.

    Antes a condição era `!= "prod"`: qualquer valor atípico ("Prod ",
    "staging", "production") silenciava a exigência de sessão e TODO o
    acesso virava o usuário local — fail-open. Agora é fail-closed:
    sem dev explícito, sem fallback.
    """
    return settings.environment.strip().lower() == "dev"


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
    # cookie atual (possivelmente __Host-) + legado de deploys anteriores
    for name in cookie_names():
        token = request.cookies.get(name)
        if token:
            return token
    return None


def decode_live_claims(db: Session, token: str, purpose: str) -> dict | None:
    """Payload do token **que ainda não foi revogado** (ou None).

    Usado para sessão e para desafios de uso único (2FA): um `jti` em
    `revoked_tokens` derruba o token mesmo com assinatura/expiração válidas.
    """
    claims = decode_claims(token, purpose)
    if not claims:
        return None
    jti = claims.get("jti")
    if jti and db.get(RevokedToken, str(jti)) is not None:
        return None
    return claims


def revoke_token(db: Session, token: str, purpose: str = "session") -> None:
    """Revoga um token emitido até o `exp` dele (logout / desafio usado).

    Guarda o `jti` na tabela `revoked_tokens`; `resolve_session` passa a
    recusar o token mesmo que a assinatura ainda seja válida. Tokens antigos
    (sem `jti`) não são revogáveis — expiram sozinhos em 12 h.
    """
    claims = decode_claims(token, purpose)
    if not claims:
        return
    jti = claims.get("jti")
    exp = claims.get("exp")
    if not jti or not exp:
        return
    if db.get(RevokedToken, jti) is not None:
        return  # já revogado
    expires = dt.datetime.fromtimestamp(int(exp), tz=dt.timezone.utc)
    db.add(RevokedToken(jti=str(jti), expires_at=expires))
    db.commit()


def resolve_session(request: Request, db: Session) -> User | None:
    """Usuário da sessão JWT (ou None)."""
    token = _session_token(request)
    if not token:
        return None
    claims = decode_live_claims(db, token, "session")
    if not claims:
        return None
    user_id = str(claims.get("sub") or "") or None
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
    if _dev_fallback_ok():
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
