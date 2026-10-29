"""Sumário/índice com nomeação de anexos e bookmarks (Fase 3).

Entrada: uma lista de anexos (`label` + página no documento original).
O serviço pode:

* inserir páginas de índice no início do documento (com "pontilhado" até o
  número da página, já deslocado pelo tamanho do índice);
* criar/renumerar os bookmarks (sumário navegável do PDF);
* derivar os anexos dos bookmarks existentes quando a lista vier vazia.

Feito para petições com anexos ("ANEXO I — ...") em que o número de folhas
precisa bater com o índice protocolado.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

log = logging.getLogger("lexscan.outline")

MAX_ENTRIES = 300
ENTRIES_PER_PAGE = 34


@dataclass
class OutlineEntry:
    """Um anexo do índice."""

    label: str
    page: int  # 1-based, no documento ORIGINAL


@dataclass
class OutlineOptions:
    """Opções do sumário/índice."""

    title: str = "ÍNDICE"
    entries: list[dict] = field(default_factory=list)
    insert_index: bool = True   # cria páginas de índice no início
    bookmarks: bool = True      # cria sumário navegável (bookmarks)

    @classmethod
    def from_dict(cls, data: dict | None) -> "OutlineOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        opts.title = str(opts.title or "ÍNDICE").strip()[:80] or "ÍNDICE"
        opts.insert_index = bool(opts.insert_index)
        opts.bookmarks = bool(opts.bookmarks)

        entries: list[dict] = []
        for raw in (opts.entries or [])[:MAX_ENTRIES]:
            if not isinstance(raw, dict):
                continue
            label = str(raw.get("label") or "").strip()[:120]
            try:
                page = int(raw.get("page") or 0)
            except (TypeError, ValueError):
                continue
            if label and page > 0:
                entries.append({"label": label, "page": page})
        opts.entries = entries
        return opts


@dataclass
class OutlineResult:
    file: Path
    pages: int = 0
    entries: int = 0
    preview: str = ""


def _entries_from_toc(doc: pymupdf.Document) -> list[dict]:
    """Deriva a lista de anexos dos bookmarks já existentes no PDF."""
    entries: list[dict] = []
    for _level, title, page in doc.get_toc():
        label = str(title).strip()
        if label and page > 0:
            entries.append({"label": label, "page": int(page)})
    return entries


def _index_pages_needed(count: int) -> int:
    return math.ceil(count / ENTRIES_PER_PAGE) if count else 1


def _draw_index(page: pymupdf.Page, title: str, entries: list[dict]) -> None:
    """Desenha uma página de índice: título, linhas com pontilhado e número.

    TextWriter (e não `page.insert_text`) porque preserva acentos, travessões
    e outros caracteres fora do ASCII na hora de extrair o texto depois.
    """
    helv = pymupdf.Font("helv")
    bold = pymupdf.Font("hebo")
    width, height = page.rect.width, page.rect.height
    margin_x, top = 56.0, 72.0
    bottom = height - 48.0
    content_w = width - 2 * margin_x
    tw = pymupdf.TextWriter(page.rect)

    tw.append(pymupdf.Point(margin_x, top), title, font=bold, fontsize=14)
    page.draw_line(
        pymupdf.Point(margin_x, top + 8),
        pymupdf.Point(width - margin_x, top + 8),
        color=(0.6, 0.6, 0.6),
        width=0.7,
    )

    y = top + 34.0
    dot_w = helv.text_length(".", fontsize=11)
    for entry in entries:
        if y > bottom:
            break  # segurança: nunca estoura a página
        number = str(entry.get("number", 0))
        num_len = helv.text_length(number, fontsize=11)
        label = str(entry["label"])
        # encurta o rótulo para caber antes do pontilhado e do número
        max_label = content_w - num_len - 24
        while label and helv.text_length(label, fontsize=11) > max_label:
            label = label[:-1]
        if label != entry["label"]:
            label = label.rstrip() + "..."
        label_w = helv.text_length(label, fontsize=11)
        gap = max(0.0, content_w - label_w - num_len)
        dots = "." * max(1, int(gap / dot_w))
        tw.append(
            pymupdf.Point(margin_x, y),
            f"{label} {dots} {number}",
            font=helv,
            fontsize=11,
        )
        y += 22.0

    tw.append(
        pymupdf.Point(margin_x, height - 30),
        "JudiFiles - sumário gerado automaticamente",
        font=helv,
        fontsize=8,
    )
    tw.write_text(page)


def build_outline(
    pdf_path: str | Path,
    workdir: Path,
    opts: OutlineOptions | None = None,
    progress=None,
) -> OutlineResult:
    """Cria o índice (páginas + bookmarks) do documento informado."""
    opts = opts or OutlineOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise ValueError("O PDF não tem páginas.")

        entries = opts.entries
        if not entries:
            entries = _entries_from_toc(doc)
            if not entries:
                raise ValueError(
                    "Nenhum anexo informado e o PDF também não tem sumário "
                    "(bookmarks) para usar como base."
                )

        total = doc.page_count
        invalid = [e["label"] for e in entries if e["page"] > total]
        if invalid:
            raise ValueError(
                f"Páginas fora do documento (o PDF tem {total} página(s)): "
                + ", ".join(invalid[:3])
                + "."
            )

        inserted = _index_pages_needed(len(entries)) if opts.insert_index else 0
        shift = inserted

        # páginas de índice no início (com o número já deslocado)
        if inserted:
            if progress:
                progress(0, total, "Criando páginas de índice...")
            first = doc[0].rect
            for i in range(inserted):
                page = doc.new_page(pno=i, width=first.width, height=first.height)
                chunk = entries[i * ENTRIES_PER_PAGE : (i + 1) * ENTRIES_PER_PAGE]
                numbered = [
                    {"label": e["label"], "number": e["page"] + shift} for e in chunk
                ]
                title = opts.title if inserted == 1 else f"{opts.title} ({i + 1}/{inserted})"
                _draw_index(page, title, numbered)
                if progress:
                    progress(i + 1, inserted, f"Página de índice {i + 1} de {inserted}...")

        # sumário navegável
        if opts.bookmarks:
            toc: list[list] = []
            if inserted:
                toc.append([1, opts.title, 1])
                for e in entries:
                    toc.append([2, e["label"], e["page"] + shift])
            else:
                for e in entries:
                    toc.append([1, e["label"], e["page"]])
            doc.set_toc(toc)

        if progress:
            progress(total - 1, total, "Finalizando sumário...")
        doc.set_metadata(
            {
                **(doc.metadata or {}),
                "title": opts.title,
                "subject": f"{len(entries)} item(ns) no sumário",
            }
        )

        stem = Path(pdf_path).stem
        dest = workdir / f"{stem}_sumario.pdf"
        doc.save(dest, garbage=3, deflate=True)
    finally:
        doc.close()

    parts = []
    if opts.insert_index:
        parts.append(f"{inserted} página(s) de índice no início")
    if opts.bookmarks:
        parts.append(f"{len(entries)} bookmark(s)")
    preview = (
        f"Sumário “{opts.title}” com {len(entries)} item(ns): "
        + " e ".join(parts)
        + "."
    )
    return OutlineResult(
        file=dest, pages=total + inserted, entries=len(entries), preview=preview
    )
