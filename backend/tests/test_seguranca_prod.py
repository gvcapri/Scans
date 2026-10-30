"""Segurança da postura de produção (deploy de VM pequena).

Cobre as garantias novas da fase de deploy:

* **401** — a allowlist mínima do modsecurity: rota protegida sem sessão
  responde 401 com ``code=unauthorized``; rotas públicas continuam abertas;
* **503** — feature flag desligada responde ``code=feature_disabled`` antes
  de chegar na rota, e o catálogo ``/api/meta/tools`` reflete a flag;
* **init_search no Postgres** — regressão: todos os passos (tabela **e**
  índice GIN) precisam rodar, não só o primeiro;
* **isolamento de busca** — um usuário não encontra o acervo do outro.
"""

from __future__ import annotations

import io
from pathlib import Path


# --------------------------------------------------------------------------- #
# fail-closed: sem ENVIRONMENT=dev explícito, sem usuário local               #
# --------------------------------------------------------------------------- #
def test_sem_dev_explicito_nao_ha_fallback_para_usuario_local(monkeypatch):
    """`ENVIRONMENT` atípico ("staging", "Prod ") não pode desligar a
    exigência de sessão — antes a condição era `!= "prod"` (fail-open)."""
    from app.api.deps import _dev_fallback_ok
    from app.core.config import settings

    original = settings.environment
    try:
        for value in ("staging", "production", "Prod ", "homolog"):
            settings.environment = value
            assert _dev_fallback_ok() is False, value
        settings.environment = "dev"
        assert _dev_fallback_ok() is True
    finally:
        settings.environment = original


def test_docs_e_openapi_desligados_em_prod():
    """Em prod não existe /docs, /redoc nem /openapi.json (mapa de rotas
    público); em dev continuam disponíveis."""
    from app.core.config import settings
    from app.main import create_app

    original = settings.environment
    try:
        settings.environment = "prod"
        prod_app = create_app()
        assert prod_app.docs_url is None
        assert prod_app.redoc_url is None
        assert prod_app.openapi_url is None

        settings.environment = "dev"
        dev_app = create_app()
        assert dev_app.docs_url == "/docs"
        assert dev_app.openapi_url == "/openapi.json"
    finally:
        settings.environment = original


def test_rate_limit_varre_buckets_vencidos(monkeypatch):
    """Contadores com janela inteiramente vencida são descartados (memória
    limitada mesmo com IPs rotativos) e a varredura automática está ligada."""
    import time as _time
    from collections import deque

    from app.core import rate_limit

    rate_limit.reset()
    now = _time.monotonic()
    rate_limit._hits["velho"] = deque([now - 999])
    rate_limit._hits["vazio"] = deque()
    rate_limit._hits["fresco"] = deque([now])

    rate_limit._sweep(now)
    assert "velho" not in rate_limit._hits, "bucket vencido deve sumir"
    assert "vazio" not in rate_limit._hits, "bucket sem atividade deve sumir"
    assert "fresco" in rate_limit._hits, "atividade recente é preservada"

    # a varredura dispara de fato dentro de `allow` a cada _SWEEP_EVERY
    swept: list[float] = []
    monkeypatch.setattr(rate_limit, "_sweep", swept.append)
    rate_limit.reset()
    rate_limit._sweeps = 0
    for i in range(rate_limit._SWEEP_EVERY + 1):
        assert rate_limit.allow(f"ip-{i}", 5) is True
    assert len(swept) == 1, "sweep automático deve rodar uma vez"

    # e o limite da janela continua valendo
    rate_limit.reset()
    for _ in range(3):
        assert rate_limit.allow("ip-fixo", 3) is True
    assert rate_limit.allow("ip-fixo", 3) is False, "limite respeitado"
    rate_limit.reset()


# --------------------------------------------------------------------------- #
# 401 — allowlist mínima                                                       #
# --------------------------------------------------------------------------- #
def test_rota_protegida_sem_sessao_devolve_401(client):
    client.cookies.clear()
    resp = client.get("/api/files")
    assert resp.status_code == 401
    assert resp.json()["code"] == "unauthorized"


def test_rotas_publicas_continuam_abertas(client):
    client.cookies.clear()
    for path in ("/api/meta/health", "/api/meta/features", "/api/meta/tools"):
        assert client.get(path).status_code == 200, path


