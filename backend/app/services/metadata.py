"""Metadados jurídicos (CNJ, partes, datas, tipo de peça) e renomeação (Fase 3).

Dois efeitos no mesmo PDF:

1. grava os metadados do documento (título, autor/partes, assunto,
   palavras-chave com o número CNJ) — úteis para busca e para o PJe;
2. renomeia o arquivo de saída a partir de um template
   (padrão: `{tipo} - {cnj} - {autor} x {reu}`).

O número CNJ e a data são validados antes de gravar: formato
`NNNNNNN-DD.AAAA.J.TR.OOOO` e ISO `AAAA-MM-DD`.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
from dataclasses import dataclass
from pathlib import Path

import pymupdf

log = logging.getLogger("lexscan.metadata")

CNJ_RE = re.compile(r"^\d{7}-\d{2}\.\d{4}\.\d\.\d{2}\.\d{4}$")
FORBIDDEN = re.compile(r'[<>:"/\\|?*\x00-\x1f]')


def _normalize_cnj(value: str) -> str:
    """Aceita com ou sem pontuação e devolve no formato canônico."""
    d = re.sub(r"\D", "", value)
    if len(d) != 20:
        return value.strip()
    # NNNNNNN-DD.AAAA.J.TR.OOOO
    return f"{d[:7]}-{d[7:9]}.{d[9:13]}.{d[13]}.{d[14:16]}.{d[16:20]}"


class _Fields(dict):
    """Template sem KeyError: campo não informado vira vazio."""

    def __missing__(self, key: str) -> str:
        return ""


@dataclass
class LegalMetaOptions:
    """Campos jurídicos gravados no PDF e usados no nome do arquivo."""

    cnj: str = ""
    tipo: str = ""          # ex.: "Petição inicial"
    autor: str = ""
    reu: str = ""
    data: str = ""          # ISO AAAA-MM-DD
    observacao: str = ""
    template: str = "{tipo} - {cnj} - {autor} x {reu}"
    apply_metadata: bool = True
    rename: bool = True

    @classmethod
    def from_dict(cls, data: dict | None) -> "LegalMetaOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        for field_name in ("cnj", "tipo", "autor", "reu", "observacao"):
            setattr(opts, field_name, str(getattr(opts, field_name) or "").strip())
        opts.data = str(opts.data or "").strip()
        opts.template = str(opts.template or "").strip()[:200] or cls.template
        opts.apply_metadata = bool(opts.apply_metadata)
        opts.rename = bool(opts.rename)

        if opts.cnj:
            opts.cnj = _normalize_cnj(opts.cnj)
            if not CNJ_RE.match(opts.cnj):
                raise ValueError(
                    "Número CNJ inválido. Formato esperado: NNNNNNN-DD.AAAA.J.TR.OOOO."
                )
        if opts.data:
            try:
                dt.date.fromisoformat(opts.data)
            except ValueError as exc:
                raise ValueError("Data inválida. Use o formato AAAA-MM-DD.") from exc
        return opts


@dataclass
class MetaResult:
    file: Path
    preview: str = ""


def _render_name(opts: LegalMetaOptions, original_stem: str) -> str:
    fields = _Fields(
        tipo=opts.tipo,
        cnj=opts.cnj,
        autor=opts.autor,
        reu=opts.reu,
        data=opts.data.replace("-", ""),
        original=original_stem,
    )
    try:
        rendered = opts.template.format_map(fields)
    except (KeyError, ValueError, IndexError):
        rendered = original_stem

    tokens = [t.strip() for t in rendered.split(" - ")]
    tokens = [t for t in tokens if t and t.lower() != "x"]
    name = " - ".join(tokens)
    name = re.sub(r"\s+x$", "", name).strip()
    name = FORBIDDEN.sub(" ", name)
    name = re.sub(r"\s+", " ", name).strip(" .-")
    return (name[:150].strip() or original_stem).rstrip(". ")


def apply_legal_metadata(
    pdf_path: str | Path,
    workdir: Path,
    opts: LegalMetaOptions | None = None,
    progress=None,
) -> MetaResult:
    """Grava os metadados jurídicos e salva o PDF com o nome renomeado."""
    opts = opts or LegalMetaOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise ValueError("O PDF não tem páginas.")
        if progress:
            progress(0, 1, "Gravando metadados...")

        partes = " x ".join(p for p in (opts.autor, opts.reu) if p)
        written: list[str] = []
        if opts.apply_metadata:
            meta = dict(doc.metadata or {})
            title = " - ".join(p for p in (opts.tipo, opts.cnj) if p)
            if title:
                meta["title"] = title
            if partes:
                meta["author"] = partes
            if opts.observacao:
                meta["subject"] = opts.observacao
            keywords = [
                f"CNJ: {opts.cnj}" if opts.cnj else "",
                f"tipo: {opts.tipo}" if opts.tipo else "",
                f"partes: {partes}" if partes else "",
                f"data: {opts.data}" if opts.data else "",
            ]
            if any(keywords):
                meta["keywords"] = "; ".join(k for k in keywords if k)
            doc.set_metadata(meta)
            written.append("metadados")

        stem = Path(pdf_path).stem
        new_name = _render_name(opts, stem) if opts.rename else stem
        dest = workdir / f"{new_name}.pdf"
        doc.save(dest, garbage=3, deflate=True)
        if opts.rename:
            written.append("renomeação")
    finally:
        doc.close()

    if progress:
        progress(1, 1, "Concluído")
    preview_parts = []
    if "metadados" in written:
        campos = [
            f"CNJ {opts.cnj}" if opts.cnj else "",
            f"tipo {opts.tipo}" if opts.tipo else "",
            f"partes {partes}" if partes else "",
            f"data {opts.data}" if opts.data else "",
        ]
        preview_parts.append(
            "Metadados gravados: " + ", ".join(c for c in campos if c) + "."
        )
    if "renomeação" in written:
        preview_parts.append(f"Arquivo renomeado para: {dest.name}")
    return MetaResult(file=dest, preview=" ".join(preview_parts) or "Nada a alterar.")
