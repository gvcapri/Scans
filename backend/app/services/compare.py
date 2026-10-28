"""Comparador de versões lado a lado (Fase 4).

Compara duas versões de um documento PDF por **texto** (não por pixel):
cada página vira uma lista de linhas e o `difflib.SequenceMatcher`
devolve as operações (igual / removido / adicionado / substituído) que a
interface desenha em duas colunas — o mesmo modelo de "diff" de qualquer
ferramenta de versão, aplicado a petições e contratos.

Limites pensados para resposta síncrona rápida: 200 páginas e 400 linhas
por página por documento.
"""

from __future__ import annotations

import difflib
import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

log = logging.getLogger("lexscan.compare")

MAX_PAGES = 200
MAX_LINES = 400


@dataclass
class CompareOptions:
    """Opções do comparador."""

    max_lines: int = MAX_LINES

    @classmethod
    def from_dict(cls, data: dict | None) -> "CompareOptions":
        data = data or {}
        opts = cls()
        try:
            opts.max_lines = min(2000, max(50, int(data.get("max_lines", MAX_LINES))))
        except (TypeError, ValueError):
            opts.max_lines = MAX_LINES
        return opts


@dataclass
class CompareResult:
    """Diff estruturado, pronto para a interface lado a lado."""

    pages: list[dict] = field(default_factory=list)
    summary: dict = field(default_factory=dict)
    pages_a: int = 0
    pages_b: int = 0


def _page_lines(page: pymupdf.Page, max_lines: int) -> list[str]:
    text = page.get_text() or ""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    return lines[:max_lines]


def _extract(path: Path, max_lines: int) -> list[list[str]]:
    with pymupdf.open(path) as doc:
        return [_page_lines(page, max_lines) for page in doc][:MAX_PAGES]


def _diff_page(a: list[str], b: list[str]) -> list[dict]:
    matcher = difflib.SequenceMatcher(None, a, b, autojunk=False)
    ops: list[dict] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "equal":
            ops.append({"type": "equal", "a": a[i1:i2], "b": b[j1:j2]})
        elif tag == "delete":
            ops.append({"type": "delete", "a": a[i1:i2], "b": []})
        elif tag == "insert":
            ops.append({"type": "insert", "a": [], "b": b[j1:j2]})
        else:  # replace
            ops.append({"type": "replace", "a": a[i1:i2], "b": b[j1:j2]})
    return ops


def compare_documents(
    path_a: Path,
    path_b: Path,
    opts: CompareOptions | None = None,
    progress=None,
) -> CompareResult:
    """Compara os dois PDFs e devolve o diff página a página."""
    opts = opts or CompareOptions()
    for path in (path_a, path_b):
        if path.suffix.lower() != ".pdf":
            raise ValueError(
                f"O comparador aceita apenas PDF (recebido: {path.suffix or 'sem extensão'})."
            )

    pages_a = _extract(path_a, opts.max_lines)
    pages_b = _extract(path_b, opts.max_lines)
    if not pages_a and not pages_b:
        raise ValueError("Nenhum dos arquivos tem texto para comparar.")

    total = max(len(pages_a), len(pages_b))
    out: list[dict] = []
    changed_pages = 0
    added = 0
    removed = 0

    for index in range(total):
        if progress:
            progress(index, total, f"Comparando página {index + 1} de {total}...")
        a = pages_a[index] if index < len(pages_a) else []
        b = pages_b[index] if index < len(pages_b) else []
        ops = _diff_page(a, b)
        page_changed = any(op["type"] != "equal" for op in ops)
        if page_changed:
            changed_pages += 1
        added += sum(len(op["b"]) for op in ops if op["type"] in ("insert", "replace"))
        removed += sum(len(op["a"]) for op in ops if op["type"] in ("delete", "replace"))
        if page_changed or index < 2:  # páginas iguais no início também entram
            out.append({"index": index + 1, "changed": page_changed, "ops": ops})

    return CompareResult(
        pages=out,
        summary={
            "pages_compared": total,
            "pages_changed": changed_pages,
            "lines_added": added,
            "lines_removed": removed,
            "only_a": max(0, len(pages_a) - len(pages_b)),
            "only_b": max(0, len(pages_b) - len(pages_a)),
        },
        pages_a=len(pages_a),
        pages_b=len(pages_b),
    )
