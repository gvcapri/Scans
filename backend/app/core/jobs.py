"""Runner de jobs: mesma interface para dev local (threads) e Docker (Celery).

O restante da aplicação só conhece `get_runner().submit(job_id)` — trocar a
fila de tarefas não muda nada nas rotas.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from concurrent.futures import ThreadPoolExecutor

from app.core.config import settings

log = logging.getLogger("lexscan.jobs")


class JobRunner(ABC):
    """Abstração da fila de tarefas."""

    @abstractmethod
    def submit(self, job_id: str) -> None:
        """Enfileira um job para execução assíncrona."""


class LocalRunner(JobRunner):
    """Dev local: threads do próprio processo (sem Redis)."""

    def __init__(self, workers: int = 2):
        self._pool = ThreadPoolExecutor(
            max_workers=max(1, workers), thread_name_prefix="lexscan-job"
        )

    def submit(self, job_id: str) -> None:
        from app.workers.execution import run_job

        def _safe() -> None:
            try:
                run_job(job_id)
            except Exception:  # nunca derruba a thread
                log.exception("Falha ao executar o job")

        self._pool.submit(_safe)


class CeleryRunner(JobRunner):
    """Produção/Docker: Celery + Redis."""

    def submit(self, job_id: str) -> None:
        from app.workers.tasks import run_job_task

        run_job_task.delay(job_id)


_runner: JobRunner | None = None


def get_runner() -> JobRunner:
    """Singleton do runner, escolhido por TASK_BACKEND."""
    global _runner
    if _runner is None:
        if settings.task_backend.lower() == "celery":
            _runner = CeleryRunner()
        else:
            _runner = LocalRunner(settings.worker_concurrency)
    return _runner
