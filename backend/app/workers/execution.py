"""Execução dos jobs: carrega, despacha por `kind`, reporta progresso.

Regras importantes:
* Nenhuma sessão de banco fica aberta durante o processamento — apenas
  sessões curtas para cada atualização de progresso (evita travar o SQLite
  e mantém a UI responsiva).
* Os arquivos de entrada são materializados (descriptografados) numa pasta
  temporária do sistema, apagada ao final — o conteúdo nunca fica em claro
  no diretório do projeto.
"""

from __future__ import annotations

import datetime as dt
import logging
import shutil
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from sqlalchemy import select

from app.db.models import Job, StoredFile
from app.db.session import session_scope
from app.services.storage import get_storage

log = logging.getLogger("lexscan.worker")


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


@dataclass
class JobResult:
    """O que um handler devolve ao worker."""

    files: list[Path] = field(default_factory=list)
    preview: str = ""
    message: str = "Concluído"


class JobContext:
    """Contexto entregue ao handler: entradas, progresso e saídas."""

    def __init__(self, job: "_JobSnapshot", workdir: Path):
        self.job = job
        self.job_id = job.id
        self.user_id = job.user_id
        self.kind = job.kind
        self.options = job.options
        self.workdir = workdir
        self.inputs: list[Path] = []
        self.output_ids: list[str] = []
        self._last_progress_write = 0.0

    # ------------------------------------------------------------ progresso
    def progress(self, page: int, total: int, message: str) -> None:
        """Atualiza a barra de progresso (com throttle de 250 ms)."""
        now = time.monotonic()
        pct = int((page / total) * 100) if total else 0
        if now - self._last_progress_write < 0.25 and pct < 100:
            return
        self._last_progress_write = now
        try:
            with session_scope() as db:
                job = db.get(Job, self.job_id)
                if job is None:
                    return
                job.page_current = page
                job.page_total = total
                job.progress = max(0, min(99, pct))
                job.message = message[:255]
        except Exception:  # progresso é best-effort
            log.debug("Não foi possível gravar o progresso", exc_info=True)

    # --------------------------------------------------------------- saídas
    def store_output(self, path: Path, name: str | None = None) -> str:
        """Cifra um arquivo gerado no storage e registra no banco."""
        file_id = __import__("uuid").uuid4().hex
        meta = get_storage().save_path(self.user_id, path, file_id, path.suffix)
        with session_scope() as db:
            row = StoredFile(
                id=file_id,
                user_id=self.user_id,
                original_name=(name or path.name)[:255],
                mime=_mime_for(path.suffix),
                ext=meta.ext,
                size=meta.size,
                sha256=meta.sha256,
                role="output",
                job_id=self.job_id,
            )
            db.add(row)
        self.output_ids.append(file_id)
        try:
            from app.services.indexing import index_stored_file

            index_stored_file(file_id, self.user_id, row.original_name, path)
        except Exception:
            log.debug("Não foi possível indexar a saída do job", exc_info=True)
        return file_id

    # -------------------------------------------------------------- entradas
    def materialize_inputs(self) -> list[Path]:
        """Descriptografa as entradas para a pasta temporária do job."""
        storage = get_storage()
        paths: list[Path] = []
        names: dict[str, str] = {}
        if self.job.input_file_ids:
            with session_scope() as db:
                rows = db.scalars(
                    select(StoredFile).where(StoredFile.id.in_(self.job.input_file_ids))
                ).all()
                names = {r.id: r.original_name for r in rows}
        for file_id in self.job.input_file_ids:
            paths.append(
                storage.materialize(
                    self.user_id, file_id, self.workdir, names.get(file_id)
                )
            )
        self.inputs = paths
        return paths


def _mime_for(ext: str) -> str:
    return {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
        ".txt": "text/plain",
        ".docx": "application/vnd.openxmlformats-officedocument."
        "wordprocessingml.document",
        ".zip": "application/zip",
    }.get(ext.lower(), "application/octet-stream")


@dataclass
class _JobSnapshot:
    id: str
    user_id: str
    kind: str
    options: dict
    input_file_ids: list[str]


