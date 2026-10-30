"""Autenticação do LexScan (Fase 5): argon2, JWT e 2FA TOTP.

* **Senhas** — Argon2id (argon2-cffi), com verificação amigável e
  rehash automático quando os parâmetros mudarem.
* **Sessão** — JWT HS256 (payload `sub` + `purpose`) entregue por cookie
  httpOnly *e* no corpo do login (bearer), para scripts/testes.
* **2FA** — TOTP RFC 6238 (pyotp). O segredo só é gravado no usuário
  depois da confirmação com um código válido; até lá ele viaja num token
  de desafio assinado (15 min), sem tocar no banco.

Nada aqui guarda conteúdo de documento — só credenciais.
"""

from __future__ import annotations

import re
import time
import uuid

import jwt
import pyotp
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from app.core.config import settings

ALGORITHM = "HS256"
SESSION_HOURS = 12
CHALLENGE_MINUTES = 15
TWOFA_MINUTES = 5
COOKIE_NAME = "lexscan_token"


def cookie_name() -> str:
    """Nome do cookie de sessão.

    Em prod usa o prefixo `__Host-` (exige Secure, Path=/ e sem Domain):
    um subdomínio hostileiro não consegue sobrescrever/injetar o cookie da
    sessão — blindagem contra cookie-tossing. Fora de prod (http) o prefixo
    não é aceito pelo navegador, então mantém o nome simples.
    """
    if settings.environment.lower() == "prod":
        return "__Host-" + COOKIE_NAME
    return COOKIE_NAME


def cookie_names() -> tuple[str, ...]:
    """Nomes a ler/apagar: o atual + o legado (sessões anteriores ao deploy)."""
    current = cookie_name()
    return (current, COOKIE_NAME) if current != COOKIE_NAME else (COOKIE_NAME,)

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]{2,}$")

_hasher = PasswordHasher()
# hash de referência para igualar o tempo de resposta quando o e-mail não existe
_DUMMY_HASH = _hasher.hash("senha-de-referencia-para-timing")


# --------------------------------------------------------------------------- #
# senhas                                                                       #
# --------------------------------------------------------------------------- #
def valid_email(email: str) -> bool:
    return bool(EMAIL_RE.match(email or ""))


def valid_password(password: str) -> bool:
    return 8 <= len(password or "") <= 128


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(hashed: str | None, password: str) -> bool:
    """Verifica com segurança; hash ausente/inválido só devolve False."""
    if not hashed:
        try:
            _hasher.verify(_DUMMY_HASH, password)  # mantém o tempo de resposta
        except (VerifyMismatchError, VerificationError, InvalidHashError):
            pass  # esperado: o hash de referência nunca confere
        return False
    try:
        return _hasher.verify(hashed, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(hashed: str) -> bool:
    try:
        return _hasher.check_needs_rehash(hashed)
    except (InvalidHashError, VerificationError):
        return False


# --------------------------------------------------------------------------- #
# tokens (sessão, desafio 2FA e desafio de configuração do 2FA)                #
# --------------------------------------------------------------------------- #
def create_token(subject: str, purpose: str, minutes: int | None = None) -> str:
    now = int(time.time())
    lifetime = (minutes or SESSION_HOURS * 60) * 60
    payload = {
        "sub": subject,
        "purpose": purpose,
        # id único do token: é o que permite revogar (logout / desafio usado)
        "jti": uuid.uuid4().hex,
        "iat": now,
        "exp": now + lifetime,
    }
    return jwt.encode(payload, settings.secret_key, algorithm=ALGORITHM)


def decode_claims(token: str, purpose: str) -> dict | None:
    """Valida assinatura/expiração/finalidade e devolve o payload completo.

    É daqui que `jti` e `exp` saem para a revogação; o resto do código
    continua usando `decode_token` (só o subject).
    """
    try:
        data = jwt.decode(token, settings.secret_key, algorithms=[ALGORITHM])
    except jwt.InvalidTokenError:
        return None
    if data.get("purpose") != purpose:
        return None
    return data


def decode_token(token: str, purpose: str) -> str | None:
    """Decodifica e valida finalidade; devolve o subject ou None."""
    data = decode_claims(token, purpose)
    if data is None:
        return None
    return str(data.get("sub") or "") or None


def session_token(user_id: str) -> str:
    return create_token(user_id, "session")


def challenge_token(subject: str, purpose: str, minutes: int) -> str:
    return create_token(subject, purpose, minutes=minutes)


# --------------------------------------------------------------------------- #
# 2FA (TOTP)                                                                   #
# --------------------------------------------------------------------------- #
def new_totp_secret() -> str:
    return pyotp.random_base32()


def totp_uri(secret: str, email: str) -> str:
    return pyotp.TOTP(secret).provisioning_uri(name=email, issuer_name="JudiFiles")


def verify_totp(secret: str, code: str) -> bool:
    """Confere o código TOTP (janela de ±1 período para relógio fora de passo)."""
    digits = re.sub(r"\D", "", code or "")
    if len(digits) != 6:
        return False
    try:
        return bool(pyotp.TOTP(secret).verify(digits, valid_window=1))
    except Exception:
        return False
