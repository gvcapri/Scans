"""OCR de documentos (PDF escaneado, JPG, PNG, TIFF) — PyMuPDF + Tesseract.

Pipeline por página:
  1. renderiza a página em alta resolução (padrão 300 DPI);
  2. pré-processa a imagem: rotação automática (OSD), deskew (perfil de
     projeção), remoção de ruído (mediana), realce de contraste;
  3. roda o Tesseract (`por`+`eng`) e coleta caixas palavra a palavra;
  4. monta a saída:
       • PDF pesquisável = imagem da página + texto invisível (render_mode 3),
         ou seja, busca/destaque funcionam, mas o visual é a imagem;
       • TXT / DOCX com o texto extraído.

Tudo é configurado por `OcrOptions`; o progresso é reportado página a página
via callback, para a barra de progresso da interface.
"""

from __future__ import annotations

import io
import logging
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import numpy as np
import PIL.Image
import PIL.ImageFilter
import PIL.ImageOps
import pymupdf
import pytesseract
from docx import Document as DocxDocument
from docx.shared import Pt
from pytesseract import Output

from app.core.config import settings

log = logging.getLogger("lexscan.ocr")

# (página_atual, total, mensagem)
ProgressFn = Callable[[int, int, str], None]

_OSD_RE = re.compile(r"Rotate:\s*(\d+)")


# --------------------------------------------------------------------------
# Configuração do Tesseract
# --------------------------------------------------------------------------
def configure_tesseract() -> str:
    """Aponta o pytesseract para o binário e os idiomas do ambiente."""
    cmd = settings.resolve_tesseract()
    pytesseract.pytesseract.tesseract_cmd = cmd
    tessdata = settings.resolve_tessdata()
    if tessdata is not None:
        os.environ.setdefault("TESSDATA_PREFIX", str(tessdata))
    return cmd


@dataclass
class OcrOptions:
    """Opções do job de OCR (espelhadas 1:1 na interface)."""

    lang: str = "por+eng"          # idiomas do Tesseract
    output: str = "pdf"            # pdf | txt | docx
    dpi: int = 300                 # resolução de renderização/OCR
    deskew: bool = True            # correção de inclinação
    denoise: bool = True           # remoção de ruído
    auto_rotate: bool = True       # rotação automática (OSD)
    enhance_contrast: bool = True  # melhoria de contraste
    force_ocr: bool = False        # re-OCR mesmo com texto já existente
    jpeg_quality: int = 85         # qualidade do raster no PDF de saída

    @classmethod
    def from_dict(cls, data: dict | None) -> "OcrOptions":
        """Constrói apenas com campos conhecidos (ignora lixo do cliente)."""
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        if opts.output not in {"pdf", "txt", "docx"}:
            opts.output = "pdf"
        opts.dpi = int(min(600, max(150, int(opts.dpi))))
        opts.jpeg_quality = int(min(95, max(30, int(opts.jpeg_quality))))
        # idiomas validados contra a lista real instalada
        available = set(languages())
        asked = [l for l in re.split(r"[+,;\s]+", opts.lang) if l]
        opts.lang = "+".join(dict.fromkeys(l for l in asked if l in available)) or "eng"
        return opts


def languages() -> list[str]:
    """Idiomas efetivamente disponíveis no Tesseract do ambiente."""
    try:
        return [l.strip() for l in pytesseract.get_languages(config="") if l.strip()]
    except Exception:  # pragma: no cover - tesseract ausente
        return ["eng"]


# --------------------------------------------------------------------------
# Pré-processamento de imagem
# --------------------------------------------------------------------------
def _auto_rotate(img: PIL.Image.Image) -> PIL.Image.Image:
    """Gira a imagem para a orientação de leitura (via OSD do Tesseract)."""
    try:
        osd = pytesseract.image_to_osd(img)
        match = _OSD_RE.search(osd)
        angle = int(match.group(1)) if match else 0
        if angle:
            # PIL gira no sentido anti-horário para ângulo positivo.
            img = img.rotate(-angle, expand=True, fillcolor="white")
    except Exception:
        pass  # imagem sem orientação detectável: segue como está
    return img


