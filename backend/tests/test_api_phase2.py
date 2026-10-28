"""Testes ponta a ponta da API — ferramentas da Fase 2."""

from __future__ import annotations

import io
import time
from pathlib import Path

from app.core.config import settings


def _upload(client, path: Path) -> dict:
    with open(path, "rb") as fh:
        resp = client.post(
            "/api/files",
            files=[("files", (path.name, io.BytesIO(fh.read()), "application/pdf"))],
        )
    assert resp.status_code == 200, resp.text
    return resp.json()[0]


def _wait_job(client, job_id: str, timeout: float = 240.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = client.get(f"/api/jobs/{job_id}").json()
        if job["status"] in ("done", "error"):
            return job
        time.sleep(0.5)
    raise AssertionError("job não terminou a tempo")


def test_ferramentas_da_fase_2_estao_disponiveis(client):
    tools = {t["id"]: t for t in client.get("/api/meta/tools").json()["tools"]}
    for tool_id in ("merge", "split", "convert", "compress"):
        assert tools[tool_id]["available"] is True, tool_id
    # com a Fase 4 concluída, nenhum card do catálogo fica bloqueado
    assert all(t["available"] for t in tools.values())


def test_fluxo_merge_completo(client, text_pdf: Path, scanned_pdf: Path):
    first = _upload(client, text_pdf)
    second = _upload(client, scanned_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "merge",
            "file_ids": [second["id"], first["id"]],  # ordem invertida de propósito
            "options": {},
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    assert len(job["output_file_ids"]) == 1
    dl = client.get(f"/api/files/{job['output_file_ids'][0]}/download")
    assert dl.status_code == 200

    import pymupdf
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(dl.content)
        tmp_path = Path(tmp.name)
    doc = pymupdf.open(tmp_path)
    try:
        assert doc.page_count == 2
        assert doc[0].get_images(), "primeiro arquivo enviado vem primeiro"
        assert "CONTRATO" in doc[1].get_text()
    finally:
        doc.close()
        tmp_path.unlink(missing_ok=True)


def test_merge_exige_dois_arquivos(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    resp = client.post(
        "/api/jobs", json={"kind": "merge", "file_ids": [row["id"]]}
    )
    assert resp.status_code == 400
    assert "arquivos" in resp.json()["detail"]


def test_fluxo_split_completo(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "split",
            "file_ids": [row["id"]],
            "options": {"mode": "extract", "ranges": "1"},
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")
    assert len(job["output_file_ids"]) == 1
    assert client.get(
        f"/api/files/{job['output_file_ids'][0]}/download"
    ).status_code == 200


def test_split_rejeita_intervalo_invalido(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "split",
            "file_ids": [row["id"]],
            "options": {"mode": "ranges", "ranges": "99-100"},
        },
    )
    assert job.status_code == 200
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "error"
    assert "fora do documento" in job["error"]


def test_fluxo_convert_pdf_para_txt(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "convert",
            "file_ids": [row["id"]],
            "options": {"target": "txt"},
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")
    dl = client.get(f"/api/files/{job['output_file_ids'][0]}/download")
    assert dl.status_code == 200
    assert "CONTRATO" in dl.content.decode("utf-8")


def test_job_rejeita_arquivo_incompativel(client, text_pdf: Path):
    """Imagem não pode entrar em 'merge' (só PDF) — validação por extensão."""
    import io as _io

    from PIL import Image

    buf = _io.BytesIO()
    Image.new("RGB", (32, 32), "white").save(buf, "PNG")
    uploaded = client.post(
        "/api/files",
        files=[("files", ("pagina.png", buf.getvalue(), "image/png"))],
    )
    assert uploaded.status_code == 200, uploaded.text
    image_row = uploaded.json()[0]
    pdf_row = _upload(client, text_pdf)

    resp = client.post(
        "/api/jobs",
        json={"kind": "merge", "file_ids": [pdf_row["id"], image_row["id"]]},
    )
    assert resp.status_code == 400
    assert "não é compatível" in resp.json()["detail"]


def test_fluxo_compress_com_limite(client, text_pdf: Path):
    if settings.resolve_ghostscript() is None:
        import pytest

        pytest.skip("Ghostscript não instalado")

    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "compress",
            "file_ids": [row["id"]],
            "options": {"limit_mb": 0, "quality": "ebook", "pdfa": False},
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")
    assert job["output_file_ids"]
    dl = client.get(f"/api/files/{job['output_file_ids'][0]}/download")
    assert dl.status_code == 200
    assert dl.content[:5] == b"%PDF-"


def test_presets_embutidos_e_crud(client):
    listing = client.get("/api/presets", params={"tool": "compress"}).json()
    presets = listing["presets"]
    builtins = [p for p in presets if p["builtin"]]
    assert {p["name"] for p in builtins} >= {"PJe", "e-SAJ", "e-Proc", "Projudi"}
    assert all("limit_mb" in p["options"] for p in builtins)

    # salvar perfil editado
    created = client.post(
        "/api/presets",
        json={
            "tool": "compress",
            "name": "Tribunal Local",
            "options": {"limit_mb": 7.5, "quality": "printer", "pdfa": True},
        },
    )
    assert created.status_code == 200, created.text
    preset_id = created.json()["id"]

    # aparece na listagem
    presets = client.get("/api/presets", params={"tool": "compress"}).json()["presets"]
    mine = [p for p in presets if p["id"] == preset_id]
    assert mine and mine[0]["options"]["limit_mb"] == 7.5

    # nome duplicado é recusado
    duplicate = client.post(
        "/api/presets",
        json={"tool": "compress", "name": "tribunal local", "options": {}},
    )
    assert duplicate.status_code == 409

    # apagar perfil embutido é recusado; o próprio é apagado
    assert client.delete("/api/presets/builtin:pje").status_code == 400
    assert client.delete(f"/api/presets/{preset_id}").json()["ok"] is True
    assert client.delete(f"/api/presets/{preset_id}").status_code == 404
