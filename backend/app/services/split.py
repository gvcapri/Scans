"""Divisão de PDF — por intervalos, extração de páginas ou blocos fixos.

Três modos:
  • `ranges`  — cada intervalo ("1-5,8,10-12") vira um PDF separado;
  • `extract` — as páginas escolhidas saem num único PDF (na ordem pedida);
  • `every`   — divide em blocos de N páginas (útil para anexos grandes).

A numeração é 1-based e inclusiva nos dois extremos, como na interface.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

log = logging.getLogger("lexscan.split")

_RANGE_RE = re.compile(r"^\s*(\d+)\s*(?:-\s*(\d+)?)?\s*$")


@dataclass
class SplitOptions:
    """Opções da divisão."""

    mode: str = "ranges"     # ranges | extract | every
    ranges: str = ""         # "1-5,8,10-12" (ranges/extract)
    every: int = 10          # tamanho do bloco no modo `every`

    @classmethod
    def from_dict(cls, data: dict | None) -> "SplitOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        if opts.mode not in {"ranges", "extract", "every"}:
            opts.mode = "ranges"
        opts.ranges = str(opts.ranges or "").strip()
        opts.every = int(min(500, max(1, int(opts.every or 1))))
        return opts


@dataclass
class SplitResult:
    """Resultado da divisão."""

    files: list[Path] = field(default_factory=list)
    pages: int = 0
    preview: str = ""


def parse_ranges(spec: str, page_count: int) -> list[tuple[int, int]]:
    """Converte "1-3,5,7" em [(1,3),(5,5),(7,7)] validando contra o documento."""
    if not spec.strip():
        raise ValueError("Informe os intervalos de páginas (ex.: 1-5, 8, 10-12).")

    parsed: list[tuple[int, int]] = []
    for chunk in spec.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        match = _RANGE_RE.match(chunk)
        if not match:
            raise ValueError(f"Intervalo inválido: '{chunk}'. Use 1-5, 8 ou 10-12.")
        start = int(match.group(1))
        end = int(match.group(2) or match.group(1))
        if start > end:
            start, end = end, start
        if start < 1 or end > page_count:
            raise ValueError(
                f"Intervalo {start}-{end} fora do documento (1 a {page_count})."
            )
        parsed.append((start, end))

    if not parsed:
        raise ValueError("Nenhum intervalo válido informado.")
    return parsed


def split_pdf(
    src: Path,
    workdir: Path,
    opts: SplitOptions | None = None,
    progress=None,
) -> SplitResult:
    """Aplica o modo escolhido e grava os PDFs de saída em `workdir`."""
    opts = opts or SplitOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if src.suffix.lower() != ".pdf":
        raise ValueError("A divisão funciona apenas em arquivos PDF.")

    source = pymupdf.open(src)
    if source.page_count == 0:
        source.close()
        raise ValueError("Documento sem páginas.")

    stem = src.stem or "documento"
    pages = source.page_count
    outputs: list[tuple[str, list[tuple[int, int]]]] = []  # (nome, intervalos)

    try:
        if opts.mode == "every":
            size = opts.every
            blocks = [
                (start, min(start + size - 1, pages))
                for start in range(1, pages + 1, size)
            ]
            outputs = [(f"{stem}_parte_{i}.pdf", [b]) for i, b in enumerate(blocks, 1)]
        else:
            spans = parse_ranges(opts.ranges, pages)
            if opts.mode == "extract":
                outputs = [(f"{stem}_paginas_selecionadas.pdf", spans)]
            else:
                outputs = [
                    (f"{stem}_parte_{i}.pdf", [span])
                    for i, span in enumerate(spans, 1)
                ]

        total_parts = len(outputs)
        written: list[Path] = []
        for index, (name, spans) in enumerate(outputs, start=1):
            if progress:
                progress(index - 1, total_parts, f"Gerando parte {index} de {total_parts}")
            part = pymupdf.open()
            try:
                for start, end in spans:
                    part.insert_pdf(source, from_page=start - 1, to_page=end - 1)
                dest = workdir / name
                part.save(dest, garbage=3, deflate=True)
                written.append(dest)
            finally:
                part.close()

        if progress:
            progress(total_parts, total_parts, "Finalizando...")

        if opts.mode == "extract":
            selected = sum(end - start + 1 for start, end in outputs[0][1])
            preview = f"{selected} página(s) extraída(s) de {pages} em um novo PDF."
        else:
            preview = (
                f"{pages} página(s) dividida(s) em {total_parts} arquivo(s), "
                f"com {', '.join(str(_count(s)) for _, ss in outputs[:8] for s in ss)} página(s) cada."
                if opts.mode == "every"
                else f"{total_parts} arquivo(s) gerado(s) a partir de {pages} página(s)."
            )
        return SplitResult(files=written, pages=pages, preview=preview[:2000])
    finally:
        source.close()


def _count(span: tuple[int, int]) -> int:
    return span[1] - span[0] + 1
