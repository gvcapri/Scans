"""Modelos do banco de dados do LexScan.

O `user_id` está presente em todos os registros que guardam arquivo/job:
é a base do isolamento por usuário exigido pela LGPD (um usuário jamais
acessa arquivos de outro).
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _uuid() -> str:
    """Identificador opaco de 32 hex (sem informação sensível embutida)."""
    return uuid.uuid4().hex


def _utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class User(Base):
    """Usuário. Na Fase 1 existe um usuário local único; a Fase 5 adiciona
    e-mail/senha + 2FA sem mudar o restante do esquema."""

    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str | None] = mapped_column(String(255), nullable=True)
    totp_secret: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class RevokedToken(Base):
    """JWTs assinados já invalidados (logout e desafios 2FA usados).

    Guarda apenas o `jti` até o `exp` do próprio token: depois disso o JWT
    expirou sozinho e a linha sai no expurgo LGPD. É o que faz o logout
    desvaler de verdade um token que o cliente ainda tenha em mãos.
    """

    __tablename__ = "revoked_tokens"

    jti: Mapped[str] = mapped_column(String(32), primary_key=True)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime, index=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class CaseFolder(Base):
    """Pasta de processo/cliente (usada a partir da Fase 4)."""

    __tablename__ = "case_folders"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), index=True
    )
    name: Mapped[str] = mapped_column(String(255))
    process_number: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class StoredFile(Base):
    """Metadados de um arquivo cifrado no armazenamento.

    O arquivo em si está em STORAGE_ROOT/<user_id>/<id>.<ext>, cifrado;
    `original_name` fica só no banco (nunca usado como caminho de disco).
    """

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    original_name: Mapped[str] = mapped_column(String(255))
    mime: Mapped[str] = mapped_column(String(100))
    ext: Mapped[str] = mapped_column(String(16), default="")
    size: Mapped[int] = mapped_column(Integer, default=0)  # tamanho original
    sha256: Mapped[str] = mapped_column(String(64), index=True)
    role: Mapped[str] = mapped_column(String(16), default="input")  # input|output
    job_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("jobs.id"), nullable=True, index=True
    )
    case_folder_id: Mapped[str | None] = mapped_column(
        String(32), ForeignKey("case_folders.id"), nullable=True, index=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)


class ToolPreset(Base):
    """Perfil salvo pelo usuário (ex.: limites de compressão por tribunal).

    Os perfis embutidos (PJe, e-SAJ, ...) vivem no código e nunca aqui; este
    modelo guarda apenas cópias editadas/salvas pelo próprio usuário.
    """

    __tablename__ = "tool_presets"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("users.id"), index=True
    )
    tool: Mapped[str] = mapped_column(String(32), index=True)  # compress | ...
    name: Mapped[str] = mapped_column(String(60))
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow)


class Job(Base):
    """Unidade de processamento (OCR, Blindado, ...).

    O worker atualiza `page_current`/`message` a cada página: é daqui que o
    front lê a barra de progresso (polling em GET /api/jobs/{id}).
    """

    __tablename__ = "jobs"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uuid)
    user_id: Mapped[str] = mapped_column(String(32), ForeignKey("users.id"), index=True)
    kind: Mapped[str] = mapped_column(String(32), index=True)  # ocr|blind|...
    status: Mapped[str] = mapped_column(String(16), default="queued", index=True)
    # queued | running | done | error
    progress: Mapped[int] = mapped_column(Integer, default=0)  # 0..100
    page_current: Mapped[int] = mapped_column(Integer, default=0)
    page_total: Mapped[int] = mapped_column(Integer, default=0)
    message: Mapped[str] = mapped_column(String(255), default="Na fila")
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    options: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    input_file_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    output_file_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    preview: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(DateTime, default=_utcnow, index=True)
    started_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime, nullable=True)
