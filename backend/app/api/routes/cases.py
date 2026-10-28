"""Pastas de processo/cliente e histórico de operações (Fase 4).

Uma pasta agrupa arquivos de um mesmo processo (ou cliente) e mostra o
histórico das operações que passaram por eles. Ponto importante de LGPD:

* **mover arquivo para pasta** muda só o `case_folder_id` (nenhum byte é
  copiado);
* **apagar pasta** apenas desvincula os arquivos — eles continuam no
  storage cifrado até o usuário apagá-los (ou o expurgo de 24 h).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.models import CaseFolder, Job, StoredFile, User
from app.db.session import get_db

router = APIRouter(prefix="/cases", tags=["pastas"])

MAX_PER_USER = 100


def _serialize_file(row: StoredFile) -> dict:
    return {
        "id": row.id,
        "name": row.original_name,
        "mime": row.mime,
        "size": row.size,
        "role": row.role,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


def _serialize(folder: CaseFolder, file_count: int = 0) -> dict:
    return {
        "id": folder.id,
        "name": folder.name,
        "process_number": folder.process_number or "",
        "file_count": file_count,
        "created_at": folder.created_at.isoformat() if folder.created_at else None,
    }


class CaseCreate(BaseModel):
    """Payload de criação de pasta."""

    name: str = Field(..., min_length=1, max_length=255, description="Nome da pasta")
    process_number: str = Field("", max_length=32, description="Número do processo (opcional)")


class CaseUpdate(BaseModel):
    """Payload de renomeação de pasta."""

    name: str | None = Field(None, min_length=1, max_length=255)
    process_number: str | None = Field(None, max_length=32)


class CaseFiles(BaseModel):
    """Payload de vínculo de arquivos à pasta."""

    file_ids: list[str] = Field(..., min_length=1, max_length=100)


@router.get("", summary="Listar pastas de processo")
def list_cases(
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    folders = db.scalars(
        select(CaseFolder)
        .where(CaseFolder.user_id == user.id)
        .order_by(CaseFolder.created_at.desc())
    ).all()
    counts: dict[str, int] = {}
    if folders:
        rows = db.scalars(
            select(StoredFile).where(
                StoredFile.user_id == user.id,
                StoredFile.deleted_at.is_(None),
                StoredFile.case_folder_id.in_([f.id for f in folders]),
            )
        ).all()
        for row in rows:
            counts[row.case_folder_id or ""] = counts.get(row.case_folder_id or "", 0) + 1
    return [_serialize(f, counts.get(f.id, 0)) for f in folders]


@router.post("", summary="Criar pasta de processo")
def create_case(
    payload: CaseCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Informe um nome para a pasta.")
    existing = len(
        db.scalars(select(CaseFolder).where(CaseFolder.user_id == user.id)).all()
    )
    if existing >= MAX_PER_USER:
        raise HTTPException(
            status_code=400, detail=f"Limite de {MAX_PER_USER} pastas atingido."
        )
    folder = CaseFolder(
        user_id=user.id,
        name=name[:255],
        process_number=(payload.process_number or "").strip()[:32] or None,
    )
    db.add(folder)
    db.commit()
    db.refresh(folder)
    return _serialize(folder)


@router.get("/{case_id}", summary="Detalhe da pasta (arquivos + operações)")
def get_case(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    folder = db.get(CaseFolder, case_id)
    if folder is None or folder.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pasta não encontrada.")

    files = db.scalars(
        select(StoredFile)
        .where(
            StoredFile.user_id == user.id,
            StoredFile.case_folder_id == case_id,
            StoredFile.deleted_at.is_(None),
        )
        .order_by(StoredFile.created_at.desc())
    ).all()
    file_ids = {f.id for f in files}

    # histórico: jobs que tiveram entrada/saída nesta pasta (ordem recente)
    operations: list[dict] = []
    jobs = db.scalars(
        select(Job)
        .where(Job.user_id == user.id)
        .order_by(Job.created_at.desc())
        .limit(200)
    ).all()
    for job in jobs:
        touched = set(job.input_file_ids or []) | set(job.output_file_ids or [])
        if touched & file_ids:
            operations.append(
                {
                    "id": job.id,
                    "kind": job.kind,
                    "status": job.status,
                    "message": job.message,
                    "created_at": job.created_at.isoformat() if job.created_at else None,
                    "finished_at": job.finished_at.isoformat() if job.finished_at else None,
                    "files": len(touched & file_ids),
                }
            )

    return {
        **_serialize(folder, len(files)),
        "files": [_serialize_file(f) for f in files],
        "operations": operations[:50],
    }


@router.patch("/{case_id}", summary="Renomear pasta")
def update_case(
    case_id: str,
    payload: CaseUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    folder = db.get(CaseFolder, case_id)
    if folder is None or folder.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pasta não encontrada.")
    if payload.name is not None:
        name = payload.name.strip()
        if not name:
            raise HTTPException(status_code=400, detail="O nome não pode ficar vazio.")
        folder.name = name[:255]
    if payload.process_number is not None:
        folder.process_number = payload.process_number.strip()[:32] or None
    db.commit()
    db.refresh(folder)
    counts = len(
        db.scalars(
            select(StoredFile).where(
                StoredFile.user_id == user.id,
                StoredFile.case_folder_id == case_id,
                StoredFile.deleted_at.is_(None),
            )
        ).all()
    )
    return _serialize(folder, counts)


@router.delete("/{case_id}", summary="Apagar pasta (arquivos ficam no acervo)")
def delete_case(
    case_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    folder = db.get(CaseFolder, case_id)
    if folder is None or folder.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pasta não encontrada.")
    files = db.scalars(
        select(StoredFile).where(
            StoredFile.user_id == user.id, StoredFile.case_folder_id == case_id
        )
    ).all()
    for row in files:
        row.case_folder_id = None
    db.delete(folder)
    db.commit()
    return {"ok": True, "id": case_id, "unlinked": len(files)}


@router.post("/{case_id}/files", summary="Mover arquivos para a pasta")
def add_files(
    case_id: str,
    payload: CaseFiles,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    folder = db.get(CaseFolder, case_id)
    if folder is None or folder.user_id != user.id:
        raise HTTPException(status_code=404, detail="Pasta não encontrada.")
    rows = db.scalars(
        select(StoredFile).where(
            StoredFile.id.in_(payload.file_ids),
            StoredFile.user_id == user.id,
            StoredFile.deleted_at.is_(None),
        )
    ).all()
    if len(rows) != len(set(payload.file_ids)):
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    for row in rows:
        row.case_folder_id = case_id
    db.commit()
    return {"ok": True, "moved": len(rows), "case_id": case_id}


@router.delete("/{case_id}/files/{file_id}", summary="Retirar arquivo da pasta")
def remove_file(
    case_id: str,
    file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    row = db.get(StoredFile, file_id)
    if row is None or row.user_id != user.id:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    if row.case_folder_id == case_id:
        row.case_folder_id = None
        db.commit()
    return {"ok": True, "id": file_id}
