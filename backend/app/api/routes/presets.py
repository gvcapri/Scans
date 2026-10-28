"""Rotas de perfis salvos (ex.: limites de compressão por tribunal).

Os perfis embutidos (PJe, e-SAJ, e-Proc, Projudi) vêm do código e não podem
ser apagados; o usuário pode salvá-los editados, e aí ficam na conta dele.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import current_user
from app.db.models import ToolPreset, User
from app.db.session import get_db
from app.services.compress import BUILTIN_PRESETS

router = APIRouter(prefix="/presets", tags=["perfis"])

# Ferramentas que hoje usam perfis salvos.
PRESET_TOOLS = {"compress"}
MAX_PRESETS_PER_TOOL = 50


def _serialize(preset: ToolPreset) -> dict:
    return {
        "id": preset.id,
        "name": preset.name,
        "tool": preset.tool,
        "builtin": False,
        "options": preset.options or {},
        "created_at": preset.created_at.isoformat() if preset.created_at else None,
    }


def _builtins(tool: str) -> list[dict]:
    if tool != "compress":
        return []
    return [
        {
            "id": f"builtin:{row['id']}",
            "name": row["name"],
            "tool": tool,
            "builtin": True,
            "hint": row["hint"],
            "options": {
                "limit_mb": row["limit_mb"],
                "quality": row["quality"],
                "pdfa": row["pdfa"],
                "split": row["split"],
            },
        }
        for row in BUILTIN_PRESETS
    ]


class PresetCreate(BaseModel):
    """Payload de criação de perfil."""

    tool: str = Field(..., description="compress")
    name: str = Field(..., min_length=1, max_length=60, description="Nome do perfil")
    options: dict = Field(default_factory=dict, description="Opções da ferramenta")


@router.get("", summary="Perfis disponíveis (embutidos + salvos)")
def list_presets(
    tool: str = "compress",
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    if tool not in PRESET_TOOLS:
        raise HTTPException(status_code=400, detail="Ferramenta sem perfis.")
    saved = db.scalars(
        select(ToolPreset)
        .where(ToolPreset.user_id == user.id, ToolPreset.tool == tool)
        .order_by(ToolPreset.created_at)
    ).all()
    return {"tool": tool, "presets": _builtins(tool) + [_serialize(p) for p in saved]}


@router.post("", summary="Salvar perfil")
def create_preset(
    payload: PresetCreate,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    if payload.tool not in PRESET_TOOLS:
        raise HTTPException(status_code=400, detail="Ferramenta sem perfis.")
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Informe um nome para o perfil.")

    existing = db.scalars(
        select(ToolPreset).where(
            ToolPreset.user_id == user.id, ToolPreset.tool == payload.tool
        )
    ).all()
    if len(existing) >= MAX_PRESETS_PER_TOOL:
        raise HTTPException(
            status_code=400,
            detail=f"Limite de {MAX_PRESETS_PER_TOOL} perfis salvos atingido.",
        )
    if any(p.name.lower() == name.lower() for p in existing):
        raise HTTPException(status_code=409, detail="Já existe um perfil com esse nome.")

    preset = ToolPreset(
        user_id=user.id,
        tool=payload.tool,
        name=name[:60],
        options=dict(payload.options or {}),
    )
    db.add(preset)
    db.commit()
    db.refresh(preset)
    return _serialize(preset)


@router.delete("/{preset_id}", summary="Apagar perfil salvo")
def delete_preset(
    preset_id: str,
    db: Session = Depends(get_db),
    user: User = Depends(current_user),
) -> dict:
    if preset_id.startswith("builtin:"):
        raise HTTPException(status_code=400, detail="Perfil embutido não pode ser apagado.")
    preset = db.get(ToolPreset, preset_id)
    if preset is None or preset.user_id != user.id:
        raise HTTPException(status_code=404, detail="Perfil não encontrado.")
    db.delete(preset)
    db.commit()
    return {"ok": True, "id": preset_id}
