"""Revisão manual antes de redigir: localiza dados sensíveis no PDF (Fase 3).

A interface chama `POST /api/redact/scan` antes de criar o job, mostra os
achados agrupados por tipo e deixa o usuário marcar o que tarjar — os
valores aprovados voltam em `options.terms` na criação do job.
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
from app.services.redact import PATTERN_BY_ID, detect_sensitive
from app.services.storage import get_storage

router = APIRouter(prefix="/redact", tags=["redact"])


class ScanRequest(BaseModel):
    """Payload da varredura de revisão."""

    file_id: str = Field(..., description="Arquivo PDF a varrer")
    types: list[str] | None = Field(
        default=None, description="Tipos a procurar (padrão: todos)"
    )


@router.post("/scan", summary="Localizar dados sensíveis (revisão manual)")
def scan(
    payload: ScanRequest,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    row = db.scalar(
        select(StoredFile).where(
            StoredFile.id == payload.file_id,
            StoredFile.user_id == user.id,
            StoredFile.deleted_at.is_(None),
        )
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    if (row.ext or "").lower() != ".pdf":
        raise HTTPException(
            status_code=400, detail="A revisão de dados funciona em PDF."
        )

    wanted = [t for t in (payload.types or []) if t in PATTERN_BY_ID] or None
    with tempfile.TemporaryDirectory(prefix="lexscan-scan-") as tmp:
        path = get_storage().materialize(user.id, row.id, Path(tmp), row.original_name)
        result = detect_sensitive(path, wanted)

    return {
        "file_id": row.id,
        "page_count": result.page_count,
        "has_text_layer": result.has_text_layer,
        "total": result.total,
        "groups": [
            {
                "type": g.type,
                "label": g.label,
                "value": g.value,
                "count": g.count,
                "pages": [p + 1 for p in g.pages],
            }
            for g in result.groups
        ],
        "warning": (
            None
            if result.has_text_layer
            else "O PDF não tem camada de texto (é imagem): execute o OCR antes "
            "de redigir, senão nada será localizado."
        ),
    }