def _deskew(img: PIL.Image.Image, max_angle: float = 5.0) -> tuple[PIL.Image.Image, float]:
    """Corrige inclinação medindo a variação do perfil de projeção horizontal.

    Retorna (imagem, ângulo corrigido). O ângulo que maximiza a variância das
    linhas de tinta é o que deixa o texto mais "alinhdado".
    """
    gray = PIL.ImageOps.grayscale(img)
    # reduz para caber em ~900px: suficiente e muito mais rápido
    scale = max(1.0, gray.width / 900.0)
    small = gray.resize((max(1, int(gray.width / scale)), max(1, int(gray.height / scale))))
    bw = np.asarray(small.point(lambda p: 255 if p > 170 else 0), dtype=np.uint8)
    ink = (bw < 128).astype(np.float32)
    if int(ink.sum()) < 200:  # página quase vazia
        return img, 0.0

    best_angle, best_score = 0.0, -1.0
    for angle in np.arange(-max_angle, max_angle + 1e-9, 0.25):
        rotated = PIL.Image.fromarray((ink * 255).astype(np.uint8)).rotate(
            float(angle), resample=PIL.Image.BILINEAR, fillcolor=0
        )
        rows = np.asarray(rotated, dtype=np.float32).sum(axis=1)
        score = float(rows.var())
        if score > best_score:
            best_score, best_angle = score, float(angle)

    if abs(best_angle) < 0.25:
        return img, 0.0
    corrected = img.rotate(best_angle, resample=PIL.Image.BICUBIC, fillcolor="white")
    return corrected, best_angle


def preprocess(img: PIL.Image.Image, opts: OcrOptions) -> PIL.Image.Image:
    """Aplica as correções pedidas antes do reconhecimento."""
    work = img.convert("L") if (opts.denoise or opts.enhance_contrast) else img.copy()
    if opts.auto_rotate:
        work = _auto_rotate(work)
    if opts.enhance_contrast:
        work = PIL.ImageOps.autocontrast(work, cutoff=1)
    if opts.denoise:
        work = work.filter(PIL.ImageFilter.MedianFilter(3))
    if opts.deskew:
        work, _angle = _deskew(work)
    return work


# --------------------------------------------------------------------------
# OCR
# --------------------------------------------------------------------------
@dataclass
class Word:
    """Palavra com caixa em coordenadas de pixel da imagem renderizada."""

    text: str
    x: float
    y: float
    w: float
    h: float


@dataclass
class OcrResult:
    """Resultado de um job de OCR."""

    files: list[Path] = field(default_factory=list)
    pages: int = 0
    preview: str = ""
    page_texts: list[str] = field(default_factory=list)


def _extract_words(data: dict, min_conf: int = 0) -> tuple[list[list[Word]], list[str]]:
    """Agrupa os dados do Tesseract em (palavras por página) e linhas de texto."""
    words: list[list[Word]] = []
    lines: list[str] = []
    current_key: tuple | None = None
    current_line: list[Word] = []
    current_text: list[str] = []

    n = len(data["text"])
    for i in range(n):
        text = (data["text"][i] or "").strip()
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if not text or conf < min_conf:
            continue
        key = (data["block_num"][i], data["par_num"][i], data["line_num"][i])
        if key != current_key:
            if current_line:
                words.append(current_line)
                lines.append(" ".join(current_text))
            current_key, current_line, current_text = key, [], []
        current_line.append(
            Word(
                text=text,
                x=float(data["left"][i]),
                y=float(data["top"][i]),
                w=float(data["width"][i]),
                h=float(data["height"][i]),
            )
        )
        current_text.append(text)

    if current_line:
        words.append(current_line)
        lines.append(" ".join(current_text))
    return words, lines


def _to_jpeg(img: PIL.Image.Image, quality: int) -> bytes:
    """Codifica a página como JPEG (controla o tamanho do PDF final)."""
    buf = io.BytesIO()
    if img.mode not in ("RGB", "L"):
        img = img.convert("RGB")
    img.save(buf, "JPEG", quality=quality, optimize=True)
    return buf.getvalue()


def _insert_text_layer(
    page: pymupdf.Page,
    words: Sequence[Word],
    dpi: int,
) -> int:
    """Insere o texto invisível (render_mode 3) sobre a imagem da página.

    Cada palavra recebe a caixa original — é isso que permite busca e
    destaque de trechos no PDF pesquisável.
    """
    scale = 72.0 / dpi  # pixel -> ponto tipográfico
    inserted = 0
    for word in words:
        if not word.text.strip():
            continue
        x0 = word.x * scale
        y1 = (word.y + word.h) * scale  # base da linha
        fontsize = max(4.0, word.h * scale * 0.92)
        try:
            page.insert_text(
                pymupdf.Point(x0, y1 - 0.5),
                word.text,
                fontsize=fontsize,
                fontname="helv",
                color=(0, 0, 0),
                render_mode=3,  # invisível (camada de OCR)
                overlay=True,
            )
            inserted += 1
        except Exception:
            continue  # caractere fora do conjunto: não derruba o job
    return inserted


