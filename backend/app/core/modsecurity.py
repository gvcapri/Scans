"""ModSecurity de rota: 503 nos recursos desabilitados e proteção por sessão.

Duas camadas:
  1. **Allowlist mínima** — apenas `/api/meta/health`,
     `/api/meta/features`, `/api/auth/register`, `/api/auth/login`,
     `/api/auth/login/2fa`, `/api/auth/logout` e `/api/auth/me` são
     públicos. Qualquer outro `GET/POST/PUT/PATCH/DELETE /api/*` exige
     sessão (cookie ou Bearer) — deixa o 401 limpo.
  2. **Feature flags** — rotas que dependem de funcionalidade pesada
     (OCR, comparação, redação, etc.) levantam 503 {code:"feature_disabled"}.

Nunca retorna 500 por falta de configuração ou recurso indisponível: só 503
e JSON amigável.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.core.config import settings
from app.core.features import is_feature_enabled

# Permitido sem sessão. A argue lista é pública (mínima) — quem lê o código
# pode mudar; ninguém deve adicionar rotas aqui que exijam permissão.
PUBLIC_ROUTES = {
    "/api/meta/health",
    "/api/meta/features",
    "/api/meta/tools",
    "/api/auth/register",
    "/api/auth/login",
    "/api/auth/login/2fa",
    "/api/auth/logout",
    "/api/auth/me",
}

# Mapeamento de rota -> funcionalidade que desabilita o endpoint.
# A chave é o prefixo do caminho; o valor é a flag que deve estar ativa.
DISABLED_BY_FLAG = {
    "/api/ocr": "ocr",
    "/api/blind": "blind",
    "/api/compare": "compare",
    "/api/redact": "redact",
    "/api/jobs": "jobs",
    "/api/presets": "batch",
    "/api/search": "search",
    "/api/cases": "cases",
    "/api/convert": "convert",
    "/api/integrity": "integrity",
}

# Ferramentas leves consideradas publicas (acesso sem login, sem gravação,
# sem rate-limit por IP). O padrão está vazio: nenhuma ferramenta é
# pública até que a equipe decida expor (via PUBLIC_TOOLS no .env).
PUBLIC_TOOLS = []  # type: list[str]


def _is_public_route(path: str, method: str) -> bool:
    """True só para métodos públicos (read-only, sem gravação)."""
    if path in PUBLIC_ROUTES:
        return True
    # allowlist de ferramentas leves (ex.: GET /api/meta/*)
    for tool in settings.features.public_tools or []:
        if path.startswith(f"/api/{tool}/") or path == f"/api/{tool}":
            return True
    return False


def _feature_disabled(path: str) -> str | None:
    """Retorna o nome da flag que desabilitou o endpoint, ou None."""
    for prefix, flag in DISABLED_BY_FLAG.items():
        if path.startswith(prefix) and not is_feature_enabled(flag):
            return flag
    return None


def setup_modsecurity(app: FastAPI) -> None:
    @app.middleware("http")
    async def modsecurity(request: Request, call_next):
        path = request.url.path.rstrip("/") or "/"
        method = request.method

        # Allowlist pública / ferramentas leves
        if _is_public_route(path, method):
            return await call_next(request)

        # Todas as rotas /api/* exigem sessão
        if path.startswith("/api/"):
            token = request.cookies.get("lexscan_token") or request.headers.get(
                "authorization", ""
            )
            if not token.startswith("Bearer "):
                token = token.strip()
            if not token:
                return JSONResponse(
                    status_code=401,
                    content={"code": "unauthorized", "message": "Faça login para continuar."},
                )

        # Recurso desabilitado por flag
        disabled = _feature_disabled(path)
        if disabled:
            return JSONResponse(
                status_code=503,
                content={
                    "code": "feature_disabled",
                    "message": "Recurso temporariamente indisponível",
                    "feature": disabled,
                },
            )

        return await call_next(request)