# --------------------------------------------------------------------------
# Handlers por ferramenta (Fase 1: ocr e blind)
# --------------------------------------------------------------------------
def _handle_ocr(ctx: JobContext) -> JobResult:
    from app.services.ocr import OcrOptions, ocr_document

    opts = OcrOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) != 1:
        raise ValueError("O OCR processa um arquivo por vez.")
    result = ocr_document(inputs[0], ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=result.files,
        preview=result.preview,
        message=f"{result.pages} página(s) processada(s)",
    )


def _handle_blind(ctx: JobContext) -> JobResult:
    from app.services.blind import BlindOptions, blind_pdf

    opts = BlindOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) != 1:
        raise ValueError("A blindagem processa um arquivo por vez.")
    result = blind_pdf(inputs[0], ctx.workdir, opts, progress=ctx.progress)
    extra = " com camada pesquisável" if result.has_text_layer else ""
    return JobResult(
        files=[result.file],
        preview=f"PDF blindado{extra}: {result.pages} página(s), "
        f"{result.size // 1024} KB. Texto selecionável, formulários, scripts "
        f"e metadados removidos.",
        message=f"{result.pages} página(s) blindada(s)",
    )


def _handle_merge(ctx: JobContext) -> JobResult:
    from app.services.merge import MergeOptions, merge_pdfs

    opts = MergeOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) < 2:
        raise ValueError("A mesclagem precisa de pelo menos dois arquivos.")
    result = merge_pdfs(inputs, ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=[result.file],
        preview=result.preview,
        message=f"{result.parts} arquivo(s) mesclado(s)",
    )


def _handle_split(ctx: JobContext) -> JobResult:
    from app.services.split import SplitOptions, split_pdf

    opts = SplitOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) != 1:
        raise ValueError("A divisão processa um arquivo por vez.")
    result = split_pdf(inputs[0], ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=result.files,
        preview=result.preview,
        message=f"{len(result.files)} arquivo(s) gerado(s)",
    )


def _handle_convert(ctx: JobContext) -> JobResult:
    from app.services.convert import ConvertOptions, convert_document

    opts = ConvertOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) != 1:
        raise ValueError("A conversão processa um arquivo por vez.")
    result = convert_document(inputs[0], ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=result.files,
        preview=result.preview,
        message=f"{len(result.files)} arquivo(s) gerado(s)",
    )


def _handle_compress(ctx: JobContext) -> JobResult:
    from app.services.compress import CompressOptions, compress_pdf

    opts = CompressOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) != 1:
        raise ValueError("A compressão processa um arquivo por vez.")
    result = compress_pdf(inputs[0], ctx.workdir, opts, progress=ctx.progress)
    message = f"{result.parts} arquivo(s) gerado(s)"
    if opts.limit_mb:
        message += f" (limite {opts.limit_mb:g} MB)"
    return JobResult(files=result.files, preview=result.preview, message=message)


def _handle_redact(ctx: JobContext) -> JobResult:
    from app.services.redact import RedactOptions, redact_pdf

    opts = RedactOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) != 1:
        raise ValueError("A redação processa um arquivo por vez.")
    result = redact_pdf(inputs[0], ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=[result.file],
        preview=result.preview,
        message=f"{result.values} dado(s) redigido(s)",
    )


def _handle_number(ctx: JobContext) -> JobResult:
    from app.services.number import NumberOptions, number_pdf

    opts = NumberOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) != 1:
        raise ValueError("A numeração processa um arquivo por vez.")
    result = number_pdf(inputs[0], ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=[result.file],
        preview=result.preview,
        message=f"{result.stamped} página(s) numerada(s)",
    )


def _handle_outline(ctx: JobContext) -> JobResult:
    from app.services.outline import OutlineOptions, build_outline

    opts = OutlineOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) != 1:
        raise ValueError("O sumário processa um arquivo por vez.")
    result = build_outline(inputs[0], ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=[result.file],
        preview=result.preview,
        message=f"{result.entries} item(ns) no sumário",
    )


def _handle_metadata(ctx: JobContext) -> JobResult:
    from app.services.metadata import LegalMetaOptions, apply_legal_metadata

    opts = LegalMetaOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    if len(inputs) != 1:
        raise ValueError("Os metadados processam um arquivo por vez.")
    result = apply_legal_metadata(inputs[0], ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=[result.file],
        preview=result.preview,
        message="Metadados gravados",
    )