def ensure_pdf(src: Path, workdir: Path) -> Path:
    """Normaliza a entrada em PDF (imagens → PDF a 300 DPI)."""
    if src.suffix.lower() == ".pdf":
        return src
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    with PIL.Image.open(src) as first:
        frames = [f.copy() for f in PIL.ImageSequence.Iterator(first)]
    frames = [f.convert("RGB") for f in frames]
    out = workdir / f"{src.stem}.pdf"
    if len(frames) == 1:
        frames[0].save(out, "PDF", resolution=300)
    else:
        frames[0].save(
            out, "PDF", save_all=True, append_images=frames[1:], resolution=300
        )
    return out


# --------------------------------------------------------------------------
# Pipeline principal
# --------------------------------------------------------------------------
def ocr_document(
    src: Path,
    workdir: Path,
    opts: OcrOptions | None = None,
    progress: ProgressFn | None = None,
) -> OcrResult:
    """Executa o OCR de `src` e grava a saída em `workdir`."""
    opts = opts or OcrOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    configure_tesseract()

    def report(page: int, total: int, message: str) -> None:
        if progress:
            progress(page, total, message)

    report(0, 0, "Preparando documento...")
    pdf_path = ensure_pdf(src, workdir)
    source = pymupdf.open(pdf_path)
    if source.page_count == 0:
        raise ValueError("Documento sem páginas.")

    total = source.page_count
    matrix = pymupdf.Matrix(opts.dpi / 72.0, opts.dpi / 72.0)

    out_doc = pymupdf.open() if opts.output == "pdf" else None
    page_texts: list[str] = []

    try:
        for index in range(total):
            report(index, total, f"OCR da página {index + 1} de {total}")
            page = source[index]

            existing = page.get_text().strip()
            if existing and not opts.force_ocr:
                # Já tem camada de texto: reaproveita sem desperdiçar OCR.
                page_texts.append(existing)
                if out_doc is not None:
                    out_doc.insert_pdf(source, from_page=index, to_page=index)
                continue

            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image = PIL.Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            ocr_image = preprocess(image, opts)
            data = pytesseract.image_to_data(
                ocr_image,
                lang=opts.lang,
                config="--oem 3 --psm 3",
                output_type=Output.DICT,
            )
            words, lines = _extract_words(data)
            page_texts.append("\n".join(lines))

            if out_doc is not None:
                new_page = out_doc.new_page(width=page.rect.width, height=page.rect.height)
                new_page.insert_image(
                    new_page.rect, stream=_to_jpeg(image, opts.jpeg_quality)
                )
                _insert_text_layer(new_page, [w for line in words for w in line], opts.dpi)

        report(total, total, "Finalizando arquivo...")
        result = OcrResult(pages=total, page_texts=page_texts)
        preview = "\n\n".join(page_texts).strip()
        result.preview = preview[:20000]

        stem = src.stem or "documento"
        if opts.output == "pdf" and out_doc is not None:
            out_doc.set_metadata(
                {"title": "", "author": "", "subject": "", "keywords": "", "creator": ""}
            )
            out_path = workdir / f"{stem}_ocr.pdf"
            out_doc.save(out_path, garbage=3, deflate=True)
            result.files.append(out_path)
        elif opts.output == "txt":
            out_path = workdir / f"{stem}_ocr.txt"
            out_path.write_text(preview, encoding="utf-8")
            result.files.append(out_path)
        elif opts.output == "docx":
            out_path = workdir / f"{stem}_ocr.docx"
            _write_docx(out_path, page_texts, stem)
            result.files.append(out_path)

        return result
    finally:
        source.close()
        if out_doc is not None:
            out_doc.close()


def _write_docx(path: Path, page_texts: list[str], title: str) -> None:
    """Gera o DOCX com uma quebra de página por página do original."""
    doc = DocxDocument()
    doc.add_heading(title, level=1)
    for i, text in enumerate(page_texts):
        if i:
            doc.add_page_break()
        for line in text.splitlines():
            para = doc.add_paragraph(line)
            para.paragraph_format.space_after = Pt(4)
    doc.save(path)


def render_preview(path: Path, page_index: int = 0, dpi: int = 110) -> bytes:
    """PNG da página para a pré-visualização da interface."""
    doc = pymupdf.open(path)
    try:
        if page_index >= doc.page_count:
            raise IndexError("página inexistente")
        page = doc[page_index]
        pix = page.get_pixmap(dpi=dpi, alpha=False)
        return pix.tobytes("png")
    finally:
        doc.close()


def page_count(path: Path) -> int:
    doc = pymupdf.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()
