"""Busca full-text do acervo (Fase 4).

Dois caminhos, mesma API:

* **SQLite FTS5** (dev local): tabela virtual `files_fts` com tokenizer
  `unicode61 remove_diacritics 1` — "petição" encontra "peticao" e o
  `snippet()` do FTS5 devolve o trecho já com `<mark>`/`</mark>` em volta.
* **Fallback LIKE**: se o SQLite vier sem FTS5 (ou outro banco), a mesma
  tabela é criada como comum e a busca cai para `LIKE` com destaque
  calculado em Python — resultado igual, só mais lento em acervo grande.

A tabela é sombra dos arquivos: o texto é extraído na hora do upload/do
processamento e guardado aqui (o PDF original continua cifrado no storage).
"""

from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.engine import Engine

log = logging.getLogger("lexscan.search")

MARK_OPEN = "<mark>"
MARK_CLOSE = "</mark>"

# limites de segurança (consulta e conteúdo indexado)
MAX_QUERY = 200
MAX_CONTENT = 300_000  # caracteres por documento

_fts = True  # False => fallback LIKE


def init_search(engine: Engine) -> None:
    """Cria a tabela de índice (tenta FTS5, senão a comum)."""
    global _fts
    with engine.begin() as con:
        try:
            con.execute(
                text(
                    "CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5("
                    "file_id UNINDEXED, user_id UNINDEXED, name, content, "
                    "tokenize='unicode61 remove_diacritics 1')"
                )
            )
            _fts = True
            log.info("Índice full-text: FTS5")
        except Exception:
            con.execute(
                text(
                    "CREATE TABLE IF NOT EXISTS files_fts ("
                    "file_id TEXT PRIMARY KEY, user_id TEXT, name TEXT, content TEXT)"
                )
            )
            _fts = False
            log.warning("Índice full-text: FTS5 indisponível, usando LIKE")


def sanitize_query(raw: str) -> str:
    """Converte a busca do usuário em expressão FTS5 segura (sem erro de sintaxe)."""
    terms = re.findall(r"[\wÀ-ÿ]+", raw or "")[:8]
    if not terms:
        return ""
    quoted = " AND ".join(f'"{t}"' for t in terms)
    return quoted[:400]


def index_file(file_id: str, user_id: str, name: str, content: str, engine: Engine) -> None:
    """Indexa (ou reindexa) um documento — apaga a entrada anterior."""
    content = (content or "")[:MAX_CONTENT]
    with engine.begin() as con:
        con.execute(
            text("DELETE FROM files_fts WHERE file_id = :fid"), {"fid": file_id}
        )
        con.execute(
            text(
                "INSERT INTO files_fts (file_id, user_id, name, content) "
                "VALUES (:fid, :uid, :name, :content)"
            ),
            {"fid": file_id, "uid": user_id, "name": name or "", "content": content},
        )


def remove_file(file_id: str, engine: Engine) -> None:
    """Remove do índice (arquivo apagado / expurgado)."""
    with engine.begin() as con:
        con.execute(
            text("DELETE FROM files_fts WHERE file_id = :fid"), {"fid": file_id}
        )


@dataclass
class SearchHit:
    file_id: str
    name: str
    snippet: str
    score: float


def escape_snippet(snippet: str) -> str:
    """Escapa o HTML do trecho mantendo só as marcações <mark> do índice.

    O texto vem do documento (pod conter '<' ou '&'); sem este passo a
    interface renderizaria conteúdo do documento como HTML.
    """
    safe = html.escape(snippet or "", quote=False)
    safe = safe.replace("&lt;mark&gt;", MARK_OPEN).replace("&lt;/mark&gt;", MARK_CLOSE)
    return safe


def _highlight_like(content: str, query: str) -> str:
    """Destaque manual para o fallback LIKE (trecho em volta do 1º termo)."""
    terms = re.findall(r"[\wÀ-ÿ]+", query or "")
    if not terms or not content:
        return content[:180]
    lower = content.lower()
    positions = [lower.find(t.lower()) for t in terms]
    positions = [p for p in positions if p >= 0]
    start = max(0, (min(positions) if positions else 0) - 60)
    fragment = content[start : start + 180].strip()
    marked: list[str] = []
    cursor = 0
    lower_fragment = fragment.lower()
    spans: list[tuple[int, int]] = []
    for term in terms:
        pos = lower_fragment.find(term.lower())
        if pos >= 0:
            spans.append((pos, pos + len(term)))
    spans.sort()
    for start_pos, end_pos in spans:
        if start_pos < cursor:
            continue
        marked.append(fragment[cursor:start_pos])
        marked.append(f"{MARK_OPEN}{fragment[start_pos:end_pos]}{MARK_CLOSE}")
        cursor = end_pos
    marked.append(fragment[cursor:])
    return ("…" + "".join(marked)) if start else "".join(marked)


def search(
    query: str, user_id: str, engine: Engine, limit: int = 20
) -> tuple[list[SearchHit], int]:
    """Busca no acervo do usuário. Devolve (resultados, total encontrado)."""
    expr = sanitize_query(query)
    if not expr:
        return [], 0

    if _fts:
        with engine.connect() as con:
            rows = con.execute(
                text(
                    "SELECT f.file_id, f.name, "
                    "snippet(files_fts, 3, :open, :close, '…', 14) AS snip, rank "
                    "FROM files_fts f JOIN files d ON d.id = f.file_id "
                    "WHERE files_fts MATCH :expr AND f.user_id = :uid "
                    "AND d.deleted_at IS NULL "
                    "ORDER BY rank LIMIT :limit"
                ),
                {"expr": expr, "uid": user_id, "limit": limit,
                 "open": MARK_OPEN, "close": MARK_CLOSE},
            ).fetchall()
            count = con.execute(
                text(
                    "SELECT COUNT(*) FROM files_fts f JOIN files d ON d.id = f.file_id "
                    "WHERE files_fts MATCH :expr AND f.user_id = :uid "
                    "AND d.deleted_at IS NULL"
                ),
                {"expr": expr, "uid": user_id},
            ).scalar_one()
        hits = [
            SearchHit(
                file_id=r[0], name=r[1], snippet=escape_snippet(r[2]), score=abs(float(r[3]))
            )
            for r in rows
        ]
        return hits, int(count)

    # ------------------------------------------------ fallback LIKE
    terms = re.findall(r"[\wÀ-ÿ]+", query)[:8]
    with engine.connect() as con:
        rows = con.execute(
            text(
                "SELECT f.file_id, f.name, f.content FROM files_fts f "
                "JOIN files d ON d.id = f.file_id "
                "WHERE f.user_id = :uid AND d.deleted_at IS NULL "
                "AND (LOWER(f.name) LIKE :pat OR LOWER(f.content) LIKE :pat)"
                "LIMIT :limit"
            ),
            {"uid": user_id, "pat": f"%{terms[0].lower()}%", "limit": limit * 5},
        ).fetchall()
    hits = [
        SearchHit(
            file_id=r[0],
            name=r[1],
            snippet=escape_snippet(_highlight_like(r[2] or "", query)),
            score=1.0,
        )
        for r in rows
    ]
    return hits[:limit], len(hits)
