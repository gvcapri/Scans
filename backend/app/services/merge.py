"""Mesclagem de PDFs — une vários arquivos na ordem pedida, com reordenação.

A ordem de entrada vem do cliente (a interface permite arrastar/reordenar os
arquivos antes de enviar), então este serviço apenas respeita `sources[:]`.
Cada arquivo de origem vira um item de sumário (bookmark), o que facilita
navegar petições com anexos numerados.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

log = logging.getLogger("lexscan.merge")


@dataclass
class MergeOptions:
    """Opções da mesclagem."""

    bookmarks: bool = True  # cria item de sumário por arquivo de origem
    title: str = ""          # título do PDF final (opcional)

    @classmethod
    def from_dict(cls, data: dict | None) -> "MergeOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        opts.bookmarks = bool(opts.bookmarks)
        opts.title = str(opts.title or "")[:200]
        return opts


@dataclass
class MergeResult:
    """Resultado da mesclagem."""

    file: Path
    pages: int = 0
    parts: int = 0
    preview: str = ""
    warnings: list[str] = field(default_factory=list)


def merge_pdfs(
    sources: list[Path],
    workdir: Path,
    opts: MergeOptions | None = None,
    progress=None,
) -> MergeResult:
    """Une todos os PDFs de `sources` (nesse exato ordem) em um arquivo só."""
    opts = opts or MergeOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if not sources:
        raise ValueError("Nenhum arquivo para mesclar.")

    total_pages = 0
    opened: list[tuple[str, pymupdf.Document]] = []
    for path in sources:
        if path.suffix.lower() != ".pdf":
            raise ValueError(
                f"A mesclagem aceita apenas PDF (recebido: {path.suffix or 'sem extensão'})."
            )
        doc = pymupdf.open(path)
        if doc.page_count == 0:
            doc.close()
            raise ValueError(f"O arquivo '{path.name}' não tem páginas.")
        total_pages += doc.page_count
        opened.append((path.stem or "arquivo", doc))

    out = pymupdf.open()
    try:
        toc: list[list] = []
        current = 1
        for position, (name, doc) in enumerate(opened, start=1):
            if progress:
                progress(
                    position - 1,
                    len(opened),
                    f"Juntando {position} de {len(opened)}...",
                )
            if opts.bookmarks:
                toc.append([1, name, current])
            out.insert_pdf(doc)
            current += doc.page_count

        metadata = out.metadata or {}
        metadata.update(
            {
                "title": opts.title or (opened[0][0] if opened else ""),
                "author": "",
                "subject": "",
                "keywords": "",
                "creator": "",
                "producer": "",
            }
        )
        out.set_metadata(metadata)
        if toc:
            out.set_toc(toc)

        stem = opened[0][0] if opened else "documento"
        dest = workdir / f"{stem}_mesclado.pdf"
        out.save(dest, garbage=3, deflate=True)
    finally:
        out.close()
        for _, doc in opened:
            doc.close()

    names = ", ".join(name for name, _ in opened[:6])
    if len(opened) > 6:
        names += f" (+{len(opened) - 6})"
    return MergeResult(
        file=dest,
        pages=total_pages,
        parts=len(opened),
        preview=(
            f"{len(opened)} arquivo(s) mesclados em {total_pages} página(s): {names}."
        ),
    )
