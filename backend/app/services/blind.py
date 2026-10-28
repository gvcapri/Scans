"""PDF Blindado — funcionalidade central do LexScan.

O que faz:
  1. Rasteriza cada página em alta resolução (150/200/300 DPI) e remonta um
     PDF novo contendo **apenas imagens** — some texto selecionável,
     formulários, campos, scripts, anotações, links e qualquer conteúdo
     editável.
  2. Toggle opcional "manter camada de texto pesquisável": roda o OCR por cima
     das imagens e insere texto invisível (busca funciona, o documento segue
     visualmente achatado — ninguém "desacha" para editar).
  3. Senha de proprietário opcional: aplica restrições de permissão no PDF
     (bloqueia edição, cópia e extração em leitores que honram a norma).
  4. Remove metadados (autor, software, histórico de edição) — DocInfo e XMP.
  5. Qualidade x tamanho: compressão JPEG ajustável.
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass, field
from pathlib import Path

import PIL.Image
import pikepdf
import pymupdf

from app.services.ocr import (
    OcrOptions,
    _insert_text_layer,
    _to_jpeg,
    configure_tesseract,
    preprocess,
)
import pytesseract
from pytesseract import Output

log = logging.getLogger("lexscan.blind")


@dataclass
class BlindOptions:
    """Opções do PDF Blindado."""

    dpi: int = 300                       # 150 | 200 | 300
    jpeg_quality: int = 80               # qualidade x tamanho
    keep_text_layer: bool = False        # OCR por cima (pesquisável)
    owner_password: str = ""             # senha que bloqueia edição/cópia
    user_password: str = ""              # senha de abertura (opcional)
    lang: str = "por+eng"                # idioma do OCR opcional

    @classmethod
    def from_dict(cls, data: dict | None) -> "BlindOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        if opts.dpi not in (150, 200, 300):
            opts.dpi = 300
        opts.jpeg_quality = int(min(95, max(20, int(opts.jpeg_quality))))
        opts.owner_password = str(opts.owner_password or "")[:128]
        opts.user_password = str(opts.user_password or "")[:128]
        opts.lang = str(opts.lang or "por+eng")
        return opts


@dataclass
class BlindResult:
    """Resultado do serviço de blindagem."""

    file: Path
    pages: int = 0
    size: int = 0
    has_text_layer: bool = False
    notes: list[str] = field(default_factory=list)


def blind_pdf(
    src: Path,
    workdir: Path,
    opts: BlindOptions | None = None,
    progress=None,
) -> BlindResult:
    """Gera a versão blindada de `src` em `workdir`."""
    opts = opts or BlindOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    source = pymupdf.open(src)
    if source.page_count == 0:
        raise ValueError("Documento sem páginas.")

    total = source.page_count
    matrix = pymupdf.Matrix(opts.dpi / 72.0, opts.dpi / 72.0)
    out = pymupdf.open()
    ocr_words = 0

    try:
        for index in range(total):
            if progress:
                progress(index, total, f"Achatando página {index + 1} de {total}")

            page = source[index]
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            image = PIL.Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

            new_page = out.new_page(width=page.rect.width, height=page.rect.height)
            new_page.insert_image(
                new_page.rect, stream=_to_jpeg(image, opts.jpeg_quality)
            )

            if opts.keep_text_layer:
                try:
                    configure_tesseract()
                    ocr_image = preprocess(image, OcrOptions(lang=opts.lang))
                    data = pytesseract.image_to_data(
                        ocr_image,
                        lang=opts.lang,
                        config="--oem 3 --psm 3",
                        output_type=Output.DICT,
                    )
                    words = [
                        w
                        for line in _words_from(data)
                        for w in line
                    ]
                    ocr_words += _insert_text_layer(new_page, words, opts.dpi)
                except Exception as exc:  # OCR opcional: não bloqueia a blindagem
                    log.warning("OCR na blindagem falhou: %s", type(exc).__name__)
                    opts.keep_text_layer = False

        # --- metadados: nada de autor/software/histórico -------------------
        out.set_metadata(
            {
                "title": "",
                "author": "",
                "subject": "",
                "keywords": "",
                "creator": "",
                "producer": "",
                "creationDate": "",
                "modDate": "",
            }
        )
        flat = workdir / f"{src.stem}_blindado.pdf"
        out.save(flat, garbage=4, deflate=True, clean=True)
    finally:
        source.close()
        out.close()

    final = workdir / f"{src.stem}_blindado_final.pdf"
    _apply_permissions_and_strip_metadata(flat, final, opts)
    flat.unlink(missing_ok=True)

    return BlindResult(
        file=final,
        pages=total,
        size=final.stat().st_size,
        has_text_layer=bool(opts.keep_text_layer),
        notes=[],
    )


def _words_from(data: dict):
    """Caixas de palavra do Tesseract (mesmo agrupamento do OCR)."""
    from app.services.ocr import Word, _extract_words

    words, _ = _extract_words(data)
    return words


def _apply_permissions_and_strip_metadata(
    src: Path, dest: Path, opts: BlindOptions
) -> None:
    """Finalização com pikepdf: metadados zerados + permissões/senha.

    A senha de proprietário bloqueia edição e extração nos leitores PDF que
    honram a norma (Adobe, Firefox, Preview, a maioria dos visualizadores).
    """
    with pikepdf.open(src) as pdf:
        # 1) metadados DocInfo
        for key in list(pdf.docinfo.keys()):
            try:
                del pdf.docinfo[key]
            except Exception:
                pass
        # 2) metadados XMP
        if "/Metadata" in pdf.Root:
            try:
                del pdf.Root.Metadata
            except Exception:
                pass
        # 3) higiene: JS, ações automáticas, embutidos, formulários
        for key in ("/OpenAction", "/AA", "/AcroForm"):
            if key in pdf.Root:
                try:
                    del pdf.Root[key]
                except Exception:
                    pass

        permissions = pikepdf.Permissions(
            accessibility=True,                      # leitura assistiva OK
            print_lowres=True,
            print_highres=True,
            # extração/cópia só se mantivermos a camada de texto
            extract=bool(opts.keep_text_layer),
            modify_annotation=False,
            modify_form=False,
            modify_assembly=False,
            modify_other=False,
        )

        encryption = None
        if opts.owner_password:
            encryption = pikepdf.Encryption(
                user=opts.user_password,
                owner=opts.owner_password,
                R=6,
                allow=permissions,
                aes=True,
                metadata=False,
            )

        dest.unlink(missing_ok=True)
        pdf.save(
            str(dest),
            encryption=encryption,
            linearize=True,
        )
