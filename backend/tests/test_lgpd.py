"""Testes da Fase 5: expurgo LGPD (retenção) e antivírus opcional (ClamAV)."""

from __future__ import annotations

import datetime as dt
import io
import socket
import threading
import time
from pathlib import Path

SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _upload(client, name: str = "contrato.pdf") -> dict:
    data = (SAMPLES / "contrato.pdf").read_bytes()
    resp = client.post(
        "/api/files",
        files=[("files", (name, io.BytesIO(data), "application/pdf"))],
    )
    assert resp.status_code == 200, resp.text
    return resp.json()[0]


def _age_file(file_id: str, hours: int) -> None:
    """Envelhece um registro no banco (simula passagem da retenção)."""
    from app.db.models import StoredFile
    from app.db.session import session_scope

    with session_scope() as db:
        row = db.get(StoredFile, file_id)
        assert row is not None
        row.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)


def _wait_job(client, job_id: str, timeout: float = 240.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.5)
    raise AssertionError(f"job {job_id} não terminou em {timeout}s")


# ---------------------------------------------------------------- expurgo ----


def test_expurgo_apaga_arquivo_que_passou_da_retenção(client):
    from app.services.retention import purge_expired

    f = _upload(client, "antigo.pdf")
    _age_file(f["id"], hours=48)

    result = purge_expired(retention_hours=24)
    assert result["files"] >= 1

    # Some do banco, do download e da listagem.
    assert client.get(f"/api/files/{f['id']}").status_code == 404
    assert client.get(f"/api/files/{f['id']}/download").status_code == 404
    ids = {item["id"] for item in client.get("/api/files").json()}
    assert f["id"] not in ids


def test_expurgo_poupa_arquivo_recente(client):
    from app.services.retention import purge_expired

    f = _upload(client, "recente.pdf")
    result = purge_expired(retention_hours=24)

    assert client.get(f"/api/files/{f['id']}").status_code == 200
    assert result["files"] == 0


def test_expurgo_apaga_jobs_antigos(client, text_pdf: Path):
    from app.db.models import Job
    from app.db.session import session_scope
    from app.services.retention import purge_expired

    # Job concluído de verdade via API.
    up = client.post(
        "/api/files",
        files=[("files", ("contrato.pdf", text_pdf.read_bytes(), "application/pdf"))],
    )
    file_id = up.json()[0]["id"]
    job = client.post(
        "/api/jobs",
        json={
            "kind": "convert",
            "file_ids": [file_id],
            "options": {"target": "txt"},
        },
    )
    assert job.status_code == 200, job.text
    job_id = job.json()["id"]
    done = _wait_job(client, job_id)
    assert done["status"] == "done", done.get("error")

    # Envelhece o job e roda o expurgo.
    with session_scope() as db:
        row = db.get(Job, job_id)
        row.created_at = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=48)

    result = purge_expired(retention_hours=24)
    assert result["jobs"] >= 1
    assert client.get(f"/api/jobs/{job_id}").status_code == 404


# --------------------------------------------------------------- antivírus ----


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _fake_clamd(port: int, response: bytes) -> threading.Thread:
    """Servidor TCP mínimo que fala o protocolo INSTREAM do ClamAV."""
    server = socket.socket()
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind(("127.0.0.1", port))
    server.listen(1)

    def run() -> None:
        try:
            conn, _ = server.accept()
            data = b""
            while not data.endswith(b"\x00\x00\x00\x00"):
                part = conn.recv(65536)
                if not part:
                    break
                data += part
            conn.sendall(response)
            conn.close()
        except OSError:
            pass
        finally:
            server.close()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    return t


def _enable_clamav(monkeypatch, port: int) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "clamav_enabled", True)
    monkeypatch.setattr(settings, "clamav_host", "127.0.0.1")
    monkeypatch.setattr(settings, "clamav_port", port)


def test_upload_passa_quando_clamd_diz_ok(client, monkeypatch):
    port = _free_port()
    _fake_clamd(port, b"OK\x00")
    _enable_clamav(monkeypatch, port)

    f = _upload(client, "limpo.pdf")
    assert f["sha256"]
    assert client.get(f"/api/files/{f['id']}").status_code == 200


def test_upload_bloqueado_quando_clamd_encontra_virus(client, monkeypatch):
    port = _free_port()
    _fake_clamd(port, b"stream: Eicar-Test-Signature FOUND\x00")
    _enable_clamav(monkeypatch, port)

    before = {item["id"] for item in client.get("/api/files").json()}
    resp = client.post(
        "/api/files",
        files=[
            (
                "files",
                (
                    "infectado.pdf",
                    io.BytesIO((SAMPLES / "contrato.pdf").read_bytes()),
                    "application/pdf",
                ),
            )
        ],
    )
    assert resp.status_code == 415
    assert "antivírus" in resp.json()["detail"].lower()

    # Nada novo ficou registrado.
    after = {item["id"] for item in client.get("/api/files").json()}
    assert after == before


def test_upload_retorna_503_quando_clamd_offline(client, monkeypatch):
    _enable_clamav(monkeypatch, _free_port())  # porta sem servidor

    resp = client.post(
        "/api/files",
        files=[
            (
                "files",
                (
                    "ok.pdf",
                    io.BytesIO((SAMPLES / "contrato.pdf").read_bytes()),
                    "application/pdf",
                ),
            )
        ],
    )
    assert resp.status_code == 503


def test_upload_sem_clamav_nao_toca_na_rede(client, monkeypatch):
    """CLAMAV_ENABLED=false (padrão): nenhuma conexão é tentada."""
    from app.core.config import settings

    monkeypatch.setattr(settings, "clamav_enabled", False)

    f = _upload(client, "sem_scanner.pdf")
    assert f["sha256"]
