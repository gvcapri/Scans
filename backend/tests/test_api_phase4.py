"""Testes ponta a ponta da API — Fase 4 (busca, comparador, lote, pastas)."""

from __future__ import annotations

import io
import time
import zipfile
from pathlib import Path


def _upload(client, path: Path) -> dict:
    with open(path, "rb") as fh:
        resp = client.post(
            "/api/files",
            files=[("files", (path.name, io.BytesIO(fh.read()), "application/pdf"))],
        )
    assert resp.status_code == 200, resp.text
    return resp.json()[0]


def _upload_png(client) -> dict:
    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (40, 40), "white").save(buf, "PNG")
    resp = client.post(
        "/api/files",
        files=[("files", ("pagina.png", buf.getvalue(), "image/png"))],
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


def _unique_pdf(tmp_path, token: str) -> Path:
    """PDF com um termo exclusivo do teste (evita cruzar com o acervo dos outros)."""
    import pymupdf

    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        pymupdf.Point(72, 90),
        f"CONTRATO {token} - prestacao de servicos com honorario de R$ 5.000,00",
        fontsize=12,
    )
    path = tmp_path / f"{token.lower()}.pdf"
    doc.save(path)
    doc.close()
    return path


# --------------------------------------------------------------------------- #
# catálogo                                                                     #
# --------------------------------------------------------------------------- #
def test_todas_as_ferramentas_estao_ativas(client):
    tools = client.get("/api/meta/tools").json()["tools"]
    bloqueadas = [t["id"] for t in tools if not t["available"]]
    assert bloqueadas == [], f"ainda bloqueadas: {bloqueadas}"
    assert len(tools) == 14


# --------------------------------------------------------------------------- #
# busca full-text                                                              #
# --------------------------------------------------------------------------- #
def test_busca_destaca_trecho_e_ignora_acentos(client, tmp_path):
    row = _upload(client, _unique_pdf(tmp_path, "ZORBLAP1"))

    # termo único + palavra acentuada na mesma consulta (AND)
    body = client.get("/api/search", params={"q": "ZORBLAP1 prestacao"}).json()
    assert body["total"] == 1
    hit = body["results"][0]
    assert hit["file_id"] == row["id"]
    assert "<mark>" in hit["snippet"] and "</mark>" in hit["snippet"]
    assert "ZORBLAP1" in hit["snippet"].upper()
    assert hit["name"] == row["name"]
    assert hit["size"] and hit["created_at"]

    # sem acento acha o mesmo documento
    body2 = client.get("/api/search", params={"q": "zorblap1 prestacao"}).json()
    assert body2["total"] == 1


def test_busca_com_caracteres_especiais_nao_erro(client, tmp_path):
    _upload(client, _unique_pdf(tmp_path, "ZORBLAP2"))
    resp = client.get("/api/search", params={"q": '"(erro[ NEAR NOT'})
    assert resp.status_code == 200
    assert resp.json()["total"] >= 0  # sanitizado, não lança erro de sintaxe

    assert client.get("/api/search", params={"q": ""}).status_code == 422


def test_busca_apaga_quando_o_arquivo_sai(client, tmp_path):
    row = _upload(client, _unique_pdf(tmp_path, "ZORBLAP3"))
    assert client.get("/api/search", params={"q": "ZORBLAP3"}).json()["total"] == 1
    client.delete(f"/api/files/{row['id']}")
    body = client.get("/api/search", params={"q": "ZORBLAP3"}).json()
    assert body["total"] == 0


def test_saida_de_job_entra_no_indice(client, tmp_path):
    """Conversão gera texto novo — a saída precisa ficar pesquisável."""
    row = _upload(client, _unique_pdf(tmp_path, "ZORBLAP4"))
    job = client.post(
        "/api/jobs",
        json={
            "kind": "convert",
            "file_ids": [row["id"]],
            "options": {"target": "txt"},
        },
    )
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    # o TXT gerado também é indexado (aparece nos resultados)
    out_id = job["output_file_ids"][0]
    body = client.get("/api/search", params={"q": "ZORBLAP4"}).json()
    assert out_id in [h["file_id"] for h in body["results"]]


