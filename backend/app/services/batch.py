"""Processamento em lote com fluxos reutilizáveis (Fase 4).

Recebe vários arquivos **ou um ZIP** e aplica uma sequência de passos
(um "fluxo") em cada um deles, devolvendo tudo num ZIP só:

    ZIP/serviços → [OCR → Comprimir] → lote_processado.zip

Regras de comportamento:

* o ZIP de entrada é validado contra travessia de caminho e "bomba"
  (`validate_zip_file`) e só arquivos com extensão compatível entram;
* passo incompatível com um arquivo (ex.: "Blindar" numa imagem) é
  **ignorado com aviso**, não derruba o lote inteiro;
* o fluxo pode ser salvo como perfil (`tool="batch"`) e reutilizado.

Passos suportados: `ocr`, `blind`, `compress`, `convert`, `redact`,
`number` — todos operam um arquivo por vez, o que é exatamente o que se
quer num lote.
"""

from __future__ import annotations

import logging
import shutil
import zipfile
from dataclasses import dataclass, field
from pathlib import Path

from app.services.validation import sanitize_filename, validate_zip_file

log = logging.getLogger("lexscan.batch")

SUPPORTED_STEPS = {"ocr", "blind", "compress", "convert", "redact", "number"}
MAX_STEPS = 6
MAX_FILES = 50
INNER_EXTS = {
    ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
    ".doc", ".docx", ".odt", ".rtf", ".docm",
}


@dataclass
class BatchOptions:
    """Fluxo do lote (sequência de passos)."""

    steps: list[dict] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: dict | None) -> "BatchOptions":
        data = data or {}
        opts = cls()
        raw = data.get("steps") or []
        if not isinstance(raw, list):
            raise ValueError("'steps' precisa ser uma lista de passos.")
        steps: list[dict] = []
        for item in raw[:MAX_STEPS]:
            if not isinstance(item, dict):
                continue
            kind = str(item.get("kind") or "")
            if kind not in SUPPORTED_STEPS:
                raise ValueError(
                    f"Passo desconhecido no fluxo: '{kind}'. Suportados: "
                    + ", ".join(sorted(SUPPORTED_STEPS))
                    + "."
                )
            options = item.get("options")
            steps.append({"kind": kind, "options": dict(options) if isinstance(options, dict) else {}})
        if not steps:
            raise ValueError("Informe ao menos um passo do fluxo.")
        opts.steps = steps
        return opts


@dataclass
class BatchResult:
    file: Path
    processed: int = 0
    warnings: list[str] = field(default_factory=list)
    preview: str = ""


def _extract_zip(path: Path, dest: Path) -> list[Path]:
    """Valida e extrai um ZIP de entrada (anti travessia/bomba).

    Tudo lido direto do arquivo: o ZIP nunca é carregado inteiro na RAM.
    """
    try:
        validate_zip_file(path)
    except Exception as exc:  # HTTPException do validador vira erro amigável
        detail = getattr(exc, "detail", None) or str(exc)
        raise ValueError(f"ZIP inválido: {detail}") from exc

    dest.mkdir(parents=True, exist_ok=True)
    extracted: list[Path] = []
    with zipfile.ZipFile(path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            ext = Path(info.filename).suffix.lower()
            if ext not in INNER_EXTS:
                continue
            target = dest / sanitize_filename(Path(info.filename).name)
            with zf.open(info) as entry, target.open("wb") as out:
                shutil.copyfileobj(entry, out)  # extração em streaming
            extracted.append(target)
    return sorted(extracted)


def _apply_one(kind: str, options: dict, src: Path, workdir: Path, progress) -> list[Path] | None:
    """Roda um passo em um arquivo. Devolve None quando incompatível."""
    workdir.mkdir(parents=True, exist_ok=True)
    ext = src.suffix.lower()
    pdf_like = ext == ".pdf"
    raster = ext in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}

    if kind == "ocr":
        if not raster:
            return None
        from app.services.ocr import OcrOptions, ocr_document

        result = ocr_document(src, workdir, OcrOptions.from_dict(options), progress=progress)
        return list(result.files)
    if kind == "blind":
        if not pdf_like:
            return None
        from app.services.blind import BlindOptions, blind_pdf

        return [blind_pdf(src, workdir, BlindOptions.from_dict(options), progress=progress).file]
    if kind == "compress":
        if not pdf_like:
            return None
        from app.services.compress import CompressOptions, compress_pdf

        return list(compress_pdf(src, workdir, CompressOptions.from_dict(options), progress=progress).files)
    if kind == "convert":
        from app.services.convert import ConvertOptions, convert_document

        return list(convert_document(src, workdir, ConvertOptions.from_dict(options), progress=progress).files)
    if kind == "redact":
        if not pdf_like:
            return None
        from app.services.redact import RedactOptions, redact_pdf

        return [redact_pdf(src, workdir, RedactOptions.from_dict(options), progress=progress).file]
    if kind == "number":
        if not pdf_like:
            return None
        from app.services.number import NumberOptions, number_pdf

        return [number_pdf(src, workdir, NumberOptions.from_dict(options), progress=progress).file]
    return None


