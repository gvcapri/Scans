"""Rotas de comparação lado a lado (Fase 4).

A navegação de ferramentas é guiada por um catálogo de ferramentas que a
interface lê em `GET /api/meta/tools`. Cada ferramenta expõe:

* `available` — verdadeiro quando a instância está pronta para usá-la.
* `recommended` — verdadeiro quando o _fail_close_ permite (dev) ou quando
  a ferramenta é leve o bastante para estar sempre ativa.
* `requires` — lista de dependências externas (ex.: `ghostscript`,
  `tesseract`, `libreoffice`, `celery`).

O comparador diferencia **texto** de **pixel**: a interface pede duas
versões e recebe um diff `replace/delete/insert/equal` por página, que ela
desenha em duas colunas. O `progress` reporta pagina a pagina.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.api.deps import current_user
from app.db.models import Job, StoredFile
from app.db.session import get_db
from app.services.compare import CompareOptions, compare_documents
from app.services.storage import get_storage

router = APIRouter(prefix="/compare", tags=["compare"])

_AVAILABLE = True  # substituído na factory de aplicação (see create_app)


class ComparePayload(BaseModel):
    file_a: str = Field(..., description="ID do primeiro arquivo PDF")
    file_b: str = Field(..., description="ID do segundo arquivo PDF")
    options: dict = Field(default_factory=dict, description="Opções do comparador")


class CompareOut(BaseModel):
    file_a: dict
    file_b: dict
    summary: dict
    pages: list[dict]


def _job_field(row, key):
    return getattr(row, key).isoformat() if getattr(row, key) else None


@router.post("", summary="Comparar duas versões de um documento")
def run_compare(
    payload: ComparePayload,
    db=Depends(get_db),
    user: current_user = Depends(current_user),
) -> CompareOut:
    rows = db.scalars(
        select(StoredFile).where(
            StoredFile.id.in_([payload.file_a, payload.file_b]),
            StoredFile.user_id == user.id,
            StoredFile.deleted_at.is_(None),
        )
    ).all()
    by_id = {r.id: r for r in rows}
    for fid in (payload.file_a, payload.file_b):
        if fid not in by_id:
            raise HTTPException(status_code=404, detail=f"Arquivo {fid} não encontrado.")
    if len(by_id) != 2:
        raise HTTPException(status_code=400, detail="Ambos os arquivos precisam ser diferentes.")

    a, b = by_id[payload.file_a], by_id[payload.file_b]
    if a.id == b.id:
        raise HTTPException(status_code=400, detail="Os dois arquivos devem ser diferentes.")

    if (a.ext or "").lower() != ".pdf" or (b.ext or "").lower() != ".pdf":
        raise HTTPException(status_code=400, detail="A comparação aceita apenas PDF.")

    opts = CompareOptions.from_dict(payload.options or {})

    storage = get_storage()
    with tempfile.TemporaryDirectory(prefix="lexscan-compare-") as tmp:
        path_a = storage.materialize(user.id, a.id, Path(tmp), a.original_name)
        path_b = storage.materialize(user.id, b.id, Path(tmp), b.original_name)

        result = compare_documents(path_a, path_b, opts, progress=_progress)

    return CompareOut(
        file_a=_meta(a),
        file_b=_meta(b),
        summary=result.summary,
        pages=result.pages,
    )


def _progress(page, total, message):
    pass


def _meta(row: StoredFile) -> dict:
    return {
        "id": row.id,
        "name": row.original_name,
        "size": row.size,
        "mime": row.mime,
        "created_at": _job_field(row, "created_at"),
    }
