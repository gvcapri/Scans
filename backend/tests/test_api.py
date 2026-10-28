"""Testes ponta a ponta da API (Fase 1): upload → job → download."""

from __future__ import annotations

import hashlib
import io
import time
from pathlib import Path


def _upload(client, path: Path) -> dict:
    with open(path, "rb") as fh:
        resp = client.post(
            "/api/files",
            files=[("files", (path.name, io.BytesIO(fh.read()), "application/pdf"))],
        )
    assert resp.status_code == 200, resp.text
    return resp.json()[0]


def _wait_job(client, job_id: str, timeout: float = 180.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.5)
    raise AssertionError("job não terminou a tempo")


def test_health_e_idiomas(client):
    assert client.get("/api/meta/health").json()["status"] == "ok"
    langs = client.get("/api/meta/languages").json()["languages"]
    assert "por" in langs and "eng" in langs


def test_upload_listagem_download_e_exclusao(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    assert row["name"] == "contrato.pdf"
    assert len(row["sha256"]) == 64

    # listagem
    listed = client.get("/api/files").json()
    assert any(f["id"] == row["id"] for f in listed)

    # preview renderiza PNG
    preview = client.get(f"/api/files/{row['id']}/preview", params={"page": 0})
    assert preview.status_code == 200
    assert preview.headers["content-type"] == "image/png"
    assert preview.content.startswith(b"\x89PNG")

    # download devolve os bytes originais
    dl = client.get(f"/api/files/{row['id']}/download")
    assert dl.status_code == 200
    assert hashlib.sha256(dl.content).hexdigest() == row["sha256"]
    assert dl.content.startswith(b"%PDF")

    # apagar agora (LGPD)
    assert client.delete(f"/api/files/{row['id']}").json()["ok"] is True
    assert client.get(f"/api/files/{row['id']}").status_code == 404
    assert client.get(f"/api/files/{row['id']}/download").status_code == 404


def test_fluxo_ocr_completo(client, scanned_pdf: Path):
    row = _upload(client, scanned_pdf)
    job = client.post(
        "/api/jobs",
        json={"kind": "ocr", "file_ids": [row["id"]], "options": {"output": "pdf", "dpi": 200}},
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")
    assert job["progress"] == 100
    assert job["output_file_ids"]

    out_id = job["output_file_ids"][0]
    meta = client.get(f"/api/files/{out_id}").json()
    assert "_ocr" in meta["name"], "saída deve herdar o nome do arquivo de entrada"
    dl = client.get(f"/api/files/{out_id}/download")
    assert dl.status_code == 200
    assert dl.content[:5] == b"%PDF-"

    # o PDF gerado tem texto pesquisável
    import pymupdf
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(dl.content)
        tmp_path = Path(tmp.name)
    doc = pymupdf.open(tmp_path)
    try:
        assert len(doc[0].get_text().strip()) > 0
    finally:
        doc.close()
        tmp_path.unlink(missing_ok=True)


def test_fluxo_blindado_completo(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "blind",
            "file_ids": [row["id"]],
            "options": {"dpi": 150, "jpeg_quality": 60},
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    out_id = job["output_file_ids"][0]
    dl = client.get(f"/api/files/{out_id}/download")
    assert dl.status_code == 200

    import pikepdf

    with pikepdf.open(io.BytesIO(dl.content)) as pdf:
        assert "/Metadata" not in pdf.Root
        page_text = ""
    assert dl.content[:5] == b"%PDF-"


def test_job_rejeita_kind_desconhecido(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    resp = client.post(
        "/api/jobs", json={"kind": "explode", "file_ids": [row["id"]]}
    )
    assert resp.status_code == 400


def test_upload_rejeita_tipo_invalido(client):
    resp = client.post(
        "/api/files",
        files=[("files", ("notas.exe", io.BytesIO(b"MZ\x90\x03"), "application/octet-stream"))],
    )
    assert resp.status_code == 415
