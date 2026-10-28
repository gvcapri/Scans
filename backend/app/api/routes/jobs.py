"""Rotas de jobs: criação, acompanhamento e histórico de processamentos."""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.core.jobs import get_runner
from app.db.models import Job, StoredFile, User
from app.db.session import get_db

router = APIRouter(prefix="/jobs", tags=["jobs"])

# Ferramentas suportadas e as regras de entrada de cada uma.
#   min/max: quantidade de arquivos por job
#   exts:    extensões aceitas (validadas contra o arquivo real, não só o MIME)
KIND_RULES: dict[str, dict] = {
    "ocr": {"min": 1, "max": 1, "exts": {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}},
    "blind": {"min": 1, "max": 1, "exts": {".pdf"}},
    "merge": {"min": 2, "max": 50, "exts": {".pdf"}},
    "split": {"min": 1, "max": 1, "exts": {".pdf"}},
    "convert": {
        "min": 1,
        "max": 1,
        "exts": {
            ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp",
            ".doc", ".docx", ".odt", ".rtf", ".docm",
        },
    },
    "compress": {"min": 1, "max": 1, "exts": {".pdf"}},
    "redact": {"min": 1, "max": 1, "exts": {".pdf"}},
    "number": {"min": 1, "max": 1, "exts": {".pdf"}},
    "outline": {"min": 1, "max": 1, "exts": {".pdf"}},
    "metadata": {"min": 1, "max": 1, "exts": {".pdf"}},
    "integrity": {
        "min": 1,
        "max": 20,
        "exts": {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".docx", ".txt"},
    },
}
ALLOWED_KINDS = set(KIND_RULES)


class JobCreate(BaseModel):
    """Payload de criação de job."""

    kind: str = Field(
        ...,
        description=(
            "ocr | blind | merge | split | convert | compress | redact | "
            "number | outline | metadata | integrity"
        ),
    )
    file_ids: list[str] = Field(..., min_length=1, description="Arquivos de entrada")
    options: dict = Field(default_factory=dict, description="Opções da ferramenta")


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


@router.post("", summary="Criar job (OCR, Blindado...)")
def create_job(
    payload: JobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    if payload.kind not in ALLOWED_KINDS:
        raise HTTPException(status_code=400, detail="Ferramenta não suportada.")

    rule = KIND_RULES[payload.kind]
    count = len(payload.file_ids)
    if count < rule["min"] or count > rule["max"]:
        if rule["min"] == rule["max"]:
            raise HTTPException(
                status_code=400,
                detail=f"Esta ferramenta recebe exatamente {rule['min']} arquivo por vez.",
            )
        raise HTTPException(
            status_code=400,
            detail=(
                f"Esta ferramenta recebe de {rule['min']} a {rule['max']} arquivos."
            ),
        )

    # Todos os arquivos precisam existir e pertencer ao usuário atual.
    rows = db.scalars(
        select(StoredFile).where(
            StoredFile.id.in_(payload.file_ids),
            StoredFile.user_id == user.id,
            StoredFile.deleted_at.is_(None),
        )
    ).all()
    by_id = {r.id: r for r in rows}
    if len(by_id) != len(set(payload.file_ids)):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    allowed_exts: set[str] = rule["exts"]
    for file_id in payload.file_ids:
        ext = (by_id[file_id].ext or "").lower()
        if ext not in allowed_exts:
            raise HTTPException(
                status_code=400,
                detail=(
                    f"'{by_id[file_id].original_name}' não é compatível com "
                    f"a ferramenta {payload.kind}."
                ),
            )

    job = Job(
        user_id=user.id,
        kind=payload.kind,
        status="queued",
        message="Na fila",
        options=payload.options or {},
        input_file_ids=list(payload.file_ids),
    )
    db.add(job)
    db.commit()
    db.refresh(job)

    get_runner().submit(job.id)  # dispara depois do commit
    return _serialize(job)


@router.get("", summary="Histórico de jobs")
def list_jobs(
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    stmt = (
        select(Job)
        .where(Job.user_id == user.id)
        .order_by(Job.created_at.desc())
        .limit(limit)
    )
    return [_serialize(j) for j in db.scalars(stmt)]


@router.get("/{job_id}", summary="Acompanhar job (progresso/preview)")
def get_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    return _serialize(job)


@router.delete("/{job_id}", summary="Remover job do histórico")
def delete_job(
    job_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    job = db.get(Job, job_id)
    if job is None or job.user_id != user.id:
        raise HTTPException(status_code=404, detail="Job não encontrado.")
    if job.status in ("queued", "running"):
        raise HTTPException(
            status_code=409, detail="Job em andamento: aguarde concluir."
        )
    # apaga também as saídas do job
    storage = __import__("app.services.storage", fromlist=["get_storage"]).get_storage()
    for file_id in job.output_file_ids or []:
        storage.delete(user.id, file_id)
        row = db.get(StoredFile, file_id)
        if row:
            row.deleted_at = dt.datetime.now(dt.timezone.utc)
    db.delete(job)
    db.commit()
    return {"ok": True, "id": job_id}
