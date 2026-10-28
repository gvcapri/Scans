"""Conversores — imagem↔PDF, Word→PDF, PDF→PNG/JPG/TXT/DOCX.

Direção detectada pela extensão do arquivo de entrada:

  • imagem (PNG/JPG/TIFF/BMP/WEBP) → PDF (uma página por imagem/frame);
  • Word/Writer (DOC/DOCX/ODT/RTF) → PDF via LibreOffice headless;
  • PDF → PNG ou JPG (uma imagem por página; várias páginas viram ZIP);
  • PDF → TXT ou DOCX (texto digital direto; sem camada de texto, faz OCR).

O LibreOffice roda com perfil de usuário isolado (`-env:UserInstallation`)
para não brigar com uma instância aberta do sistema e para permitir execução
concorrente segura.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

import PIL.Image
import PIL.ImageSequence
import pymupdf

from app.core.config import settings

log = logging.getLogger("lexscan.convert")

IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}
OFFICE_EXTS = {".doc", ".docx", ".odt", ".rtf", ".docm"}
IMAGE_TARGETS = {"png", "jpg", "jpeg"}
TEXT_TARGETS = {"txt", "docx"}

LO_TIMEOUT_SECONDS = 300


@dataclass
class ConvertOptions:
    """Opções da conversão."""

    target: str = ""      # pdf | png | jpg | txt | docx  (vazio = automático)
    dpi: int = 200        # resolução das imagens geradas
    jpeg_quality: int = 85
    jpeg_pages: int = 20  # acima disso, gera ZIP com as imagens

    @classmethod
    def from_dict(cls, data: dict | None) -> "ConvertOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        opts.target = str(opts.target or "").lower().lstrip(".")
        if opts.target == "jpeg":
            opts.target = "jpg"
        opts.dpi = int(min(600, max(72, int(opts.dpi or 200))))
        opts.jpeg_quality = int(min(95, max(20, int(opts.jpeg_quality or 85))))
        opts.jpeg_pages = int(min(500, max(1, int(opts.jpeg_pages or 20))))
        return opts


@dataclass
class ConvertResult:
    """Resultado da conversão."""

    files: list[Path] = field(default_factory=list)
    pages: int = 0
    preview: str = ""


def detect_kind(src: Path) -> str:
    """Classifica a entrada: image | office | pdf."""
    ext = src.suffix.lower()
    if ext == ".pdf":
        return "pdf"
    if ext in IMAGE_EXTS:
        return "image"
    if ext in OFFICE_EXTS:
        return "office"
    raise ValueError(f"Formato não suportado: {ext or 'desconhecido'}.")


def auto_target(src: Path, opts: ConvertOptions) -> str:
    """Escolhe o formato de saída quando o cliente não informou."""
    kind = detect_kind(src)
    if kind in {"image", "office"}:
        return "pdf"
    if opts.target in IMAGE_TARGETS | TEXT_TARGETS:
        return opts.target
    return "png"


# ---------------------------------------------------------------- Conversões
def convert_document(
    src: Path,
    workdir: Path,
    opts: ConvertOptions | None = None,
    progress=None,
) -> ConvertResult:
    """Executa a conversão adequada ao tipo de `src`."""
    opts = opts or ConvertOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    kind = detect_kind(src)
    target = auto_target(src, opts)
    if kind == "pdf" and opts.target and opts.target not in IMAGE_TARGETS | TEXT_TARGETS:
        raise ValueError("Selecione um formato de saída válido (PNG, JPG, TXT ou DOCX).")
    if kind != "pdf" and target != "pdf":
        raise ValueError("Imagens e documentos do Word só são convertidos para PDF.")

    if progress:
        progress(0, 1, f"Convertendo para {target.upper()}...")

    if kind == "image":
        return _image_to_pdf(src, workdir)
    if kind == "office":
        return _office_to_pdf(src, workdir)
    return _pdf_to(src, workdir, target, opts, progress)


def _image_to_pdf(src: Path, workdir: Path) -> ConvertResult:
    """Imagem (ou TIFF multipágina) → PDF."""
    with PIL.Image.open(src) as first:
        frames = [f.copy() for f in PIL.ImageSequence.Iterator(first)]
    frames = [f.convert("RGB") for f in frames]
    dest = workdir / f"{src.stem}.pdf"
    if len(frames) == 1:
        frames[0].save(dest, "PDF", resolution=300)
    else:
        frames[0].save(dest, "PDF", save_all=True, append_images=frames[1:], resolution=300)
    return ConvertResult(
        files=[dest],
        pages=len(frames),
        preview=f"{len(frames)} imagem(ns) convertida(s) em PDF ({dest.name}).",
    )


def _office_to_pdf(src: Path, workdir: Path) -> ConvertResult:
    """Word/Writer → PDF usando o LibreOffice em modo headless."""
    soffice = settings.resolve_soffice()
    if not soffice:
        raise ValueError(
            "LibreOffice não encontrado. Instale o LibreOffice ou defina SOFFICE_CMD."
        )

    profile = workdir / f"lo-profile-{uuid.uuid4().hex[:8]}"
    cmd = [
        soffice,
        "--headless",
        "--norestore",
        "--invisible",
        f"-env:UserInstallation={_file_url(profile)}",
        "--convert-to",
        "pdf",
        "--outdir",
        str(workdir),
        str(src),
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            timeout=LO_TIMEOUT_SECONDS,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except subprocess.TimeoutExpired as exc:
        raise ValueError("O LibreOffice demorou demais para converter o arquivo.") from exc
    finally:
        shutil.rmtree(profile, ignore_errors=True)

    dest = workdir / f"{src.stem}.pdf"
    if not dest.exists():
        detail = (proc.stderr or proc.stdout or "").strip()[:200]
        log.warning("LibreOffice falhou: %s", detail)
        raise ValueError("Não foi possível converter o documento no LibreOffice.")

    pages = page_count(dest)
    return ConvertResult(
        files=[dest],
        pages=pages,
        preview=f"Documento convertido em PDF com {pages} página(s).",
    )


def _file_url(path: Path) -> str:
    """URL file:/// do Windows/POSIX para o perfil do LibreOffice."""
    return path.resolve().as_uri()