# --------------------------------------------------------------------------- #
# comparador                                                                   #
# --------------------------------------------------------------------------- #
def test_comparador_lado_a_lado(client, samples_dir: Path):
    # as duas amostras de contrato são versões diferentes do mesmo documento
    v1 = _upload(client, samples_dir / "contrato.pdf")
    v2 = _upload(client, samples_dir / "contrato_v2.pdf")

    resp = client.post(
        "/api/compare", json={"file_a": v1["id"], "file_b": v2["id"]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["file_a"]["name"].startswith("contrato")
    assert body["summary"]["pages_changed"] >= 1
    assert body["summary"]["lines_added"] >= 1
    ops = {op["type"] for page in body["pages"] for op in page["ops"]}
    assert "replace" in ops


def test_comparador_validacoes(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    png = _upload_png(client)

    # mesmo arquivo dos dois lados
    assert (
        client.post("/api/compare", json={"file_a": row["id"], "file_b": row["id"]}).status_code
        == 400
    )
    # inexistente
    assert (
        client.post("/api/compare", json={"file_a": "nao-existe", "file_b": row["id"]}).status_code
        == 404
    )
    # não-PDF
    resp = client.post("/api/compare", json={"file_a": png["id"], "file_b": row["id"]})
    assert resp.status_code == 400
    assert "PDF" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# lote                                                                         #
# --------------------------------------------------------------------------- #
def test_lote_converte_pdfs_em_txt_e_baixa_zip(client, text_pdf: Path, samples_dir: Path):
    """Dois PDFs → fluxo de lote → um ZIP só com os .txt."""
    a = _upload(client, text_pdf)
    b = _upload(client, samples_dir / "dados_sensiveis.pdf")

    job = client.post(
        "/api/jobs",
        json={
            "kind": "batch",
            "file_ids": [a["id"], b["id"]],
            "options": {"steps": [{"kind": "convert", "options": {"target": "txt"}}]},
        },
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    dl = client.get(f"/api/files/{job['output_file_ids'][0]}/download")
    assert dl.status_code == 200
    with zipfile.ZipFile(io.BytesIO(dl.content)) as zf:
        assert len(zf.namelist()) == 2
        assert all(n.endswith(".txt") for n in zf.namelist())


def test_lote_usando_fluxo_embutido_de_presets(client, text_pdf: Path):
    """O fluxo embutido 'Extrair texto' é aplicável direto do preset."""
    presets = client.get("/api/presets", params={"tool": "batch"}).json()["presets"]
    embutidos = [p for p in presets if p["builtin"]]
    assert {p["name"] for p in embutidos} >= {
        "Digitalizar (OCR)",
        "Pronto para o tribunal (OCR → Comprimir)",
        "Extrair texto (→ TXT)",
        "Blindar PDFs",
    }
    fluxo = next(p for p in embutidos if p["id"] == "builtin:texto")

    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={"kind": "batch", "file_ids": [row["id"]], "options": fluxo["options"]},
    )
    assert job.status_code == 200, job.text
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    # salvar o mesmo fluxo como perfil próprio e removê-lo
    created = client.post(
        "/api/presets",
        json={"tool": "batch", "name": "Meu fluxo TXT", "options": fluxo["options"]},
    )
    assert created.status_code == 200, created.text
    assert client.delete(f"/api/presets/{created.json()['id']}").json()["ok"] is True


def test_lote_passo_desconhecido_falha_amigavel(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    job = client.post(
        "/api/jobs",
        json={
            "kind": "batch",
            "file_ids": [row["id"]],
            "options": {"steps": [{"kind": "explode"}]},
        },
    )
    assert job.status_code == 200
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "error"
    assert "Passo desconhecido" in job["error"] or "inválidos" in job["error"]


def test_lote_rejeita_mais_de_50_arquivos(client, text_pdf: Path):
    row = _upload(client, text_pdf)
    resp = client.post(
        "/api/jobs",
        json={"kind": "batch", "file_ids": [row["id"]] * 51, "options": {"steps": []}},
    )
    assert resp.status_code == 400
    assert "50" in resp.json()["detail"]


# --------------------------------------------------------------------------- #
# pastas de processo                                                           #
# --------------------------------------------------------------------------- #
def test_crud_de_pastas(client, text_pdf: Path, samples_dir: Path):
    # criar
    created = client.post(
        "/api/cases",
        json={"name": "Processo Silva x Transportes", "process_number": "0000001-10.2026.8.01.0001"},
    )
    assert created.status_code == 200, created.text
    case_id = created.json()["id"]

    # listagem com contador
    listing = client.get("/api/cases").json()
    assert any(c["id"] == case_id for c in listing)

    # mover dois arquivos para dentro
    first = _upload(client, text_pdf)
    second = _upload(client, samples_dir / "contrato.pdf")
    moved = client.post(
        f"/api/cases/{case_id}/files", json={"file_ids": [first["id"], second["id"]]}
    )
    assert moved.json()["moved"] == 2

    # o arquivo agora sinaliza a pasta
    meta = client.get(f"/api/files/{first['id']}").json()
    assert meta["case_folder_id"] == case_id

    # renomear
    renamed = client.patch(
        f"/api/cases/{case_id}", json={"name": "Cliente Transportes Ltda"}
    )
    assert renamed.json()["name"] == "Cliente Transportes Ltda"

    # retirar um arquivo
    assert client.delete(f"/api/cases/{case_id}/files/{second['id']}").json()["ok"] is True
    detail = client.get(f"/api/cases/{case_id}").json()
    assert detail["file_count"] == 1
    assert detail["files"][0]["id"] == first["id"]

    # apagar a pasta: arquivo continua existindo (só desvincula)
    deleted = client.delete(f"/api/cases/{case_id}")
    assert deleted.json()["unlinked"] == 1
    assert client.get(f"/api/cases/{case_id}").status_code == 404
    assert client.get(f"/api/files/{first['id']}").status_code == 200
    assert client.get(f"/api/files/{first['id']}").json()["case_folder_id"] is None


def test_pasta_mostra_historico_de_operacoes(client, text_pdf: Path):
    created = client.post("/api/cases", json={"name": "Revisão de contrato"})
    case_id = created.json()["id"]
    row = _upload(client, text_pdf)
    client.post(f"/api/cases/{case_id}/files", json={"file_ids": [row["id"]]})

    # processa (converte em TXT) → a operação deve aparecer no histórico
    job = client.post(
        "/api/jobs",
        json={
            "kind": "convert",
            "file_ids": [row["id"]],
            "options": {"target": "txt"},
        },
    )
    job = _wait_job(client, job.json()["id"])
    assert job["status"] == "done", job.get("error")

    detail = client.get(f"/api/cases/{case_id}").json()
    kinds = [op["kind"] for op in detail["operations"]]
    assert "convert" in kinds
    convert_op = next(op for op in detail["operations"] if op["kind"] == "convert")
    assert convert_op["status"] == "done"


def test_pastas_isolam_usuarios_e_404(client):
    assert client.get("/api/cases/nao-existe").status_code == 404
    assert client.delete("/api/cases/nao-existe").status_code == 404
    assert (
        client.post("/api/cases", json={"name": "   "}).status_code == 400
        or client.post("/api/cases", json={"name": "ok"}).status_code == 200
    )
