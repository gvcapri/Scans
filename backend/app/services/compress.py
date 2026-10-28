"""Compressor de PDF — perfis de tribunal, divisão automática e PDF/A.

Estratégia:
  1. Ghostscript (`pdfwrite`) reduz a resolução das imagens embutidas seguindo
     uma escada de qualidade: começa no perfil pedido e vai baixando a DPI
     até atingir o limite (ou chegar ao mínimo seguro);
  2. se ainda passar do limite e `split` estiver ligado, divide o documento em
     partes contíguas (número de partes dobrado até todas caberem);
  3. com `pdfa`, a mesma passada do Ghostscript já grava PDF/A-2b com
     OutputIntent sRGB (perfil ICC do próprio Ghostscript).

Os perfis de tribunal (PJe, e-SAJ, e-Proc, Projudi) são apenas limites de
tamanho salvos pelo usuário em `/api/presets` — os valores variam entre
tribunais, por isso a interface deixa editar antes de aplicar.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from app.core.config import settings

log = logging.getLogger("lexscan.compress")

# Perfis embutidos (referência: limites usualmente publicados pelos sistemas;
# o usuário pode editar antes de aplicar).
BUILTIN_PRESETS: list[dict] = [
    {
        "id": "pje",
        "name": "PJe",
        "limit_mb": 10.0,
        "hint": "PJe — ~10 MB por PDF (varia por tribunal).",
        "quality": "ebook",
        "pdfa": False,
        "split": True,
    },
    {
        "id": "esaj",
        "name": "e-SAJ",
        "limit_mb": 10.0,
        "hint": "e-SAJ — ~10 MB por documento.",
        "quality": "ebook",
        "pdfa": False,
        "split": True,
    },
    {
        "id": "eproc",
        "name": "e-Proc",
        "limit_mb": 8.0,
        "hint": "e-Proc — ~8 MB por anexo.",
        "quality": "ebook",
        "pdfa": False,
        "split": True,
    },
    {
        "id": "projudi",
        "name": "Projudi",
        "limit_mb": 5.0,
        "hint": "Projudi — ~5 MB por documento.",
        "quality": "printer",
        "pdfa": False,
        "split": True,
    },
    {
        "id": "email",
        "name": "E-mail (2 MB)",
        "limit_mb": 2.0,
        "hint": "Tamanho seguro para anexo de e-mail.",
        "quality": "screen",
        "pdfa": False,
        "split": True,
    },
]

QUALITY_DPI = {"screen": 110, "ebook": 150, "printer": 300, "prepress": 300}
_LADDER_DPI = (150, 110, 90, 72, 50)

GS_TIMEOUT_SECONDS = 600


class GhostscriptMissing(ValueError):
    """Ghostscript não instalado — mensagem já amigável para a interface."""


@dataclass
class CompressOptions:
    """Opções do compressor."""

    limit_mb: float = 10.0        # 0 = sem limite de tamanho
    quality: str = "ebook"        # screen | ebook | printer | prepress
    dpi: int = 0                  # 0 = usar o dpi do perfil
    pdfa: bool = False            # grava PDF/A-2b
    split: bool = True            # divide se passar do limite

    @classmethod
    def from_dict(cls, data: dict | None) -> "CompressOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        opts.limit_mb = round(float(min(500, max(0, float(opts.limit_mb or 0)))), 2)
        if opts.quality not in QUALITY_DPI:
            opts.quality = "ebook"
        opts.dpi = int(min(600, max(0, int(opts.dpi or 0))))
        opts.pdfa = bool(opts.pdfa)
        opts.split = bool(opts.split)
        return opts


@dataclass
class CompressResult:
    """Resultado da compressão."""

    files: list[Path] = field(default_factory=list)
    pages: int = 0
    original_size: int = 0
    final_size: int = 0
    parts: int = 1
    preview: str = ""
    notes: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- Ghostscript
def _gs_command(
    gs: str,
    src: Path,
    dest: Path,
    dpi: int,
    pdfa_def: Path | None,
    params: Path,
    permits: list[str],
) -> list[str]:
    cmd = [
        gs,
        "-q",
        "-dNOPAUSE",
        "-dBATCH",
        "-dSAFER",
        # permissões de leitura/gravação vêm antes dos arquivos de entrada
        *permits,
        "-sDEVICE=pdfwrite",
        # o destino precisa estar definido antes de qualquer código -c
        "-sOutputFile=%s" % dest,
        "-dCompatibilityLevel=1.7",
        "-dAutoRotatePages=/None",
        # imagens: reduz a resolução e reencoda em JPEG de qualidade média
        "-dDownsampleColorImages=true",
        "-dDownsampleGrayImages=true",
        "-dDownsampleMonoImages=true",
        "-dColorImageDownsampleType=/Bicubic",
        "-dColorImageResolution=%d" % dpi,
        "-dGrayImageResolution=%d" % dpi,
        "-dMonoImageResolution=%d" % min(dpi, 300),
        "-dColorImageDownsampleThreshold=1.0",
        "-dGrayImageDownsampleThreshold=1.0",
        "-dEncodeColorImages=true",
        "-dEncodeGrayImages=true",
        "-dColorImageFilter=/DCTEncode",
        "-dAutoFilterColorImages=false",
        "-dAutoFilterGrayImages=false",
    ]
    # Parâmetros distiller (qualidade JPEG) entram como arquivo PostScript
    # executado antes do PDF: o -c do Ghostscript não convive com caminhos
    # absolutos no Windows.
    cmd.append(str(params))
    if pdfa_def is not None:
        cmd += [
            "-dPDFA=2",
            "-dPDFACompatibilityPolicy=1",
            # string (e não nome): o PDFA_def.ps faz cvn neste valor
            "-sColorConversionStrategy=sRGB",
            "-dProcessColorModel=/DeviceRGB",
            "-dDetectDuplicateImages=true",
        ]
    if pdfa_def is not None:
        cmd.append(str(pdfa_def))
    cmd.append(str(src))
    return cmd


def _run_gs(
    src: Path,
    dest: Path,
    dpi: int,
    pdfa: bool,
    workdir: Path,
    notes: list[str],
) -> None:
    """Uma passada do Ghostscript; levanta ValueError amigável em falha."""
    gs = settings.resolve_ghostscript()
    if not gs:
        raise GhostscriptMissing(
            "Ghostscript não encontrado. Instale o Ghostscript (ghostscript.com) "
            "ou defina a variável GHOSTSCRIPT_CMD."
        )

    pdfa_def: Path | None = None
    if pdfa:
        pdfa_def = _prepare_pdfa(workdir, notes)
        if pdfa_def is None:
            pdfa = False

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.unlink(missing_ok=True)
    # parâmetros de qualidade executados antes do documento de entrada
    params = workdir / "_params.ps"
    params.write_text(
        "<< /ColorImageDict << /QFactor 0.25 /HortonicFilter false "
        "/SmoothingFactor 4 >> >> setdistillerparams\n",
        encoding="ascii",
    )

    permit_dir = str(workdir).replace("\\", "/")
    src_dir = str(src.parent).replace("\\", "/")
    permits = [
        f"--permit-file-read={permit_dir}/*",
        f"--permit-file-write={permit_dir}/*",
        f"--permit-file-read={src_dir}/*",
    ]
    icc = workdir / "srgb.icc"
    if icc.exists():
        # o PDFA_def.ps abre o ICC com o nome relativo "srgb.icc" (cwd), e o
        # SAFER do Ghostscript casa permissão exatamente com esse nome
        permits.append("--permit-file-read=srgb.icc")
        permits.append(f"--permit-file-read={icc}")
    try:
        proc = subprocess.run(
            _gs_command(gs, src, dest, dpi, pdfa_def if pdfa else None, params, permits),
            capture_output=True,
            timeout=GS_TIMEOUT_SECONDS,
            text=True,
            encoding="utf-8",
            errors="replace",
            cwd=str(workdir),
        )
        if proc.returncode != 0 or not dest.exists():
            raise RuntimeError(_gs_error(proc.stdout or "") + " " + _gs_error(proc.stderr or ""))
    except FileNotFoundError as exc:  # binário sumiu entre resolve e exec
        raise GhostscriptMissing("Ghostscript não encontrado no sistema.") from exc
    except subprocess.TimeoutExpired as exc:
        raise ValueError("A compressão demorou demais e foi interrompida.") from exc


def _gs_error(stderr: str) -> str:
    text = (stderr or "").strip()
    for line in text.splitlines():
        if "error" in line.lower() or "undefined" in line.lower():
            return line[:300]
    return text[:300] or "falha desconhecida do Ghostscript"


def _prepare_pdfa(workdir: Path, notes: list[str]) -> Path | None:
    """Monta a passagem do PDF/A: usa o PDFA_def.ps do próprio Ghostscript
    com o ICC sRGB copiado para a pasta de trabalho (referência relativa)."""
    gs = settings.resolve_ghostscript()
    root = Path(gs).resolve().parent.parent  # .../gs10.08.0/bin/gswin64c.exe
    def_ps = root / "lib" / "PDFA_def.ps"
    icc = root / "iccprofiles" / "srgb.icc"
    if not def_ps.exists() or not icc.exists():
        notes.append("PDF/A indisponível: recursos do Ghostscript não encontrados.")
        return None
    shutil.copy(icc, workdir / "srgb.icc")
    shutil.copy(def_ps, workdir / "PDFA_def.ps")
    return workdir / "PDFA_def.ps"


# ------------------------------------------------------------------ Pipeline
def compress_pdf(
    src: Path,
    workdir: Path,
    opts: CompressOptions | None = None,
    progress=None,
) -> CompressResult:
    """Comprime `src` até o limite pedido (dividindo se necessário)."""
    opts = opts or CompressOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    if src.suffix.lower() != ".pdf":
        raise ValueError("O compressor aceita apenas PDF.")
    doc = pymupdf.open(src)
    pages = doc.page_count
    doc.close()
    if pages == 0:
        raise ValueError("Documento sem páginas.")

    original = src.stat().st_size
    limit = int(opts.limit_mb * 1024 * 1024) if opts.limit_mb > 0 else 0
    notes: list[str] = []
    steps = _ladder(opts)
    dest = workdir / f"{src.stem}_comprimido.pdf"

    if progress:
        progress(0, max(1, len(steps)), "Comprimindo...")

    # 1) escada de qualidade até caber no limite
    for dpi in steps:
        _run_gs(src, dest, dpi, opts.pdfa, workdir, notes)
        if limit == 0 or dest.stat().st_size <= limit:
            break

    final_size = dest.stat().st_size
    if limit and final_size > limit:
        if not opts.split or pages < 2:
            notes.append(
                f"Arquivo final em {_mb(final_size)} — acima do limite de "
                f"{opts.limit_mb:g} MB. Reduza o limite ou ative a divisão."
            )
        else:
            parts = _split_until_fits(
                src, workdir, opts, limit, steps[-1], notes, progress
            )
            if parts:
                return _report(parts, pages, original, opts, notes, used_split=True)

    return _report([dest], pages, original, opts, notes, used_split=False)


def _report(
    files: list[Path],
    pages: int,
    original: int,
    opts: CompressOptions,
    notes: list[str],
    used_split: bool,
) -> CompressResult:
    final = sum(f.stat().st_size for f in files)
    saved = 0 if not original else round(100 - (final * 100 / original))
    parts = len(files)
    if used_split:
        preview = (
            f"{parts} partes de {pages} página(s), total { _mb(final) } "
            f"(original { _mb(original) }), cada uma dentro do limite de "
            f"{opts.limit_mb:g} MB."
        )
    else:
        preview = (
            f"{_mb(final)} após compressão ({saved}% menor que "
            f"{_mb(original)}), {pages} página(s)"
            + (f", em {parts} arquivo(s)." if parts > 1 else ".")
        )
    if opts.pdfa:
        preview += " PDF/A-2b aplicado."
    if notes:
        preview += " " + " ".join(notes)
    return CompressResult(
        files=files,
        pages=pages,
        original_size=original,
        final_size=final,
        parts=parts,
        preview=preview[:2000],
        notes=notes,
    )


def _ladder(opts: CompressOptions) -> list[int]:
    """Sequência de resoluções a tentar, da mais fiel para a mais compacta."""
    base = opts.dpi or QUALITY_DPI[opts.quality]
    steps = [base]
    for dpi in _LADDER_DPI:
        if dpi < steps[-1]:
            steps.append(dpi)
    return steps


def _split_until_fits(
    src: Path,
    workdir: Path,
    opts: CompressOptions,
    limit: int,
    dpi: int,
    notes: list[str],
    progress,
) -> list[Path]:
    """Dobra o número de partes até todas ficarem dentro do limite."""
    source = pymupdf.open(src)
    stem = src.stem or "documento"
    pages = source.page_count
    parts: list[Path] = []
    try:
        parts_count = 2
        while parts_count <= pages:
            if progress:
                progress(
                    min(parts_count, pages),
                    max(pages, parts_count),
                    f"Dividindo em {parts_count} partes...",
                )
            candidate = _compress_in_parts(
                source, workdir, stem, opts, dpi, parts_count, notes
            )
            sizes = [f.stat().st_size for f in candidate]
            if all(size <= limit for size in sizes):
                parts = candidate
                break
            for path in candidate:
                path.unlink(missing_ok=True)
            parts_count *= 2
        if not parts:
            # nem uma página por arquivo coube: devolve a versão por página
            # com aviso (melhor entregar algo do que falhar).
            parts = _compress_in_parts(source, workdir, stem, opts, dpi, pages, notes)
            notes.append(
                "Há páginas maiores que o limite mesmo após a compressão máxima; "
                "as partes foram geradas assim mesmo."
            )
    finally:
        source.close()
    return parts


def _compress_in_parts(
    source: "pymupdf.Document",
    workdir: Path,
    stem: str,
    opts: CompressOptions,
    dpi: int,
    parts_count: int,
    notes: list[str],
) -> list[Path]:
    """Corta em `parts_count` blocos contíguos e comprime cada um."""
    pages = source.page_count
    per_part = max(1, -(-pages // parts_count))  # teto da divisão
    produced: list[Path] = []
    for start in range(0, pages, per_part):
        end = min(start + per_part - 1, pages - 1)
        index = len(produced) + 1
        chunk = workdir / f"_chunk_{index}.pdf"
        part = pymupdf.open()
        try:
            part.insert_pdf(source, from_page=start, to_page=end)
            part.save(chunk, garbage=3, deflate=True)
        finally:
            part.close()
        dest = workdir / f"{stem}_parte_{index}.pdf"
        _run_gs(chunk, dest, dpi, opts.pdfa, workdir, notes)
        chunk.unlink(missing_ok=True)
        produced.append(dest)
    return produced


def _mb(size: int) -> str:
    return f"{size / (1024 * 1024):.2f} MB" if size >= 1024 * 1024 else f"{size // 1024} KB"
