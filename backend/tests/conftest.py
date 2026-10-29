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
os.environ.setdefault("ENVIRONMENT", "dev")  # prod é o padrão do código (falha fechada)
os.environ.setdefault("STORAGE_ROOT", str(_TEST_ROOT / "storage"))
os.environ.setdefault("STORAGE_SECRET", "segredo-de-teste-somente-0123456789")
os.environ.setdefault("TASK_BACKEND", "local")
os.environ.setdefault("AUTH_RATE_LIMIT_PER_MIN", "1000000000")  # testes batem muito no login
os.environ.setdefault("RATE_LIMIT_PER_MIN", "1000000000")  # testes batem muito nas APIs
os.environ.setdefault("TESSDATA_PREFIX", str(Path(__file__).resolve().parents[2] / "tessdata"))

import pytest  # noqa: E402
from PIL import Image, ImageDraw, ImageFont  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[2]


def _init_db() -> None:
    """Cria as tabelas antes de rodar os testes.

    O SQLite em `:memory:` (o padrão de `TestClient` sem caminho) mantém
    o banco vivo só na conexão que criou: cada `get_db()` abre uma nova
    conexão e não enxerga o `users` já inserido em outra. Para o teste,
    a conexão fica no arquivo temporário, então `init_tables()` - que
    roda na mesma conexão - e os demais ficam na mesma base.
    """
    from app.db import init_tables

    _ensure_file(_TEST_ROOT / 'test.db')
    init_tables()


def _ensure_file(path: Path) -> None:
    """Cria o arquivo vazio quando o SQLite exige que ele exista."""
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()


def _register(client, email: str = "dev@lexscan.local", password: str = "senha-forte-123") -> dict:
    """Registra uma conta e devolve o JSON de resposta."""
    resp = client.post(
        "/api/auth/register",
        json={"email": email, "password": password},
    )
    if resp.status_code == 409:
        # A conta já existe dentre os testes — apenas logamos.
        resp = client.post(
            "/api/auth/login",
            json={"email": email, "password": password},
        )
        assert resp.status_code == 200, resp.text
    else:
        assert resp.status_code == 200, resp.text
    return resp.json()


def _login(client, email: str = "dev@lexscan.local", password: str = "senha-forte-123") -> dict:
    """Entrar com e-mail e senha e devolver o JSON."""
    resp = client.post(
        "/api/auth/login",
        json={"email": email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


@pytest.fixture()
def client():
    """Cliente HTTP de teste.

    Garante:
      * banco inicializado (tables + índice) antes de usar o TestClient;
      * um usuário registrado e logado, sempre que o cliente for criado.
    Cada teste recebe um `client` limpo (scope="function"), então o estado de
    sessão não vaza entre eles.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    # Banco: o lifespan de `create_app()` não roda no TestClient (o objeto
    # `app` já está instanciado), então a inicialização das tabelas é feita
    # aqui, antes do `with TestClient(app) as ...
    _init_db()

    with TestClient(app) as test_client:
        _register(test_client)
        yield test_client


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
    """Cliente HTTP de teste.

    Cada teste recebe um `client` com sessão pronta (registro + login), e o
    banco é inicializado uma vez por sessão de teste.
    """
    from fastapi.testclient import TestClient

    from app.main import app

    # Banco: o lifespan de `create_app()` não roda no TestClient (o objeto
    # `app` já está instanciado), então a inicialização das tabelas é feita
    # aqui, antes do `with TestClient(app) as ...
    _init_db()

    with TestClient(app) as test_client:
        _register(test_client)
        yield test_client