def test_public_tools_so_aceita_leitura(client, monkeypatch):
    """PUBLIC_TOOLS é allowlist de leitura: um POST não "fica público"
    só por bater com o prefixo da ferramenta."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "public_tools", "compare")
    client.cookies.clear()

    # GET pode passar da allowlist pública (chega na rota; 401/422/etc.
    # dependem da rota, o que importa aqui é NÃO ser 401 de middleware)
    get = client.get("/api/compare")
    assert get.status_code != 401 or get.json().get("code") != "unauthorized"

    # POST é recusado pelo middleware com o mesmo 401 de "sem sessão"
    post = client.post("/api/compare", json={})
    assert post.status_code == 401
    assert post.json()["code"] == "unauthorized"


# --------------------------------------------------------------------------- #
# 503 — feature flags                                                          #
# --------------------------------------------------------------------------- #
def test_flag_desligada_devolve_503_feature_disabled(client):
    from app.core.config import settings

    original = settings.feature_compare
    try:
        settings.feature_compare = False
        # o middleware responde antes do roteamento — corpo irrelevante
        resp = client.post("/api/compare", json={})
        assert resp.status_code == 503
        body = resp.json()
        assert body["code"] == "feature_disabled"
        assert body["feature"] == "compare"
    finally:
        settings.feature_compare = original

    # com a flag de volta, a rota deixa de ser bloqueada pelo middleware
    # (pode acabar em 422/401 de validação, mas nunca mais em 503 de flag)
    again = client.post("/api/compare", json={})
    assert again.status_code != 503 or again.json().get("code") != "feature_disabled"


def test_catalogo_de_ferramentas_reflete_a_flag(client):
    from app.core.config import settings

    original = settings.feature_batch
    try:
        settings.feature_batch = False
        tools = {t["id"]: t for t in client.get("/api/meta/tools").json()["tools"]}
        assert tools["batch"]["available"] is False
        # ferramenta leve (sem flag) continua de pé mesmo com a pesada fora
        assert tools["merge"]["available"] is True
        assert "phase" in tools["batch"]
    finally:
        settings.feature_batch = original


# --------------------------------------------------------------------------- #
# init_search no Postgres — regressão do índice GIN                           #
# --------------------------------------------------------------------------- #
def test_init_search_postgres_executa_todos_os_passos(monkeypatch):
    """Regressão: os passos do dialeto precisam rodar INTEIROS.

    Antes da correção, `init_search` executava só ``steps[:1]`` — a tabela
    era criada e o índice GIN jamais aparecia (a busca só funcionava por
    seq scan). Aqui garantimos que a lista completa chega ao executor.
    """
    from app.db import search as search_mod

    calls: list[list[tuple[str, str]]] = []

    def _fake_run_steps(engine, steps) -> bool:
        calls.append(list(steps))
        return True

    class _FakeDialect:
        name = "postgresql"

    class _FakeEngine:
        dialect = _FakeDialect()

    monkeypatch.setattr(search_mod, "_run_steps", _fake_run_steps)
    monkeypatch.setattr(search_mod, "_mode", "fts5")  # e restaura ao final

    assert search_mod.init_search(_FakeEngine()) is True

    assert len(calls) == 1, "o dialeto nativo deve tentar os passos uma vez"
    steps = calls[0]
    assert len(steps) == 2, "tabela + índice GIN são dois passos"
    ddl = " ".join(sql for _, sql in steps)
    assert "CREATE TABLE IF NOT EXISTS files_fts" in ddl
    assert "USING GIN" in ddl, "o índice GIN precisa estar entre os passos"
    assert search_mod._mode == "postgres"


# --------------------------------------------------------------------------- #
# isolamento de busca por usuário (LGPD)                                      #
# --------------------------------------------------------------------------- #
def test_busca_isolada_por_usuario(client, text_pdf: Path):
    # dono: registra, envia um PDF com texto e busca nele
    dono = client.post(
        "/api/auth/register",
        json={"email": "dono-busca@exemplo.adv.br", "password": "senha-forte-123"},
    ).json()
    with open(text_pdf, "rb") as fh:
        up = client.post(
            "/api/files",
            files=[("files", ("contrato.pdf", io.BytesIO(fh.read()), "application/pdf"))],
        )
    assert up.status_code == 200, up.text

    achou = client.get(
        "/api/search",
        params={"q": "PRESTACAO"},
        headers={"Authorization": f"Bearer {dono['token']}"},
    )
    assert achou.status_code == 200
    assert achou.json()["total"] >= 1, "o dono encontra o próprio documento"

    # intruso: mesma consulta não devolve o acervo do dono
    intruso = client.post(
        "/api/auth/register",
        json={"email": "intruso-busca@exemplo.adv.br", "password": "senha-forte-123"},
    ).json()
    client.cookies.clear()
    espiao = client.get(
        "/api/search",
        params={"q": "PRESTACAO"},
        headers={"Authorization": f"Bearer {intruso['token']}"},
    )
    assert espiao.status_code == 200
    assert espiao.json()["total"] == 0
    assert espiao.json()["results"] == []
