"""Expurgo automático (LGPD) — Fase 5.

Arquivos com mais de `RETENTION_HOURS` (padrão 24 h) saem do disco, do
banco e do índice de busca; jobs encerrados da mesma idade também, porque
o `preview` de um job guarda trechos do conteúdo. Roda no startup e em
segundo plano a cada `PURGE_INTERVAL_MINUTES`.

O "Apagar agora" (rota DELETE /files/{id}) continua sendo a exclusão
imediata — este módulo é só o derrame automático.
"""

from __future__ import annotations

import datetime as dt
import logging

from sqlalchemy import select

from app.core.config import settings
from app.db.models import Job, StoredFile
from app.db.session import session_scope
from app.services.indexing import drop_from_index

log = logging.getLogger("lexscan.retention")


def purge_expired(
    retention_hours: int | None = None,
    now: dt.datetime | None = None,
) -> dict:
    """Apaga o que passou da retenção. Devolve quantos registros saíram."""
    hours = settings.retention_hours if retention_hours is None else retention_hours
    now = now or dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(hours=hours)

    removed_files = 0
    removed_jobs = 0

    with session_scope() as db:
        stale = db.scalars(
            select(StoredFile).where(
                StoredFile.deleted_at.is_(None),
                StoredFile.created_at < cutoff,
            )
        ).all()

        for row in stale:
            try:
                from app.services.storage import get_storage

                get_storage().delete(row.user_id, row.id)
            except Exception:
                log.warning("Falha ao apagar bytes de %s", row.id, exc_info=True)
            try:
                drop_from_index(row.id)
            except Exception:
                log.debug("Índice já não tinha %s", row.id, exc_info=True)
            db.delete(row)  # sumário de verdade: some também do banco
            removed_files += 1

        old_jobs = db.scalars(
            select(Job).where(
                Job.created_at < cutoff,
                Job.status.in_(["done", "error"]),
            )
        ).all()
        dead_ids = {job.id for job in old_jobs}
        if dead_ids:
            # arquivos vivos não podem apontar para job apagado
            survivors = db.scalars(
                select(StoredFile).where(StoredFile.job_id.in_(dead_ids))
            ).all()
            for row in survivors:
                row.job_id = None
            for job in old_jobs:
                db.delete(job)
                removed_jobs += 1

    if removed_files or removed_jobs:
        log.info(
            "Expurgo LGPD: %d arquivo(s) e %d job(s) além de %dh removidos",
            removed_files,
            removed_jobs,
            hours,
        )
    return {"files": removed_files, "jobs": removed_jobs}
