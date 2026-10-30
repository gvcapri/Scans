"""Rotas de autenticação (Fase 5): registro, login, 2FA e sessão.

Fluxos:

* `POST /auth/register` — cria a conta (e-mail + senha) e já entra;
* `POST /auth/login` — valida a senha; se o 2FA estiver ligado devolve
  um desafio de 5 min e o código vai em `POST /auth/login/2fa`;
* `POST /auth/2fa/enable` → devolve segredo + QR (otpauth://) e espera
  `POST /auth/2fa/confirm` com um código válido **antes** de gravar;
* `DELETE /auth/2fa` — desliga o 2FA (exige código corrente);
* `POST /auth/logout` — limpa o cookie; `GET /auth/me` — quem sou.

O token sai em **cookie httpOnly** (navegador) e no corpo da resposta
(scriptos/testes). Tentativas são limitadas por IP (registro) e
IP+e-mail (login) para conter força bruta.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, decode_live_claims, revoke_token, session_user
from app.core.config import settings
from app.core.rate_limit import require_within
from app.core.security import (
    TWOFA_MINUTES,
    challenge_token,
    cookie_name,
    cookie_names,
    hash_password,
    new_totp_secret,
    session_token,
    totp_uri,
    valid_email,
    valid_password,
    verify_password,
    verify_totp,
)
from app.db.models import User
from app.db.session import get_db

router = APIRouter(prefix="/auth", tags=["autenticação"])


class Credentials(BaseModel):
    """E-mail + senha."""

    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=1, max_length=128)


class TwoFAPayload(BaseModel):
    """Código de 6 dígitos."""

    code: str = Field(..., min_length=6, max_length=8)


class ChallengePayload(BaseModel):
    """Desafio 2FA + código."""

    challenge: str = Field(..., min_length=10)
    code: str = Field(..., min_length=6, max_length=8)


def _set_cookie(response: Response, token: str) -> None:
    response.set_cookie(
        key=cookie_name(),
        value=token,
        max_age=60 * 60 * 12,
        httponly=True,
        samesite="lax",
        # atrás do Caddy o tráfego é sempre HTTPS em prod; em dev (http)
        # o cookie precisa ser aceito sem TLS
        secure=settings.environment.lower() == "prod",
        path="/",
    )


def _public(user: User) -> dict:
    return {
        "id": user.id,
        "email": user.email,
        "two_factor_enabled": bool(user.totp_secret),
    }


@router.post("/register", summary="Criar conta")
def register(
    payload: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    require_within(request, "registro", _ip(request), settings.auth_rate_limit_per_min)

    email = (payload.email or "").strip().lower()
    if not valid_email(email):
        raise HTTPException(status_code=400, detail="E-mail inválido.")
    if not valid_password(payload.password):
        raise HTTPException(
            status_code=400, detail="A senha precisa ter de 8 a 128 caracteres."
        )
    if settings.environment.lower() == "prod" and email.endswith("@lexscan.local"):
        raise HTTPException(status_code=400, detail="E-mail não permitido.")

    # Regras de cadastro validadas NO BACKEND (o frontend nunca é a fonte):
    # REGISTRATION_OPEN=false fecha o cadastro (só convidados) e
    # ALLOWED_EMAIL_DOMAINS restringe o domínio quando configurado.
    if not settings.features.registration_open:
        raise HTTPException(
            status_code=403, detail="Cadastro temporariamente fechado."
        )
    allowed = settings.allowed_email_domains.strip().lower()
    if allowed:
        domains = {d.strip() for d in allowed.split(",") if d.strip()}
        if email.rsplit("@", 1)[-1] not in domains:
            raise HTTPException(
                status_code=403, detail="E-mail não permitido neste domínio."
            )

    # Argon2 ANTES da checagem de duplicidade: o custo de resposta é o
    # mesmo com e-mail livre ou ocupado — fecha o canal de tempo na
    # enumeração de usuários. O 409 continua sendo exposto por UX: sem
    # fluxo de verificação por e-mail não há como informar "conta já
    # existe" sem revelar a existência (mitigado por rate limit por IP).
    password_hash = hash_password(payload.password)

    existing = db.scalar(select(User).where(User.email == email))
    if existing is not None:
        raise HTTPException(status_code=409, detail="Já existe uma conta com esse e-mail.")

    user = User(email=email, password_hash=password_hash)
    db.add(user)
    db.commit()
    db.refresh(user)

    token = session_token(user.id)
    _set_cookie(response, token)
    return {"token": token, "user": _public(user)}


@router.post("/login", summary="Entrar com e-mail e senha")
def login(
    payload: Credentials,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    email = (payload.email or "").strip().lower()
    require_within(request, "login", f"{_ip(request)}|{email}", settings.auth_rate_limit_per_min)

    user = db.scalar(select(User).where(User.email == email))
    if not verify_password(user.password_hash if user else None, payload.password):
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")
    if user is not None and not user.is_active:
        raise HTTPException(status_code=403, detail="Conta desativada.")

    assert user is not None
    if user.totp_secret:
        return {
            "two_factor_required": True,
            "challenge": challenge_token(user.id, "2fa", TWOFA_MINUTES),
            "expires_in": TWOFA_MINUTES * 60,
        }

    token = session_token(user.id)
    _set_cookie(response, token)
    return {"token": token, "user": _public(user)}


@router.post("/login/2fa", summary="Concluir login com código TOTP")
def login_two_fa(
    payload: ChallengePayload,
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    # força bruta do código TOTP: limite por IP + desafio (mesma política
    # do login — sem isto, 6 dígitos seriam tentativos sem restrição)
    require_within(
        request, "login-2fa", f"{_ip(request)}|{payload.challenge[:16]}",
        settings.auth_rate_limit_per_min,
    )
    # desafio de uso único: só vale enquanto não foi trocado por uma sessão
    claims = decode_live_claims(db, payload.challenge, "2fa")
    if not claims:
        raise HTTPException(
            status_code=401,
            detail="Desafio expirado ou já usado. Refaça o login.",
        )
    user_id = str(claims.get("sub") or "")
    user = db.get(User, user_id)
    if user is None or not user.totp_secret:
        raise HTTPException(status_code=401, detail="2FA não configurado.")
    if not verify_totp(user.totp_secret, payload.code):
        raise HTTPException(status_code=401, detail="Código incorreto ou expirado.")

    # desafio de uso único: revogado assim que concluído (o mesmo challenge
    # não pode trocar outro código por uma segunda sessão)
    revoke_token(db, payload.challenge, "2fa")

    token = session_token(user.id)
    _set_cookie(response, token)
    return {"token": token, "user": _public(user)}


@router.post("/logout", summary="Sair (limpa a sessão)")
def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
) -> dict:
    """Limpa o cookie **e revoga o token** (jti): o JWT em mãos do
    cliente deixa de valer imediatamente, não só no navegador."""
    from app.api.deps import _session_token

    token = _session_token(request)
    if token:
        revoke_token(db, token, "session")
    # apaga o nome atual e o legado (deploys anteriores ao __Host-)
    for name in cookie_names():
        response.delete_cookie(name, path="/")
    return {"ok": True}


@router.get("/me", summary="Usuário autenticado")
def me(user: User = Depends(current_user)) -> dict:
    info = _public(user)
    # em dev (sem sessão) o backend atende pelo usuário local — sinalizamos
    # para a interface mostrar o aviso de "modo desenvolvimento"
    info["authenticated"] = bool(getattr(user, "_session_authenticated", False))
    return info


@router.post("/2fa/enable", summary="Iniciar a ativação do 2FA (gera QR)")
def enable_two_fa(
    request: Request,
    user: User = Depends(session_user),
) -> dict:
    require_within(request, "2fa", _ip(request), settings.auth_rate_limit_per_min)
    if user.totp_secret:
        raise HTTPException(status_code=400, detail="O 2FA já está ativo.")
    secret = new_totp_secret()
    return {
        "secret": secret,
        "uri": totp_uri(secret, user.email),
        "challenge": challenge_token(f"{user.id}:{secret}", "2fa-setup", 15),
    }


@router.post("/2fa/confirm", summary="Confirmar o 2FA com um código válido")
def confirm_two_fa(
    payload: ChallengePayload,
    db: Session = Depends(get_db),
    user: User = Depends(session_user),
) -> dict:
    claims = decode_live_claims(db, payload.challenge, "2fa-setup")
    subject = str(claims.get("sub")) if claims else None
    if not subject or not subject.startswith(f"{user.id}:"):
        raise HTTPException(status_code=400, detail="Desafio expirado. Comece de novo.")
    secret = subject.split(":", 1)[1]
    if not verify_totp(secret, payload.code):
        raise HTTPException(status_code=400, detail="Código incorreto — confira o app autenticador.")
    revoke_token(db, payload.challenge, "2fa-setup")  # desafio de uso único
    user.totp_secret = secret
    db.commit()
    return {"ok": True, "two_factor_enabled": True}


@router.delete("/2fa", summary="Desligar o 2FA (exige código corrente)")
def disable_two_fa(
    payload: TwoFAPayload,
    db: Session = Depends(get_db),
    user: User = Depends(session_user),
) -> dict:
    if not user.totp_secret:
        raise HTTPException(status_code=400, detail="O 2FA não está ativo.")
    if not verify_totp(user.totp_secret, payload.code):
        raise HTTPException(status_code=400, detail="Código incorreto.")
    user.totp_secret = None
    db.commit()
    return {"ok": True, "two_factor_enabled": False}


def _ip(request: Request) -> str:
    from app.core.rate_limit import client_ip

    return client_ip(request)
