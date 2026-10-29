"""Tarefas Celery (usadas quando TASK_BACKEND=celery, ou seja, no Docker).

Mantidas em um módulo separado para que o dev local não precise instalar
celery/redis — o import acontece só quando a fila é realmente usada.
"""

from __future__ import annotations

from app.core.config import settings

try:  # import opcional: localmente não instalamos celery/redis
    from celery import Celery

    celery_app = Celery(
        "lexscan",
        broker=settings.celery_broker_url,
        backend=settings.celery_broker_url,
    )
    celery_app.conf.update(
        task_serializer="json",
        result_serializer="json",
        accept_content=["json"],
        task_acks_late=True,
        worker_prefetch_multiplier=1,
        broker_connection_retry_on_startup=True,
    )

    @celery_app.task(name="lexscan.run_job", bind=True)
    def run_job_task(self, job_id: str) -> str:
        from app.core.jobs import run_job_guarded

        run_job_guarded(job_id)
        return job_id

except ImportError:  # modo local: não há Celery instalado
    celery_app = None
    run_job_task = None  # type: ignore[assignment]