def run_batch(
    sources: list[Path],
    workdir: Path,
    opts: BatchOptions | None = None,
    progress=None,
) -> BatchResult:
    """Aplica o fluxo em todos os arquivos (descompactando ZIPs) e zipa a saída."""
    opts = opts or BatchOptions()
    if not opts.steps:
        raise ValueError("Informe ao menos um passo do fluxo.")
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    # 1) expande as entradas (ZIP vira arquivos; o resto entra como está)
    files: list[Path] = []
    for index, src in enumerate(sources, start=1):
        if src.suffix.lower() == ".zip":
            if progress:
                progress(index - 1, len(sources), f"Abrindo {src.name}...")
            files.extend(_extract_zip(src, workdir / f"zip_{index}"))
        else:
            files.append(src)
    if not files:
        raise ValueError(
            "Nenhum arquivo utilizável no lote (ZIP vazio ou formatos não suportados)."
        )
    if len(files) > MAX_FILES:
        raise ValueError(f"Lote com arquivos demais: máximo {MAX_FILES}.")

    # 2) aplica os passos, arquivo a arquivo
    warnings: list[str] = []
    finals: list[Path] = []
    total_units = len(files) * len(opts.steps)
    done = 0

    for file_index, file in enumerate(files, start=1):
        current = [file]
        for step_index, step in enumerate(opts.steps, start=1):
            kind = step["kind"]
            if progress:
                done += 1
                progress(
                    done,
                    total_units,
                    f"{file.name}: passo {step_index} de {len(opts.steps)} ({kind})...",
                )
            nxt: list[Path] = []
            for candidate in current:
                out_dir = workdir / f"f{file_index}_s{step_index}"
                produced = _apply_one(
                    kind, step["options"], candidate, out_dir, progress
                )
                if produced is None:
                    warnings.append(f"'{kind}' ignorado para {candidate.name} (formato incompatível).")
                    nxt.append(candidate)
                else:
                    nxt.extend(p for p in produced if p.exists())
            current = nxt or [file]
        finals.extend(current)

    if not finals:
        raise ValueError("O fluxo não gerou nenhum arquivo de saída.")

    # 3) empacota tudo em um ZIP (nomes únicos)
    zip_path = workdir / "lote_processado.zip"
    used: set[str] = set()
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for position, out in enumerate(finals, start=1):
            name = sanitize_filename(out.name)
            if name in used:
                name = f"{position:02d}_{name}"
            used.add(name)
            zf.write(out, arcname=name)

    steps_label = " → ".join(s["kind"] for s in opts.steps)
    preview = (
        f"Fluxo \"{steps_label}\" aplicado em {len(finals)} arquivo(s) "
        f"de {len(files)} de entrada."
    )
    if warnings:
        preview += " Avisos: " + " ".join(sorted(set(warnings))[:6])
    return BatchResult(
        file=zip_path, processed=len(finals), warnings=warnings, preview=preview
    )
