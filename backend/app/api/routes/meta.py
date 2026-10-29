"""Rotas de metadados do serviço (sem conteúdo de documento)."""

from __future__ import annotations

import pytesseract

from fastapi import APIRouter

from app.core.config import settings
from app.core.features import is_feature_enabled

router = APIRouter(prefix="/meta", tags=["metadados"])


@router.get("/features", summary="Funcionalidades ativas (flags de produção)")
def read_features() -> dict:
    """Lista o que está disponível nesta instância.

    O valor vem de variáveis de ambiente; basta mudar o .env e reiniciar.
    """
    return {
        "ocr": settings.features.ocr,
        "blind": settings.features.blind,
        "compare": settings.features.compare,
        "redact": settings.features.redact,
        "numbering": settings.features.numbering,
        "outline": settings.features.outline,
        "integrity": settings.features.integrity,
        "convert": settings.features.convert,
        "batch": settings.features.batch,
        "search": settings.features.search,
        "cases": settings.features.cases,
        "jobs": settings.features.jobs,
        "registration_open": settings.features.registration_open,
        "public_tools": settings.features.public_tools,
    }


@router.get("/languages", summary="Idiomas disponíveis no Tesseract")
def read_languages() -> dict:
    """Lista os idiomas OCR suportados neste ambiente."""
    try:
        installed = [
            l.strip()
            for l in pytesseract.get_languages(config="")
            if l.strip()
        ]
    except Exception:
        installed = []
    configured = [l.strip() for l in (settings.tesseract_langs or "por+eng").split("+") if l.strip()]
    return {"languages": installed or configured, "installed": installed, "configured": configured}


@router.get("/tools", summary="Catálogo de ferramentas disponíveis")
def read_tools() -> dict:
    """Lista todas as ferramentas (Fases 2-4) com disponibilidade por instância.

    A disponibilidade respeita o _fail_close_ de `ENVIRONMENT=prod`: nessa
    configuração, somente as ferramentas leves (baseadas em PyMuPDF, sem
    subida de processo, sem dependências externas) ficam ativas por padrão.
    Tudo o que consome OCR, Ghostscript, LibreOffice, Celery ou um processo
    externo é **recomendada** e exige a flag correspondente ou um
    `ENVIRONMENT=dev` ativo.
    """
    tools = [
        # Fase 2 — conversão e manipulação básica
        {
            "id": "convert",
            "name": "Converter",
            "description": "Imagem/PDF → PDF, Word → PDF, PDF → PNG/TXT/DOCX.",
            "category": "conversao",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["convert", "imagem", "documento"],
        },
        {
            "id": "split",
            "name": "Dividir/Extrair",
            "description": "Extrair páginas, por intervalos ou por metadado de um PDF.",
            "category": "conversao",
            "available": True,
            "recommended": False,
            "requires": ["ghostscript"],
            "tags": ["pdf", "split", "extrair"],
        },
        {
            "id": "merge",
            "name": "Mesclar PDFs",
            "description": "Juntar vários PDFs na ordem escolhida, com sumário.",
            "category": "conversao",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["pdf", "merge", "mesclar"],
        },
        {
            "id": "compress",
            "name": "Comprimir PDF",
            "description": "Reduz o tamanho do PDF (Qualidade, PDF/A, divisão).",
            "category": "conversao",
            "available": True,
            "recommended": False,
            "requires": ["ghostscript"],
            "tags": ["pdf", "compressão", "tamanho"],
        },
        # Fase 3 — documento jurídico
        {
            "id": "redact",
            "name": "Redigir PDF",
            "description": "Tarja irreversível de dados sensíveis (CPF, CNPJ, cartões, e-mail...).",
            "category": "documento",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["redact", "segurança", "LGPD", "pdf"],
        },
        {
            "id": "number",
            "name": "Numerar páginas",
            "description": "Insere numeração automática (centro, canto, formato).",
            "category": "documento",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["numeracao", "pdf", "documento"],
        },
        {
            "id": "numbering",
            "name": "Numeração automática",
            "description": "Aplica numeração automática (centro, canto, formato).",
            "category": "documento",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["numeracao", "pdf", "documento"],
        },
        {
            "id": "outline",
            "name": "Sumário (bookmarks)",
            "description": "Gera ou reescreve o sumário do PDF a partir de uma tabela.",
            "category": "documento",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["outline", "bookmark", "sumario", "pdf"],
        },
        {
            "id": "metadata",
            "name": "Metadados",
            "description": "Ler/escrever título, autor, assunto, palavras-chave do PDF.",
            "category": "documento",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["metadata", "metadados", "pdf"],
        },
        # Fase 4 — pesquisa e acervo
        {
            "id": "search",
            "name": "Busca full-text",
            "description": "Procura no texto extraído de todos os PDFs do usuário.",
            "category": "pesquisa",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["busca", "fulltext", "texto"],
        },
        {
            "id": "compare",
            "name": "Comparação lado a lado",
            "description": "Diff de duas versões do mesmo documento por texto.",
            "category": "pesquisa",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["compare", "diff", "versao"],
        },
        {
            "id": "batch",
            "name": "Lote",
            "description": "Aplica uma sequência de passos (PCA, OCR, compressão...) a vários PDFs.",
            "category": "lote",
            "available": True,
            "recommended": False,
            "requires": ["ghostscript"],
            "tags": ["lote", "batch", "sequencia"],
        },
        # Fase 5 — segurança e privacidade
        {
            "id": "blind",
            "name": "PDF Blindado",
            "description": "Achata o PDF em imagem (nada de edição, metadados zerados).",
            "category": "privacidade",
            "available": True,
            "recommended": False,
            "requires": ["tesseract"],
            "tags": ["blind", "privacidade", "segurança", "pdf"],
        },
        {
            "id": "integrity",
            "name": "Certificado de integridade",
            "description": "Gera SHA-256 e lê/escreve metadados de assinatura de documento.",
            "category": "privacidade",
            "available": True,
            "recommended": False,
            "requires": [],
            "tags": ["integridade", "sha256", "certificado"],
        },
    ]
    # Disponibilidade real por flag — a mesma que o modsecurity usa para
    # devolver 503 (fail-closed em prod). Sem flag correspondente: sempre
    # disponível (ferramenta leve, baseada em PyMuPDF).
    tool_flags = {
        "convert": "convert",
        "redact": "redact",
        "search": "search",
        "compare": "compare",
        "batch": "batch",
        "blind": "blind",
        "integrity": "integrity",
    }
    tool_phases = {
        "convert": 2, "split": 2, "merge": 2, "compress": 2,
        "redact": 3, "number": 3, "numbering": 3, "outline": 3, "metadata": 3,
        "search": 4, "compare": 4, "batch": 4,
        "blind": 5, "integrity": 5,
    }
    for tool in tools:
        flag = tool_flags.get(tool["id"])
        tool["available"] = flag is None or is_feature_enabled(flag)
        tool["phase"] = tool_phases.get(tool["id"], 1)
    return {"tools": tools}


@router.get("/health", summary="Saúde do serviço")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name}
