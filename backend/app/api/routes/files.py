"""Rotas de arquivos: upload, listagem, preview, download e exclusão.

Toda rota passa por `current_user`: um usuário jamais enxerga arquivo de
outro (o storage também só acessa a pasta do próprio usuário).
"""

from __future__ import annotations

import datetime as dt
import tempfile
import urllib.parse
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from fastapi.responses import Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user, owned_or_404
from app.core.config import settings
from app.db.models import StoredFile, User
from app.db.session import get_db
from app.services.ocr import render_preview
from app.services.storage import get_storage
from app.services.validation import validate_upload

router = APIRouter(prefix="/files", tags=["arquivos"])

_READ_CHUNK = 1024 * 1024


def _serialize(row: StoredFile) -> dict:
    return {
        "id": row.id,
        "name": row.original_name,
        "mime": row.mime,
        "size": row.size,
        "sha256": row.sha256,
        "role": row.role,
        "job_id": row.job_id,
        "created_at": row.created_at.isoformat() if row.created_at else None,
    }


@router.post("", summary="Enviar arquivos")
def upload_files(
    files: list[UploadFile] = File(..., description="PDF, imagens, Word ou ZIP"),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    """Valida (magic bytes, tamanho, nome) e grava cifrado no storage."""
    max_bytes = settings.max_upload_bytes
    created: list[StoredFile] = []

    for upload in files:
        stream = upload.file
        stream.seek(0, 2)
        size = stream.tell()
        stream.seek(0)
        head = stream.read(4096)
        stream.seek(0)

        info = validate_upload(
            filename=upload.filename or "documento",
            declared_mime=upload.content_type,
            size=size,
            head=head,
            max_bytes=max_bytes,
        )

        file_id = uuid.uuid4().hex
        meta = get_storage().save_stream(user.id, stream, file_id, info.ext)

        row = StoredFile(
            id=file_id,
            user_id=user.id,
            original_name=info.safe_name,
            mime=info.mime,
            ext=meta.ext,
            size=meta.size,
            sha256=meta.sha256,
            role="input",
        )
        db.add(row)
        created.append(row)

    db.commit()
    for row in created:
        db.refresh(row)
    return [_serialize(r) for r in created]


@router.get("", summary="Listar arquivos")
def list_files(
    role: str | None = Query(None, description="input | output"),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> list[dict]:
    stmt = (
        select(StoredFile)
        .where(StoredFile.user_id == user.id, StoredFile.deleted_at.is_(None))
        .order_by(StoredFile.created_at.desc())
        .limit(limit)
    )
    if role in ("input", "output"):
        stmt = stmt.where(StoredFile.role == role)
    return [_serialize(r) for r in db.scalars(stmt)]


@router.get("/{file_id}", summary="Metadados de um arquivo")
def get_file(
    file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    row = db.get(StoredFile, file_id)
    owned_or_404(row, user)
    if row.deleted_at:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")
    return _serialize(row)


@router.get("/{file_id}/preview", summary="Pré-visualização de uma página (PNG)")
def preview_file(
    file_id: str,
    page: int = Query(0, ge=0, description="Índice da página (0-based)"),
    dpi: int = Query(110, ge=50, le=200),
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> Response:
    row = db.get(StoredFile, file_id)
    owned_or_404(row, user)
    if row.deleted_at:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    storage = get_storage()
    with tempfile.TemporaryDirectory(prefix="lexscan-prev-") as tmp:
        path = storage.materialize(
            user.id, file_id, Path(tmp), display_name=row.original_name
        )
        try:
            png = render_preview(path, page_index=page, dpi=dpi)
        except Exception:
            raise HTTPException(status_code=400, detail="Não foi possível renderizar.")
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "private, max-age=300"},
    )


@router.get("/{file_id}/download", summary="Baixar arquivo (descriptografado)")
def download_file(
    file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> StreamingResponse:
    row = db.get(StoredFile, file_id)
    owned_or_404(row, user)
    if row.deleted_at:
        raise HTTPException(status_code=404, detail="Arquivo não encontrado.")

    filename = row.original_name or "documento"
    quoted = urllib.parse.quote(filename, safe="")
    headers = {
        "Content-Disposition": f"attachment; filename*=UTF-8''{quoted}",
        "Content-Length": str(row.size),
        "X-Content-Type-Options": "nosniff",
        "Cache-Control": "private, no-store",
    }
    return StreamingResponse(
        get_storage().decrypt_iter(user.id, file_id),
        media_type=row.mime or "application/octet-stream",
        headers=headers,
    )


@router.delete("/{file_id}", summary="Apagar agora (LGPD)")
def delete_file(
    file_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    """Remoção imediata do arquivo cifrado — direito de eliminação (LGPD)."""
    row = db.get(StoredFile, file_id)
    owned_or_404(row, user)
    if not row.deleted_at:
        get_storage().delete(user.id, file_id)
        row.deleted_at = dt.datetime.now(dt.timezone.utc)
        db.commit()
    return {"ok": True, "id": file_id}