def _handle_integrity(ctx: JobContext) -> JobResult:
    from app.services.integrity import IntegrityOptions, build_certificate

    opts = IntegrityOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    result = build_certificate(inputs, ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=[result.file],
        preview=result.preview,
        message=f"{result.files} arquivo(s) certificado(s)",
    )


def _handle_batch(ctx: JobContext) -> JobResult:
    from app.services.batch import BatchOptions, run_batch

    opts = BatchOptions.from_dict(ctx.options)
    inputs = ctx.inputs or ctx.materialize_inputs()
    result = run_batch(inputs, ctx.workdir, opts, progress=ctx.progress)
    return JobResult(
        files=[result.file],
        preview=result.preview,
        message=f"{result.processed} arquivo(s) no lote",
    )


HANDLERS: dict[str, Callable[[JobContext], JobResult]] = {
    "ocr": _handle_ocr,
    "blind": _handle_blind,
    "merge": _handle_merge,
    "split": _handle_split,
    "convert": _handle_convert,
    "compress": _handle_compress,
    "redact": _handle_redact,
    "number": _handle_number,
    "outline": _handle_outline,
    "metadata": _handle_metadata,
    "integrity": _handle_integrity,
    "batch": _handle_batch,
}


# --------------------------------------------------------------------------
# Worker
# --------------------------------------------------------------------------
def run_job(job_id: str) -> None:
    """Executa um job do início ao fim, com progresso e saídas cifradas."""
    with session_scope() as db:
        job = db.get(Job, job_id)
        if job is None:
            log.warning("Job inexistente")
            return
        if job.status not in ("queued", "running"):
            return
        job.status = "running"
        job.started_at = _utcnow()
        job.message = "Iniciando..."
        job.progress = 0
        snapshot = _JobSnapshot(
            id=job.id,
            user_id=job.user_id,
            kind=job.kind,
            options=dict(job.options or {}),
            input_file_ids=list(job.input_file_ids or []),
        )

    handler = HANDLERS.get(snapshot.kind)
    if handler is None:
        _fail(snapshot, "Ferramenta desconhecida.")
        return

    workdir = Path(tempfile.mkdtemp(prefix="lexscan-job-"))
    try:
        ctx = JobContext(snapshot, workdir)
        ctx.inputs = ctx.materialize_inputs()
        if not ctx.inputs:
            raise ValueError("Nenhum arquivo de entrada.")
        result = handler(ctx)

        output_ids: list[str] = []
        for path in result.files:
            with session_scope() as db:
                job = db.get(Job, snapshot.id)
                job.message = "Cifrando saída..."[:255]
            output_ids.append(ctx.store_output(path))

        with session_scope() as db:
            job = db.get(Job, snapshot.id)
            job.status = "done"
            job.progress = 100
            job.page_current = job.page_total or job.page_current
            job.message = result.message[:255]
            job.preview = (result.preview or "")[:20000]
            job.output_file_ids = output_ids
            job.finished_at = _utcnow()
        log.info("Job %s concluído (%s)", job_id, snapshot.kind)
    except Exception as exc:
        # Mensagem de erro amigável; o log técnico não contém conteúdo.
        log.exception("Job %s falhou", job_id)
        _fail(snapshot, _friendly_error(exc))
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _fail(snapshot: "_JobSnapshot", message: str) -> None:
    with session_scope() as db:
        job = db.get(Job, snapshot.id)
        if job is None:
            return
        job.status = "error"
        job.message = message[:255]
        job.error = message
        job.finished_at = _utcnow()


def _friendly_error(exc: Exception) -> str:
    """Converte exceções técnicas em mensagens em pt-BR."""
    text = str(exc)
    if isinstance(exc, ValueError):
        return f"Dados inválidos: {text}"
    if "password" in text.lower() or "encrypt" in text.lower():
        return "Falha ao aplicar a proteção por senha."
    if "damaged" in text.lower() or "cannot open" in text.lower():
        return "O arquivo parece corrompido ou protegido por senha."
    return f"Falha no processamento: {type(exc).__name__}"
