"""Comparador de versões lado a lado (Fase 4).

Endpoint síncrono (a comparação de texto é rápida): aceita dois PDFs do
usuário e devolve o diff estruturado página a página — a interface só
desenha as duas colunas.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.models import StoredFile, User
from app.db.session import get_db
from app.services.compare import CompareOptions, compare_documents
from app.services.storage import get_storage

router = APIRouter(prefix="/compare", tags=["comparador"])


class CompareRequest(BaseModel):
    """Payload da comparação."""

    file_a: str = Field(..., description="Versão original (esquerda)")
    file_b: str = Field(..., description="Versão alterada (direita)")
    options: dict = Field(default_factory=dict, description="Opções do comparador")


def _load(db: Session, user: User, file_id: str, side: str) -> StoredFile:
    row = db.scalar(
        select(StoredFile).where(
            StoredFile.id == file_id,
            StoredFile.user_id == user.id,
            StoredFile.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail=f"Arquivo {side} não encontrado.")
    if (row.ext or "").lower() != ".pdf":
        raise HTTPException(
            status_code=400, detail=f"O comparador aceita PDF ({side})."
        )
    return row


@router.post("", summary="Comparar duas versões (lado a lado)")
def compare(
    payload: CompareRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    if payload.file_a == payload.file_b:
        raise HTTPException(
            status_code=400, detail="Escolha duas versões diferentes do documento."
        )
    row_a = _load(db, user, payload.file_a, "original")
    row_b = _load(db, user, payload.file_b, "alterado")

    opts = CompareOptions.from_dict(payload.options)
    storage = get_storage()
    with tempfile.TemporaryDirectory(prefix="lexscan-compare-") as tmp:
        path_a = storage.materialize(user.id, row_a.id, Path(tmp), row_a.original_name)
        path_b = storage.materialize(user.id, row_b.id, Path(tmp), row_b.original_name)
        try:
            result = compare_documents(path_a, path_b, opts)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    return {
        "file_a": {"id": row_a.id, "name": row_a.original_name, "pages": result.pages_a},
        "file_b": {"id": row_b.id, "name": row_b.original_name, "pages": result.pages_b},
        "summary": result.summary,
        "pages": result.pages,
    }
