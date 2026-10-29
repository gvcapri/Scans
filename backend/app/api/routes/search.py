"""Busca full-text no acervo (Fase 4).

`GET /api/search?q=...` varre o texto dos documentos **do usuário** e
devolve o trecho onde a ocorrência aparece, já com `<mark>`/`</mark>` em
volta — o front só precisa imprimir o HTML do snippet.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, HTTPException
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.models import StoredFile, User
from app.core.features import is_feature_enabled
from app.db.search import search as run_search
from app.db.session import engine, get_db

router = APIRouter(prefix="/search", tags=["busca"])


@router.get("", summary="Buscar no acervo (full-text com destaque)")
def search(
    q: str = Query(..., min_length=1, max_length=200, description="Termos buscados"),
    limit: int = Query(20, ge=1, le=50),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    if not is_feature_enabled("search"):
        raise HTTPException(
            status_code=503,
            detail={"code": "feature_disabled", "message": "Recurso temporariamente indisponível"},
        )
    hits, total = run_search(q, user.id, engine, limit=limit)

    # metadados do arquivo (nome, tamanho, data) — somente os do usuário
    rows: dict[str, StoredFile] = {}
    if hits:
        from sqlalchemy import select

        ids = [h.file_id for h in hits]
        for row in db.scalars(
            select(StoredFile).where(
                StoredFile.id.in_(ids),
                StoredFile.user_id == user.id,
                StoredFile.deleted_at.is_(None),
            )
        ):
            rows[row.id] = row

    return {
        "query": q,
        "total": total,
        "results": [
            {
                "file_id": h.file_id,
                "name": h.name,
                "snippet": h.snippet,
                "score": round(h.score, 3),
                "size": rows[h.file_id].size if h.file_id in rows else None,
                "mime": rows[h.file_id].mime if h.file_id in rows else None,
                "created_at": (
                    rows[h.file_id].created_at.isoformat()
                    if h.file_id in rows and rows[h.file_id].created_at
                    else None
                ),
            }
            for h in hits
            if h.file_id in rows
        ],
    }
