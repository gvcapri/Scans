"""Rotas de OCR (Fase 5).

A navegação de ferramentas é guiada por um catálogo de ferramentas que a
interface lê em `GET /api/meta/tools`. Cada ferramenta expõe:

* `available` — verdadeiro quando a instância está pronta para usá-la.
* `recommended` — verdadeiro quando o _fail_close_ permite (dev) ou quando
  a ferramenta é leve o bastante para estar sempre ativa.
* `requires` — lista de dependências externas (ex.: `ghostscript`,
  `tesseract`, `libreoffice`, `celery`).

A rota `POST /ocr` consome `OcrOptions` e produz o mesmo `OcrResult` das
demais ferramentas: grava a saída cifrada no storage e registra um job com
progresso para a barra de carregamento.
"""

from __future__ import annotations

import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from app.api.deps import current_user
from app.db.models import Job, StoredFile
from app.db.session import get_db
from app.services.ocr import OcrOptions, ocr_document
from app.services.storage import get_storage

router = APIRouter(prefix="/ocr", tags=["ocr"])

_AVAILABLE = True  # substituído na factory de aplicação (see create_app)


class OcrPayload(BaseModel):
    file_id: str = Field(..., description="Arquivo de entrada (PDF, PNG, JPG, TIFF)")
    options: OcrOptions = Field(default_factory=OcrOptions, description="Opções da ferramenta")


class JobOut(BaseModel):
    id: str
    kind: str
    status: str
    progress: int
    page_current: int
    page_total: int
    message: str
    error: str | None = None
    options: dict = Field(default_factory=dict)
    input_file_ids: list[str] = Field(default_factory=list)
    output_file_ids: list[str] = Field(default_factory=list)
    preview: str | None = None
    created_at: str | None = None
    started_at: str | None = None
    finished_at: str | None = None


def _serialize(job: Job) -> dict:
    return {
        "id": job.id,
        "kind": job.kind,
        "status": job.status,
        "progress": job.progress,
        "page_current": job.page_current,
        "page_total": job.page_total,
        "message": job.message,
        "error": job.error,
        "options": job.options or {},
        "input_file_ids": job.input_file_ids or [],
        "output_file_ids": job.output_file_ids or [],
        "preview": job.preview,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "finished_at": job.finished_at.isoformat() if job.finished_at else None,
    }


@router.post("", summary="Iniciar OCR de um documento")
def run_ocr(payload: OcrPayload, db=Depends(get_db), user: current_user = Depends(current_user)):
    row = db.scalar(
        select(StoredFile).where(
            StoredFile.id == payload.file_id,
            StoredFile.user_id == user.id,
            StoredFile.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    ext = (row.ext or "").lower()
    if ext not in {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise HTTPException(status_code=400, detail=f"Formato {ext or 'desconhecido'} não suportado pelo OCR.")

    job = Job(
        user_id=user.id,
        kind="ocr",
        status="queued",
        message="Na fila",
        options=(payload.options or OcrOptions()).__dict__,
        input_file_ids=[row.id],
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    _runner().submit(job.id)
    return _serialize(job)


def _runner():
    from app.core.jobs import get_runner

    return get_runner()


def _mime_for(ext: str) -> str:
    table = {
        ".pdf": "application/pdf",
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".tif": "image/tiff",
        ".tiff": "image/tiff",
    }
    return table.get(ext, "application/octet-stream")


def _finish(job: Job, result, preview: str, user_id: str) -> None:
    job.status = "done"
    job.progress = 100
    job.page_current = result.pages
    job.page_total = result.pages
    job.message = "Concluído"
    job.preview = preview[:20000]
    job.finished_at = datetime.now(timezone.utc)
    with get_db() as db:
        job = db.get(Job, job.id)
        if job is None:
            return
        job.status = "done"
        job.progress = 100
        job.page_current = result.pages
        job.page_total = result.pages
        job.message = "Concluído"
        job.preview = preview[:20000]
        job.finished_at = datetime.now(timezone.utc)
        db.commit()
        db.refresh(job)

        storage = get_storage()
        for path in result.files:
            ext = path.suffix
            file_id = uuid.uuid4().hex
            meta = storage.save_path(user_id, path, file_id, ext)
            out = StoredFile(
                id=file_id,
                user_id=user_id,
                original_name=f"{path.stem}{ext}",
                mime=_mime_for(ext),
                ext=ext,
                size=meta.size,
                sha256=meta.sha256,
                role="output",
                job_id=job.id,
            )
            db.add(out)
            job.output_file_ids.append(file_id)
        db.commit()
        db.refresh(job)
