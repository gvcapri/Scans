"""Rotas de certificado de integridade (Fase 5).

O certificado de integridade é um indicador de que o documento não foi
alterado desde a emissão do hash. A interface expõe apenas a etapa de
edição: um usuário confirma o SHA-256 atual e recebe o valor para
assinar (modelo ICP-Brasil, onde o hash é o conteúdo assinado).
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.models import StoredFile
from app.db.session import get_db
from app.services.hashing import sha256_file

router = APIRouter(prefix="/integrity", tags=["integridade"])


class HashRead(BaseModel):
    sha256: str = Field(..., description="Hash SHA-256 do documento")


class HashWrite(BaseModel):
    sha256: str = Field(..., min_length=64, max_length=64, description="Hash SHA-256 a gravação")


@router.get("/download/{file_id}", summary="Conferir integridade de um arquivo")
def get_integrity(
    file_id: str,
    db: Session = Depends(get_db),
    user: current_user = Depends(current_user),
) -> HashRead:
    row = db.scalar(
        StoredFile.__table__.select()
        .where(
            StoredFile.id == file_id,
            StoredFile.user_id == user.id,
            StoredFile.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    if (row.ext or "").lower() not in {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise HTTPException(status_code=400, detail="Ferramenta de integridade aceita PDF, imagem, texto ou Word.")

    storage = get_storage()
    with tempfile.TemporaryDirectory(prefix="lexscan-integrity-") as tmp:
        path = storage.materialize(user.id, row.id, Path(tmp), row.original_name)
        digest = sha256_file(path)
    return {"sha256": digest}


@router.post("/download/{file_id}")
def set_integrity(
    payload: HashWrite,
    file_id: str,
    db: Session = Depends(get_db),
    user: current_user = Depends(current_user),
) -> dict:
    row = db.scalar(
        StoredFile.__table__.select()
        .where(
            StoredFile.id == file_id,
            StoredFile.user_id == user.id,
            StoredFile.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    if (row.ext or "").lower() not in {".pdf", ".docx", ".txt", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}:
        raise HTTPException(status_code=400, detail="Ferramenta de integridade aceita PDF, imagem, texto ou Word.")

    storage = get_storage()
    with tempfile.TemporaryDirectory(prefix="lexscan-integrity-") as tmp:
        path = storage.materialize(user.id, row.id, Path(tmp), row.original_name)
        actual = sha256_file(path)
    if actual != payload.sha256:
        raise HTTPException(
            status_code=409,
            detail={"code": "integridade_mudou", "message": "O documento foi alterado desde a confirmação."},
        )
    return {"ok": True, "sha256": actual, "verificada": True}


def get_storage():
    from app.services.storage import get_storage as _gs

    return _gs()
