"""Numeração de páginas, Bates, carimbo "Fls." e marca d'água (Fase 3).

Três estilos de numeração no rodapé/topo (sequencial simples, Bates com
prefixo e zeros à esquerda, e "Fls." — o carimbo de folhas dos tribunais),
mais uma marca d'água diagonal com opacidade controlada. O intervalo de
páginas usa a mesma sintaxe da ferramenta "Dividir" ("1-5,8").
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.services.split import parse_ranges

log = logging.getLogger("lexscan.number")

MARGIN = 36.0
POSITIONS = (
    "bottom-center",
    "bottom-right",
    "bottom-left",
    "top-center",
    "top-right",
    "top-left",
)
STYLES = {"plain", "bates", "fls"}


@dataclass
class NumberOptions:
    """Opções da numeração/carimbo."""

    style: str = "fls"          # plain | bates | fls
    start: int = 1              # primeira folha numerada
    pad: int = 3                # zeros à esquerda (bates/fls)
    prefix: str = ""            # prefixo do Bates (ex.: "PROC")
    show_total: bool = False    # "12/30" no estilo sequencial
    position: str = "bottom-center"
    font_size: float = 10.0
    pages: str = ""             # intervalo "1-5,8"; vazio = todas
    watermark: str = ""         # texto da marca d'água (vazio = nenhuma)
    watermark_size: float = 42.0
    watermark_opacity: float = 0.15

    @classmethod
    def from_dict(cls, data: dict | None) -> "NumberOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        if opts.style not in STYLES:
            opts.style = "fls"
        if opts.position not in POSITIONS:
            opts.position = "bottom-center"
        try:
            opts.start = max(1, int(opts.start))
        except (TypeError, ValueError):
            opts.start = 1
        try:
            opts.pad = min(12, max(1, int(opts.pad)))
        except (TypeError, ValueError):
            opts.pad = 3
        opts.prefix = str(opts.prefix or "").strip()[:20]
        opts.show_total = bool(opts.show_total)
        opts.pages = str(opts.pages or "").strip()
        opts.watermark = str(opts.watermark or "").strip()[:80]
        try:
            opts.font_size = min(24.0, max(6.0, float(opts.font_size)))
        except (TypeError, ValueError):
            opts.font_size = 10.0
        try:
            opts.watermark_size = min(200.0, max(12.0, float(opts.watermark_size)))
        except (TypeError, ValueError):
            opts.watermark_size = 42.0
        try:
            opts.watermark_opacity = min(1.0, max(0.02, float(opts.watermark_opacity)))
        except (TypeError, ValueError):
            opts.watermark_opacity = 0.15
        return opts


@dataclass
class NumberResult:
    file: Path
    pages: int = 0
    stamped: int = 0
    preview: str = ""


def _label(number: int, total: int, opts: NumberOptions) -> str:
    if opts.style == "bates":
        return f"{opts.prefix}{number:0{opts.pad}d}"
    if opts.style == "fls":
        return f"Fls. {number:0{opts.pad}d}"
    text = str(number)
    if opts.show_total:
        text += f"/{total}"
    return text


def _point(text: str, page: pymupdf.Page, opts: NumberOptions) -> pymupdf.Point:
    """Ponto de ancoragem (canto/base) do carimbo na página informada."""
    width = page.rect.width
    height = page.rect.height
    length = pymupdf.get_text_length(text, fontname="helv", fontsize=opts.font_size)
    right = opts.position.endswith("right")
    center = opts.position.endswith("center")
    top = opts.position.startswith("top")

    if center:
        x = (width - length) / 2
    elif right:
        x = width - MARGIN - length
    else:
        x = MARGIN
    y = 30.0 if top else height - 24.0
    return pymupdf.Point(x, y)


def _stamp_watermark(page: pymupdf.Page, opts: NumberOptions) -> None:
    """Marca d'água diagonal centralizada, com opacidade controlada."""
    text = opts.watermark
    size = opts.watermark_size
    font = pymupdf.Font("hebo")
    length = font.text_length(text, fontsize=size)
    angle = math.radians(-35)
    # origem do texto antes da rotação, para que o centro fique no centro
    origin = pymupdf.Point(-length / 2, size * 0.35)
    matrix = pymupdf.Matrix(
        math.cos(angle), math.sin(angle), -math.sin(angle), math.cos(angle), 0, 0
    )
    rotated = pymupdf.Point(
        origin.x * matrix.a + origin.y * matrix.c + page.rect.width / 2,
        origin.x * matrix.b + origin.y * matrix.d + page.rect.height / 2,
    )
    tw = pymupdf.TextWriter(page.rect)
    tw.append(rotated, text, font=font, fontsize=size)
    tw.write_text(
        page,
        color=(0.45, 0.45, 0.45),
        opacity=opts.watermark_opacity,
        morph=(rotated, matrix),
    )


def number_pdf(
    pdf_path: str | Path,
    workdir: Path,
    opts: NumberOptions | None = None,
    progress=None,
) -> NumberResult:
    """Numera/carimba páginas e aplica marca d'água, gravando um novo PDF."""
    opts = opts or NumberOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise ValueError("O PDF não tem páginas.")

        targets = set(range(doc.page_count))  # 0-based
        if opts.pages:
            spans = parse_ranges(opts.pages, doc.page_count)
            targets = {p - 1 for start, end in spans for p in range(start, end + 1)}
        if not targets:
            raise ValueError("Intervalo de páginas inválido.")

        total = doc.page_count
        stamped = 0
        watermark_on = bool(opts.watermark)

        for index, page in enumerate(doc, start=1):
            if progress:
                progress(index - 1, total, f"Numerando página {index} de {total}...")
            zero_based = index - 1
            if zero_based in targets:
                number = opts.start + zero_based - min(targets)
                # acima: primeira página alvo recebe `start`
                text = _label(number, total, opts)
                page.insert_text(
                    _point(text, page, opts),
                    text,
                    fontsize=opts.font_size,
                    fontname="helv",
                    color=(0, 0, 0),
                )
                stamped += 1
            if watermark_on:
                _stamp_watermark(page, opts)

        if stamped == 0:
            raise ValueError("Nenhuma página numerada no intervalo informado.")

        stem = Path(pdf_path).stem
        dest = workdir / f"{stem}_numerado.pdf"
        doc.save(dest, garbage=3, deflate=True)
    finally:
        doc.close()

    style_name = {"plain": "numeração", "bates": "Bates", "fls": "carimbo Fls."}[
        opts.style
    ]
    preview = f"{style_name} aplicada em {stamped} de {total} página(s)."
    if opts.watermark:
        preview += f" Marca d'água “{opts.watermark}” em todas as páginas."
    return NumberResult(file=dest, pages=total, stamped=stamped, preview=preview)
