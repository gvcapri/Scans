"""Testes ponta a ponta da API — ferramentas da Fase 3."""

from __future__ import annotations

import io
import time
from pathlib import Path

import pymupdf


def _upload(client, path: Path) -> dict:
    with open(path, "rb") as fh:
        resp = client.post(
            "/api/files",
            files=[("files", (path.name, io.BytesIO(fh.read()), "application/pdf"))],
        )
    assert resp.status_code == 200, resp.text
    return resp.json()[0]


def _upload_bytes(client, name: str, data: bytes) -> dict:
    resp = client.post(
        "/api/files",
        files=[("files", (name, io.BytesIO(data), "application/pdf"))],
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


def _sensitive_pdf_bytes() -> bytes:
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    lines = [
        "RECLAMACAO TRABALHISTA",
        "CPF: 529.982.247-25",
        "E-mail: cliente@escritorio.adv.br",
        "Telefone: (11) 98765-4321",
    ]
    y = 72
    for line in lines:
        page.insert_text(pymupdf.Point(72, y), line, fontsize=12)
        y += 28
    data = doc.tobytes()
    doc.close()
    return data


def _open_pdf(content: bytes) -> tuple[pymupdf.Document, Path]:
    import tempfile

    with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        path = Path(tmp.name)
    return pymupdf.open(path), path


def _close(doc: pymupdf.Document, path: Path) -> None:
    doc.close()
    path.unlink(missing_ok=True)


def test_ferramentas_da_fase_3_estao_disponiveis(client):
    tools = {t["id"]: t for t in client.get("/api/meta/tools").json()["tools"]}
    for tool_id in ("redact", "number", "outline", "metadata", "integrity"):
        assert tools[tool_id]["available"] is True, tool_id
    assert tools["search"]["available"] is False, "fase seguinte continua bloqueada"


def test_scan_lista_dados_sensiveis_para_revisao(client):
    row = _upload_bytes(client, "reclamacao.pdf", _sensitive_pdf_bytes())
    resp = client.post("/api/redact/scan", json={"file_id": row["id"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["has_text_layer"] is True
    assert body["warning"] is None
    types = {g["type"] for g in body["groups"]}
    assert {"cpf", "email", "phone"} <= types
    cpf = next(g for g in body["groups"] if g["type"] == "cpf")
    assert cpf["value"] == "529.982.247-25"
    assert cpf["pages"] == [1]


def test_scan_avisa_quando_nao_tem_texto(client, scanned_pdf: Path):
    row = _upload(client, scanned_pdf)
    body = client.post("/api/redact/scan", json={"file_id": row["id"]}).json()
    assert body["has_text_layer"] is False
    assert body["warning"]


def test_scan_rejeita_arquivo_inexistente(client):
    resp = client.post("/api/redact/scan", json={"file_id": "nao-existe"})
    assert resp.status_code == 404


def test_fluxo_redact_completo(client):
    row = _upload_bytes(client, "reclamacao.pdf", _sensitive_pdf_bytes())

    # revisão → usuário aprova só o CPF e o e-mail
    groups = client.post("/api/redact/scan", json={"file_id": row["id"]}).json()[
        "groups"
    ]
    approved = [
        g["value"]
        for g in groups
        if g["type"] in {"cpf", "email"}
    ]
    assert len(approved) == 2

    job = client.post(
        "/api/jobs",
        json={
            "kind": "redact",
            "file_ids": [row["id"]],
            "options": {"terms": approved, "mode": "black"},
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    dl = client.get(f"/api/files/{job['output_file_ids'][0]}/download")
    assert dl.status_code == 200
    doc, path = _open_pdf(dl.content)
    try:
        text = "".join(page.get_text() for page in doc)
        assert "529.982.247-25" not in text
        assert "cliente@escritorio.adv.br" not in text
        assert "(11) 98765-4321" in text  # não aprovado na revisão → intacto
        assert not doc[0].search_for("529.982.247-25")
    finally:
        _close(doc, path)


def test_redact_sem_dados_localizados_falha_com_mensagem(client):
    """PDF com texto mas sem nenhum dado: job termina com erro amigável."""
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text(pymupdf.Point(72, 72), "Apenas texto comum, sem dados.", fontsize=12)
    data = doc.tobytes()
    doc.close()
    row = _upload_bytes(client, "simples.pdf", data)

    job = client.post(
        "/api/jobs",
        json={"kind": "redact", "file_ids": [row["id"]], "options": {"terms": ["999.999.999-99"]}},
    )
    assert job.status_code == 200
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "error"
    assert "não foram localizados" in job["error"]


def test_fluxo_number_completo(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "number",
            "file_ids": [row["id"]],
            "options": {
                "style": "bates",
                "prefix": "PROC",
                "start": 1,
                "pad": 4,
                "position": "bottom-center",
                "watermark": "USO JUDICIAL",
            },
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    dl = client.get(f"/api/files/{job['output_file_ids'][0]}/download")
    doc, path = _open_pdf(dl.content)
    try:
        text = "".join(page.get_text() for page in doc)
        assert "PROC0001" in text
        assert "USO JUDICIAL" in text
    finally:
        _close(doc, path)


def test_fluxo_outline_completo(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "outline",
            "file_ids": [row["id"]],
            "options": {
                "title": "ÍNDICE",
                "insert_index": True,
                "bookmarks": True,
                "entries": [{"label": "ANEXO I — Contrato", "page": 1}],
            },
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    dl = client.get(f"/api/files/{job['output_file_ids'][0]}/download")
    doc, path = _open_pdf(dl.content)
    try:
        assert doc.page_count == 2
        toc = doc.get_toc()
        assert toc[0][1] == "ÍNDICE"
        assert toc[1] == [2, "ANEXO I — Contrato", 2]
        assert "ANEXO I — Contrato" in doc[0].get_text()
    finally:
        _close(doc, path)


def test_fluxo_metadata_completo(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "metadata",
            "file_ids": [row["id"]],
            "options": {
                "cnj": "0000001-10.2026.8.01.0001",
                "tipo": "Contestação",
                "autor": "Maria Souza",
                "reu": "Transportes SA",
                "data": "2026-10-28",
            },
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    out_id = job["output_file_ids"][0]
    meta = client.get(f"/api/files/{out_id}").json()
    assert meta["name"].startswith("Contestação - 0000001-10.2026.8.01.0001")

    dl = client.get(f"/api/files/{out_id}/download")
    doc, path = _open_pdf(dl.content)
    try:
        assert "Contestação" in doc.metadata["title"]
        assert "0000001-10.2026.8.01.0001" in doc.metadata["keywords"]
        assert doc.metadata["author"] == "Maria Souza x Transportes SA"
    finally:
        _close(doc, path)


def test_metadata_rejeita_cnj_invalido(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={"kind": "metadata", "file_ids": [row["id"]], "options": {"cnj": "123"}},
    )
    assert job.status_code == 200
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "error"
    assert "CNJ" in job["error"]


def test_fluxo_integrity_completo(client, text_pdf: Path, scanned_pdf: Path):
    from app.services.hashing import sha256_file

    first = _upload(client, text_pdf)
    second = _upload(client, scanned_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "integrity",
            "file_ids": [first["id"], second["id"]],
            "options": {"emitente": "Escritório Silva", "observacao": "Fase 3"},
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    dl = client.get(f"/api/files/{job['output_file_ids'][0]}/download")
    assert dl.status_code == 200
    doc, path = _open_pdf(dl.content)
    try:
        text = "".join(page.get_text() for page in doc).replace("\n", "")
        assert sha256_file(text_pdf) in text
        assert sha256_file(scanned_pdf) in text
        assert "ICP-Brasil" in text
        assert doc.metadata["title"] == "Certificado de Integridade"
    finally:
        _close(doc, path)


def test_integrity_aceita_varios_arquivos_mas_limita_a_20(client, text_pdf: Path):
    rows = [_upload(client, text_pdf) for _ in range(3)]
    resp = client.post(
        "/api/jobs",
        json={"kind": "integrity", "file_ids": [r["id"] for r in rows]},
    )
    assert resp.status_code == 200
    job = _wait_job(client, resp.json()["id"])
    assert job["status"] == "done", job.get("error")

    # 21 arquivos → recusado na criação (limite da ferramenta)
    many = [_upload(client, text_pdf) for _ in range(21)]
    resp = client.post(
        "/api/jobs",
        json={"kind": "integrity", "file_ids": [r["id"] for r in many]},
    )
    assert resp.status_code == 400
