"""Limitação de requisições (Fase 5): janela deslizante por chave.

Proteção contra força bruta no login/registro, por IP (registro) e por
IP + e-mail (login). Em memória — suficiente para a instância única do
LexScan; em escala horizontal a troca é pontual (Redis) sem mudar quem
chama `require_within`.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse

from app.core.config import settings

_WINDOW = 60.0  # janela de 1 minuto
_lock = threading.Lock()
_hits: dict[str, deque[float]] = defaultdict(deque)


def client_ip(request: Request) -> str:
    """IP do cliente (respeita X-Forwarded-For quando há proxy)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "desconhecido"


def allow(key: str, limit_per_min: int) -> bool:
    """Registra uma tentativa; False quando estourou o limite da janela."""
    if limit_per_min <= 0:
        return True
    now = time.monotonic()
    with _lock:
        bucket = _hits[key]
        while bucket and now - bucket[0] > _WINDOW:
            bucket.popleft()
        if len(bucket) >= limit_per_min:
            return False
        bucket.append(now)
        return True


def require_within(request: Request, scope: str, key: str, limit_per_min: int) -> None:
    """Levanta 429 quando o limite é excedido. `scope` só separa os contadores."""
    if allow(f"{scope}:{key}", limit_per_min):
        return
    raise HTTPException(
        status_code=429,
        detail="Muitas tentativas. Aguarde um minuto e tente novamente.",
    )


def reset() -> None:
    """Zera contadores (usado pelos testes)."""
    with _lock:
        _hits.clear()


def setup_rate_limit(app: FastAPI) -> None:
    """Roda o rate limiter em todo o app (apenas rotas /api/*)."""
    @app.middleware("http")
    async def _rate_limit(request: Request, call_next):
        if request.url.path.startswith("/api/"):
            key = client_ip(request)
            # contadores compartilhados com o limiter de autenticação:
            # o mesmo limite por minuto serve para todas as rotas de API.
            if not allow(key, settings.rate_limit_per_min):
                return JSONResponse(
                    status_code=429,
                    content={
                        "code": "too_many_requests",
                        "message": "Muitas requisições. Aguarde um minuto e tente novamente.",
                    },
                )
        return await call_next(request)

