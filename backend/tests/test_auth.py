"""Testes da Fase 5: autenticação, 2FA, limitação e isolamento por usuário."""

from __future__ import annotations

import io
from pathlib import Path

import pytest


def _register(client, email: str, password: str = "senha-forte-123") -> dict:
    resp = client.post(
        "/api/auth/register", json={"email": email, "password": password}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


# --------------------------------------------------------------------------- #
# registro / login / sessão                                                    #
# --------------------------------------------------------------------------- #
def test_registro_login_e_me(client):
    body = _register(client, "oab@exemplo.adv.br")
    assert body["user"]["email"] == "oab@exemplo.adv.br"
    assert "token" in body

    client.post("/api/auth/logout")
    resp = client.post(
        "/api/auth/login",
        json={"email": "oab@exemplo.adv.br", "password": "senha-forte-123"},
    )
    assert resp.status_code == 200
    me = client.get("/api/auth/me").json()
    assert me["email"] == "oab@exemplo.adv.br"
    assert me["authenticated"] is True


def test_login_senha_errada_e_registro_duplicado(client):
    _register(client, "duplicado@exemplo.adv.br")
    client.post("/api/auth/logout")

    wrong = client.post(
        "/api/auth/login",
        json={"email": "duplicado@exemplo.adv.br", "password": "senha-errada-99"},
    )
    assert wrong.status_code == 401

    again = client.post(
        "/api/auth/register",
        json={"email": "Duplicado@exemplo.adv.br", "password": "senha-forte-123"},
    )
    assert again.status_code == 409


def test_validacao_de_email_e_senha(client):
    resp = client.post(
        "/api/auth/register", json={"email": "sem-arroba", "password": "senha-forte-123"}
    )
    assert resp.status_code == 400

    resp = client.post(
        "/api/auth/register", json={"email": "curta@exemplo.adv.br", "password": "123"}
    )
    assert resp.status_code == 400
    assert "8" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# 2FA (TOTP)                                                                   #
# --------------------------------------------------------------------------- #
def test_ciclo_completo_do_2fa(client):
    import pyotp

    _register(client, "dupla@exemplo.adv.br")
    client.post("/api/auth/logout")

    enable = client.post("/api/auth/2fa/enable")
    assert enable.status_code == 401, "configurar 2FA exige sessão real"

    client.post(
        "/api/auth/login",
        json={"email": "dupla@exemplo.adv.br", "password": "senha-forte-123"},
    )
    enable = client.post("/api/auth/2fa/enable").json()
    secret = enable["secret"]
    assert enable["uri"].startswith("otpauth://totp/")

    # código errado não confirma
    bad = client.post(
        "/api/auth/2fa/confirm", json={"challenge": enable["challenge"], "code": "000000"}
    )
    assert bad.status_code == 400

    ok = client.post(
        "/api/auth/2fa/confirm",
        json={"challenge": enable["challenge"], "code": pyotp.TOTP(secret).now()},
    )
    assert ok.status_code == 200 and ok.json()["two_factor_enabled"] is True

    # a partir de agora o login pede o segundo fator
    client.post("/api/auth/logout")
    step1 = client.post(
        "/api/auth/login",
        json={"email": "dupla@exemplo.adv.br", "password": "senha-forte-123"},
    ).json()
    assert step1["two_factor_required"] is True
    assert "token" not in step1

    # código errado é recusado
    fail = client.post(
        "/api/auth/login/2fa",
        json={"challenge": step1["challenge"], "code": "111111"},
    )
    assert fail.status_code == 401

    step2 = client.post(
        "/api/auth/login/2fa",
        json={"challenge": step1["challenge"], "code": pyotp.TOTP(secret).now()},
    )
    assert step2.status_code == 200
    assert client.get("/api/auth/me").json()["authenticated"] is True

    # desligar o 2FA exige código corrente
    disable = client.request(
        "DELETE",
        "/api/auth/2fa",
        json={"code": pyotp.TOTP(secret).now()},
    )
    assert disable.status_code == 200
    assert client.get("/api/auth/me").json()["two_factor_enabled"] is False


# --------------------------------------------------------------------------- #
# limitação de tentativas                                                      #
# --------------------------------------------------------------------------- #
def test_rate_limit_no_login(client, monkeypatch):
    from app.core import rate_limit
    from app.core.config import settings

    rate_limit.reset()
    monkeypatch.setattr(settings, "auth_rate_limit_per_min", 3)
    try:
        email = "forca-bruta@exemplo.adv.br"
        _register(client, email)
        client.post("/api/auth/logout")
        codes = [
            client.post(
                "/api/auth/login", json={"email": email, "password": "senha-errada-00"}
            ).status_code
            for _ in range(5)
        ]
        assert codes[-1] == 429, f"códigos: {codes}"
        assert 401 in codes
    finally:
        monkeypatch.setattr(settings, "auth_rate_limit_per_min", 100000)
        rate_limit.reset()


# --------------------------------------------------------------------------- #
# isolamento por usuário (LGPD)                                               #
# --------------------------------------------------------------------------- #
def test_producao_exige_sessao(client, monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "environment", "prod")
    client.cookies.clear()
    resp = client.get("/api/files")
    assert resp.status_code == 401
    assert client.get("/api/meta/health").status_code == 200  # saúde é pública


def test_usuario_nao_ve_arquivo_do_outro(client, text_pdf: Path):
    # dono do arquivo
    dono = _register(client, "dono@exemplo.adv.br")
    dono_token = dono["token"]
    with open(text_pdf, "rb") as fh:
        up = client.post(
            "/api/files",
            files=[("files", ("contrato.pdf", io.BytesIO(fh.read()), "application/pdf"))],
        )
    file_id = up.json()[0]["id"]
    assert client.get(f"/api/files/{file_id}").status_code == 200

    # outro usuário, sessão própria
    intruso = _register(client, "intruso@exemplo.adv.br")
    intruso_token = intruso["token"]
    client.cookies.clear()  # só o Authorization do intruso vale

    resp = client.get(
        f"/api/files/{file_id}", headers={"Authorization": f"Bearer {intruso_token}"}
    )
    assert resp.status_code == 404, "arquivo de outro usuário é invisível"

    resp = client.get(
        "/api/files", headers={"Authorization": f"Bearer {intruso_token}"}
    )
    assert all(f["id"] != file_id for f in resp.json())

    resp = client.get(
        f"/api/files/{file_id}/download",
        headers={"Authorization": f"Bearer {intruso_token}"},
    )
    assert resp.status_code == 404

    # e o dono continua vendo (Bearer explícito)
    resp = client.get(
        f"/api/files/{file_id}", headers={"Authorization": f"Bearer {dono_token}"}
    )
    assert resp.status_code == 200


def test_token_expirado_e_forjado_sao_rejeitados():
    from app.core.config import settings
    from app.core.security import create_token, decode_token

    # expirado (emitido com validade negativa)
    expired = create_token("usuario", "session", minutes=-5)
    assert decode_token(expired, "session") is None

    # assinado com outra chave (forjado)
    original = settings.secret_key
    try:
        settings.secret_key = "outra-chave-bem-diferente-0123456789"
        forged = create_token("usuario", "session")
    finally:
        settings.secret_key = original
    assert decode_token(forged, "session") is None

    # finalidade trocada: um desafio 2FA não serve de sessão
    challenge = create_token("usuario", "2fa", minutes=5)
    assert decode_token(challenge, "session") is None