def _pdf_to(
    src: Path,
    workdir: Path,
    target: str,
    opts: ConvertOptions,
    progress,
) -> ConvertResult:
    """PDF → imagens ou texto."""
    source = pymupdf.open(src)
    if source.page_count == 0:
        source.close()
        raise ValueError("Documento sem páginas.")
    stem = src.stem or "documento"
    total = source.page_count
    try:
        if target in IMAGE_TARGETS:
            fmt = "PNG" if target == "png" else "JPEG"
            images: list[Path] = []
            try:
                for index in range(total):
                    if progress:
                        progress(index, total, f"Gerando página {index + 1} de {total}")
                    page = source[index]
                    pix = page.get_pixmap(dpi=opts.dpi, alpha=False)
                    name = f"{stem}_p{index + 1:03d}.{ 'png' if fmt == 'PNG' else 'jpg'}"
                    path = workdir / name
                    if fmt == "PNG":
                        pix.save(str(path))
                    else:
                        _save_jpeg(pix, path, opts.jpeg_quality)
                    images.append(path)

                if total == 1:
                    return ConvertResult(
                        files=images,
                        pages=total,
                        preview=f"Página convertida em {target.upper()} a {opts.dpi} DPI.",
                    )
                if total <= opts.jpeg_pages:
                    return ConvertResult(
                        files=images,
                        pages=total,
                        preview=(
                            f"{total} páginas convertidas em {target.upper()} "
                            f"({opts.dpi} DPI)."
                        ),
                    )
                archive = workdir / f"{stem}_imagens.zip"
                with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as zf:
                    for path in images:
                        zf.write(path, arcname=path.name)
                        path.unlink(missing_ok=True)
                return ConvertResult(
                    files=[archive],
                    pages=total,
                    preview=(
                        f"{total} páginas convertidas em {target.upper()} "
                        f"({opts.dpi} DPI), empacotadas em ZIP."
                    ),
                )
            finally:
                pass

        # -------- texto (TXT/DOCX) --------
        if progress:
            progress(0, total, "Extraindo texto...")
        texts = [page.get_text("text").strip() for page in source]
        used_ocr = False
        if not any(texts):
            texts, used_ocr = _ocr_text(src, workdir, progress)

        if target == "txt":
            body = "\n\n".join(texts).strip()
            dest = workdir / f"{stem}.txt"
            dest.write_text(body, encoding="utf-8")
        else:
            from app.services.ocr import _write_docx

            dest = workdir / f"{stem}.docx"
            _write_docx(dest, texts, stem)

        chars = sum(len(t) for t in texts)
        how = " via OCR" if used_ocr else ""
        return ConvertResult(
            files=[dest],
            pages=total,
            preview=f"Texto extraído de {total} página(s){how}: {chars} caractere(s).",
        )
    finally:
        source.close()


def _save_jpeg(pix: "pymupdf.Pixmap", path: Path, quality: int) -> None:
    """Salva o pixmap como JPEG com a qualidade pedida."""
    image = PIL.Image.frombytes("RGB", (pix.width, pix.height), pix.samples)
    image.save(path, "JPEG", quality=quality, optimize=True)


def _ocr_text(src: Path, workdir: Path, progress) -> tuple[list[str], bool]:
    """Sem camada de texto: roda o OCR para obter o conteúdo."""
    from app.services.ocr import OcrOptions, ocr_document

    result = ocr_document(
        src,
        workdir / "ocr-cache",
        OcrOptions(output="txt", force_ocr=True),
        progress=progress,
    )
    if not result.page_texts:
        return [], True
    return result.page_texts, True


def page_count(path: Path) -> int:
    doc = pymupdf.open(path)
    try:
        return doc.page_count
    finally:
        doc.close()
