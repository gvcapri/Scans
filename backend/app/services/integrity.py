"""Certificado de integridade: SHA-256 + relatório PDF (Fase 3).

Gera um PDF assinável por construção: para cada arquivo de entrada calcula
o hash SHA-256 (o mesmo que o storage usa para conferir uploads) e monta
um relatório com identificação, tamanho, data/hora da emissão (UTC) e o
hash por extensão.

A estrutura é a preparada para ICP-Brasil: o hash é o "conteúdo assinado"
— basta assinar esse valor com um certificado ICP (assinatura detachada)
para o documento valer como registro de integridade. O relatório também
serve como prova autônoma: qualquer alteração posterior do arquivo muda o
SHA-256 e invalida a comparação.
"""

from __future__ import annotations

import datetime as dt
import logging
from dataclasses import dataclass
from pathlib import Path

import pymupdf

from app.core.config import settings
from app.services.hashing import sha256_file

log = logging.getLogger("lexscan.integrity")

A4_W, A4_H = 595, 842
MARGIN = 56.0
FOOTER_NOTE = (
    "Qualquer alteração posterior do arquivo modifica o SHA-256 acima. "
    "Este certificado foi preparado para assinatura digital ICP-Brasil: "
    "o hash é o conteúdo a ser assinado (assinatura detachada)."
)


@dataclass
class IntegrityOptions:
    """Opções do certificado."""

    emitente: str = ""      # quem emite (escritório, responsável)
    observacao: str = ""    # livre: processo, finalidade etc.

    @classmethod
    def from_dict(cls, data: dict | None) -> "IntegrityOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        opts.emitente = str(opts.emitente or "").strip()[:120]
        opts.observacao = str(opts.observacao or "").strip()[:300]
        return opts


@dataclass
class IntegrityResult:
    file: Path
    files: int = 0
    preview: str = ""


@dataclass
class _Record:
    name: str
    size: int
    sha256: str
    pages: int | None = None


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    if size < 1024 * 1024:
        return f"{size / 1024:.1f} KB"
    return f"{size / (1024 * 1024):.2f} MB"


def _new_page(doc: pymupdf.Document) -> tuple[pymupdf.Page, float]:
    page = doc.new_page(width=A4_W, height=A4_H)
    return page, 64.0


def _write(page: pymupdf.Page, y: float, text: str, **kwargs) -> float:
    page.insert_text(pymupdf.Point(MARGIN, y), text, **kwargs)
    return y


def build_certificate(
    sources: list[Path],
    workdir: Path,
    opts: IntegrityOptions | None = None,
    progress=None,
) -> IntegrityResult:
    """Calcula os hashes e gera o PDF do certificado de integridade."""
    opts = opts or IntegrityOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    if not sources:
        raise ValueError("Nenhum arquivo para certificar.")

    records: list[_Record] = []
    for index, path in enumerate(sources, start=1):
        if progress:
            progress(index - 1, len(sources), f"Calculando hash de {index} de {len(sources)}...")
        digest = sha256_file(path)
        pages = None
        if path.suffix.lower() == ".pdf":
            try:
                with pymupdf.open(path) as probe:
                    pages = probe.page_count
            except Exception:
                pages = None
        records.append(_Record(name=path.name, size=path.stat().st_size, sha256=digest, pages=pages))

    now = dt.datetime.now(dt.timezone.utc)
    stamp = now.strftime("%d/%m/%Y %H:%M UTC")

    doc = pymupdf.open()
    try:
        page, y = _new_page(doc)

        page.insert_text(
            pymupdf.Point(MARGIN, y),
            "CERTIFICADO DE INTEGRIDADE",
            fontsize=16,
            fontname="hebo",
            color=(0, 0, 0),
        )
        y += 8
        page.draw_line(
            pymupdf.Point(MARGIN, y),
            pymupdf.Point(A4_W - MARGIN, y),
            color=(0.55, 0.55, 0.55),
            width=0.8,
        )
        y += 22

        header = [
            (f"Emitido em: {stamp}", 10),
            (f"Ferramenta: {settings.app_name} 1.0.0", 10),
        ]
        if opts.emitente:
            header.append((f"Emitente: {opts.emitente}", 10))
        if opts.observacao:
            header.append((f"Observação: {opts.observacao}", 10))
        header.append((f"Arquivos certificados: {len(records)}", 10))
        for text, size in header:
            y = _write(page, y, text, fontsize=size, fontname="helv", color=(0.15, 0.15, 0.15))
            y += 16
        y += 8

        for record in records:
            # cada bloco ocupa ~110pt; quebra de página antes de estourar
            if y > A4_H - 150:
                page, y = _new_page(doc)
            y += 6
            name = record.name
            while name and pymupdf.get_text_length(name, fontname="hebo", fontsize=11) > A4_W - 2 * MARGIN:
                name = name[:-1]
            if name != record.name:
                name = name.rstrip() + "…"
            y = _write(page, y, name, fontsize=11, fontname="hebo", color=(0, 0, 0))
            y += 15
            detail = f"Tamanho: {_fmt_size(record.size)}"
            if record.pages is not None:
                detail += f" · {record.pages} página(s)"
            y = _write(page, y, detail, fontsize=9.5, fontname="helv", color=(0.3, 0.3, 0.3))
            y += 14
            y = _write(page, y, "SHA-256:", fontsize=9.5, fontname="helv", color=(0.3, 0.3, 0.3))
            y += 13
            for chunk in (record.sha256[:32], record.sha256[32:]):
                y = _write(page, y, chunk, fontsize=10, fontname="cour", color=(0, 0, 0))
                y += 13
            y += 10

        # rodapé com a nota de assinatura ICP-Brasil (quebra linha a linha)
        note_y = A4_H - 90
        words = FOOTER_NOTE.split()
        line, lines = "", []
        for word in words:
            trial = f"{line} {word}".strip()
            if pymupdf.get_text_length(trial, fontname="helv", fontsize=8.5) > A4_W - 2 * MARGIN:
                lines.append(line)
                line = word
            else:
                line = trial
        if line:
            lines.append(line)
        page.draw_line(
            pymupdf.Point(MARGIN, note_y - 12),
            pymupdf.Point(A4_W - MARGIN, note_y - 12),
            color=(0.7, 0.7, 0.7),
            width=0.6,
        )
        for i, text in enumerate(lines):
            page.insert_text(
                pymupdf.Point(MARGIN, note_y + i * 12),
                text,
                fontsize=8.5,
                fontname="helv",
                color=(0.35, 0.35, 0.35),
            )

        doc.set_metadata(
            {
                "title": "Certificado de Integridade",
                "author": opts.emitente,
                "subject": f"SHA-256 de {len(records)} arquivo(s) — {stamp}",
                "keywords": "integridade, SHA-256, ICP-Brasil",
                "creator": settings.app_name,
                "producer": settings.app_name,
            }
        )
        dest = workdir / f"certificado_integridade_{now.strftime('%Y%m%d_%H%M')}.pdf"
        doc.save(dest, garbage=3, deflate=True)
    finally:
        doc.close()

    preview = f"Certificado com {len(records)} arquivo(s) emitido em {stamp}."
    return IntegrityResult(file=dest, files=len(records), preview=preview)
