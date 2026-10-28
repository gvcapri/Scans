"""Rotas auxiliares: saúde, idiomas de OCR e catálogo de ferramentas."""

from __future__ import annotations

from fastapi import APIRouter

from app.core.config import settings
from app.services.ocr import configure_tesseract, languages

router = APIRouter(prefix="/meta", tags=["meta"])

# Catálogo usado pela interface. `available` diz o que já está implementado
# — as fases seguintes apenas alternam a flag.
TOOLS = [
    {
        "id": "ocr",
        "name": "OCR",
        "description": "PDF escaneado ou imagem → PDF pesquisável, TXT ou DOCX.",
        "phase": 1,
        "available": True,
        "route": "/ocr",
    },
    {
        "id": "blind",
        "name": "PDF Blindado",
        "description": "Achata o PDF em imagem de alta resolução: acaba com edição.",
        "phase": 1,
        "available": True,
        "route": "/blind",
    },
    {
        "id": "merge",
        "name": "Mesclar",
        "description": "Une vários arquivos em um único PDF, com reordenação.",
        "phase": 2,
        "available": True,
        "route": "/merge",
    },
    {
        "id": "split",
        "name": "Dividir",
        "description": "Separa por intervalo de páginas ou extrai páginas específicas.",
        "phase": 2,
        "available": True,
        "route": "/split",
    },
    {
        "id": "convert",
        "name": "Converter",
        "description": "Imagem↔PDF, Word→PDF, PDF→PNG/JPG, PDF→TXT/DOCX.",
        "phase": 2,
        "available": True,
        "route": "/convert",
    },
    {
        "id": "compress",
        "name": "Compressor",
        "description": "Reduz para o limite do tribunal (PJe, e-SAJ, e-Proc).",
        "phase": 2,
        "available": True,
        "route": "/compress",
    },
    {
        "id": "redact",
        "name": "Tarjar / Redigir",
        "description": "Remove CPF, CNPJ, RG, telefone e dados bancários.",
        "phase": 3,
        "available": True,
        "route": "/redact",
    },
    {
        "id": "metadata",
        "name": "Dados da peça",
        "description": "Grava CNJ, partes e tipo no PDF e renomeia o arquivo.",
        "phase": 3,
        "available": True,
        "route": "/metadata",
    },
    {
        "id": "number",
        "name": "Numerar / Bates",
        "description": "Numeração, carimbo Fls., anexo e marca d'água.",
        "phase": 3,
        "available": True,
        "route": "/number",
    },
    {
        "id": "outline",
        "name": "Sumário e índice",
        "description": "Bookmarks e página de índice para petições com anexos.",
        "phase": 3,
        "available": True,
        "route": "/outline",
    },
    {
        "id": "integrity",
        "name": "Certificado de integridade",
        "description": "Hash SHA-256 + relatório PDF das operações.",
        "phase": 3,
        "available": True,
        "route": "/integrity",
    },
    {
        "id": "search",
        "name": "Pesquisa em acervo",
        "description": "Busca textual em todos os documentos, com destaque.",
        "phase": 4,
        "available": True,
        "route": "/search",
    },
    {
        "id": "compare",
        "name": "Comparador",
        "description": "Diferenças entre duas versões lado a lado.",
        "phase": 4,
        "available": True,
        "route": "/compare",
    },
    {
        "id": "batch",
        "name": "Processamento em lote",
        "description": "Pasta/ZIP + fluxo reutilizável, download em ZIP.",
        "phase": 4,
        "available": True,
        "route": "/batch",
    },
]


@router.get("/health", summary="Saúde da API")
def health() -> dict:
    return {"status": "ok", "app": settings.app_name, "version": "1.0.0"}


@router.get("/languages", summary="Idiomas de OCR disponíveis")
def ocr_languages() -> dict:
    try:
        configure_tesseract()
    except Exception:
        pass
    langs = languages()
    return {
        "languages": sorted(langs),
        "default": "por+eng" if {"por", "eng"} <= set(langs) else (langs[0] if langs else "eng"),
    }


@router.get("/tools", summary="Catálogo de ferramentas")
def tools() -> dict:
    return {"tools": TOOLS}
