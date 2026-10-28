"""Fixtures compartilhadas dos testes.

O ambiente é configurado ANTES de importar qualquer módulo da aplicação
(banco e storage em diretórios temporários, Tesseract do projeto).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

# --- ambiente de teste (precisa vir antes dos imports da app) ---------------
_TEST_ROOT = Path(tempfile.mkdtemp(prefix="lexscan-tests-"))
os.environ.setdefault("DATABASE_URL", f"sqlite:///{_TEST_ROOT / 'test.db'}")
os.environ.setdefault("STORAGE_ROOT", str(_TEST_ROOT / "storage"))
os.environ.setdefault("STORAGE_SECRET", "segredo-de-teste-somente-0123456789")
os.environ.setdefault("TASK_BACKEND", "local")
os.environ.setdefault("AUTH_RATE_LIMIT_PER_MIN", "100000")  # testes batem muito no login
os.environ.setdefault("TESSDATA_PREFIX", str(Path(__file__).resolve().parents[2] / "tessdata"))

import pytest  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(scope="session")
def scanned_pdf(tmp_path_factory) -> Path:
    """PDF 'escaneado' de verdade: texto virado imagem em 300 DPI."""
    work = tmp_path_factory.mktemp("scanned")
    lines = [
        "PETICAO INICIAL",
        "Numero do processo CNJ 0000001-10.2026.8.01.0001",
        "Advogado: OAB 123456",
        "Email: contato@escritorio.adv.br",
    ]
    w, h = 2480, 3508  # A4 a 300 DPI
    img = Image.new("RGB", (w, h), "white")
    draw = ImageDraw.Draw(img)
    try:
        font = ImageFont.truetype("arial.ttf", 72)
    except Exception:
        font = ImageFont.load_default()
    y = 300
    for line in lines:
        draw.text((200, y), line, fill="black", font=font)
        y += 160
    # pequena rotação + ruído: exercita deskew/denoise
    img = img.rotate(2.0, fillcolor="white", resample=Image.BICUBIC)

    out = work / "peticao_escaneada.pdf"
    img.save(out, "PDF", resolution=300)
    return out


@pytest.fixture(scope="session")
def text_pdf(tmp_path_factory) -> Path:
    """PDF nasceu-digital (com camada de texto)."""
    import pymupdf

    work = tmp_path_factory.mktemp("digital")
    doc = pymupdf.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text(
        pymupdf.Point(72, 120),
        "CONTRATO DE PRESTACAO DE SERVICOS - versao 1",
        fontsize=16,
    )
    page.insert_text(pymupdf.Point(72, 160), "Clausula 1 - objeto do contrato", fontsize=14)
    out = work / "contrato.pdf"
    doc.save(out)
    doc.close()
    return out


@pytest.fixture(scope="session")
def samples_dir() -> Path:
    """Amostras versionadas em ./samples (PDFs de exemplo)."""
    return REPO_ROOT / "samples"


@pytest.fixture()
def client():
    """Cliente HTTP de teste (dispara o lifespan: banco + tabelas)."""
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as test_client:
        yield test_client
