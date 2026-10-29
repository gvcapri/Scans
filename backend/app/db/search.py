"""Busca full-text do acervo (Fase 4) — SQLite e Postgres.

Três modos, mesma API pública:

* **fts5** (SQLite dev): tabela virtual `files_fts` com tokenizer
  `unicode61 remove_diacritics 1` — "petição" encontra "peticao" e o
  `snippet()` do FTS5 devolve o trecho já com `<mark>`/`</mark>` em volta.
* **postgres** (produção): tabela comum `files_fts` com coluna `tsvector`
  GERADA (`to_tsvector('portuguese', ...)`) e índice **GIN**; a consulta
  usa `plainto_tsquery` (nunca lança erro de sintaxe) e `ts_headline`
  com `StartSel=<mark>` para o mesmo formato de trecho.
* **like** (fallback): qualquer outro banco — mesma tabela comum, busca
  por LIKE com destaque calculado em Python.

`init_search()` **nunca levanta exceção**: cada passo roda na própria
transação e, se algo falhar, o módulo entra em modo "off" (busca
desabilitada, resto do app intacto) e loga o erro real. O índice é sombra
dos arquivos: o texto é extraído no upload/processamento e guardado aqui
(o PDF original continua cifrado no storage).
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

# modo ativo: "fts5" | "postgres" | "like" | "off"
_mode = "fts5"

# opções do ts_headline (o trecho chega no front já com <mark>)
_PG_HEADLINE_OPTS = (
    "StartSel=<mark>, StopSel=</mark>, "
    "MaxFragments=3, MaxWords=18, MinWords=8, FragmentDelimiter= ..."
)


def available() -> bool:
    """True quando a busca está utilizável nesta instância."""
    return _mode != "off"


def init_search(engine: Engine) -> bool:
    """Cria o índice de busca no dialeto do banco. Nunca levanta exceção.

    Cada passo roda na própria transação — um erro anterior não contamina
    os seguintes (o `InFailedSqlTransaction` do Postgres). Falhou algum
    passo? Desliga **só** a busca (modo "off"), loga o erro real e devolve
    False; o restante da aplicação sobe normalmente.
    """
    global _mode
    dialect = engine.dialect.name

    if dialect == "postgresql":
        steps = [
            (
                "tabela files_fts (tsvector gerado)",
                "CREATE TABLE IF NOT EXISTS files_fts ("
                "file_id TEXT PRIMARY KEY, user_id TEXT, name TEXT, content TEXT, "
                "tsv tsvector GENERATED ALWAYS AS ("
                "to_tsvector('portuguese', coalesce(name, '') || ' ' || "
                "coalesce(content, '')) "
                ") STORED)",
            ),
            (
                "índice GIN em files_fts.tsv",
                "CREATE INDEX IF NOT EXISTS files_fts_tsv_idx "
                "ON files_fts USING GIN (tsv)",
            ),
        ]
    else:
        steps = [
            (
                "tabela full-text files_fts (FTS5)",
                "CREATE VIRTUAL TABLE IF NOT EXISTS files_fts USING fts5("
                "file_id UNINDEXED, user_id UNINDEXED, name, content, "
                "tokenize='unicode61 remove_diacritics 1')",
            ),
        ]

    # 1º passo: tenta o modo nativo do dialeto (tabela + índice, cada um
    # na própria transação — `steps` inteiro, senão o GIN nunca é criado).
    if _run_steps(engine, steps):
        _mode = "postgres" if dialect == "postgresql" else "fts5"
        log.info("Índice full-text: %s", _mode)
        return True

    # 2º passo: fallback comum (tabela simples + LIKE).
    fallback = [
        (
            "tabela comum files_fts (fallback LIKE)",
            "CREATE TABLE IF NOT EXISTS files_fts ("
            "file_id TEXT PRIMARY KEY, user_id TEXT, name TEXT, content TEXT)",
        )
    ]
    if dialect == "postgresql":
        fallback.append(
            (
                "índice em files_fts.user_id (fallback LIKE)",
                "CREATE INDEX IF NOT EXISTS files_fts_user_idx "
                "ON files_fts (user_id)",
            )
        )
    if _run_steps(engine, fallback):
        _mode = "like"
        log.warning(
            "Índice full-text nativo indisponível (%s); usando LIKE — "
            "busca funcional, porém mais lenta em acervo grande.",
            dialect,
        )
        return True

    _mode = "off"
    log.error(
        "Não foi possível criar o índice de busca: busca desabilitada nesta "
        "instância (as demais funcionalidades seguem normais)."
    )
    return False


def _run_steps(engine: Engine, steps: list[tuple[str, str]]) -> bool:
    """Executa cada instrução na própria transação. True se todas passaram."""
    for label, stmt in steps:
        try:
            with engine.begin() as con:
                con.execute(text(stmt))
        except Exception:
            log.error("Falha ao criar %s", label, exc_info=True)
            return False
    return True


def sanitize_query(raw: str) -> str:
    """Converte a busca do usuário em expressão FTS5 segura (sem erro de sintaxe)."""
    terms = re.findall(r"[\wÀ-ÿ]+", raw or "")[:8]
    if not terms:
        return ""
    quoted = ' AND '.join(f'"{t}"' for t in terms)
    return quoted[:400]


def _terms(raw: str) -> list[str]:
    """Termos limpos da consulta (também usados no modo Postgres/LIKE)."""
    return re.findall(r"[\wÀ-ÿ]+", raw or "")[:8]


def index_file(file_id: str, user_id: str, name: str, content: str, engine: Engine) -> None:
    """Indexa (ou reindexa) um documento — apaga a entrada anterior.

    Best-effort: falha aqui só deixa o documento fora da busca, nunca
    derruba o upload/job que chamou.
    """
    if _mode == "off":
        log.debug("Busca desabilitada; não indexando %s", file_id)
        return
    content = (content or "")[:MAX_CONTENT]
    try:
        with engine.begin() as con:
            con.execute(
                text("DELETE FROM files_fts WHERE file_id = :fid"),
                {"fid": file_id},
            )
            con.execute(
                text(
                    "INSERT INTO files_fts (file_id, user_id, name, content) "
                    "VALUES (:fid, :uid, :name, :content)"
                ),
                {"fid": file_id, "uid": user_id, "name": name or "", "content": content},
            )
    except Exception:
        log.warning("Não foi possível indexar %s", file_id, exc_info=True)


def remove_file(file_id: str, engine: Engine) -> None:
    """Remove do índice (arquivo apagado / expurgado)."""
    if _mode == "off":
        return
    try:
        with engine.begin() as con:
            con.execute(
                text("DELETE FROM files_fts WHERE file_id = :fid"),
                {"fid": file_id},
            )
    except Exception:
        log.warning("Não foi possível remover %s do índice", file_id, exc_info=True)


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
    if _mode == "off":
        return [], 0

    terms = _terms(query)
    if not terms:
        return [], 0

    if _mode == "postgres":
        return _search_postgres(query, user_id, engine, limit)

    expr = sanitize_query(query)

    if _mode == "fts5":
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
    with engine.connect() as con:
        rows = con.execute(
            text(
                "SELECT f.file_id, f.name, f.content FROM files_fts f "
                "JOIN files d ON d.id = f.file_id "
                "WHERE f.user_id = :uid AND d.deleted_at IS NULL "
                "AND (LOWER(f.name) LIKE :pat OR LOWER(f.content) LIKE :pat) "
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


def _search_postgres(
    query: str, user_id: str, engine: Engine, limit: int
) -> tuple[list[SearchHit], int]:
    """Consulta tsvector (Português) com plainto_tsquery e destaque ts_headline."""
    # plainto_tsquery ignora operadores e nunca lança erro de sintaxe.
    plain = " ".join(_terms(query))
    if not plain:
        return [], 0
    match = "plainto_tsquery('portuguese', :q)"
    with engine.connect() as con:
        rows = con.execute(
            text(
                "SELECT f.file_id, f.name, "
                "ts_headline('portuguese', coalesce(f.content, ''), "
                f"{match}, :opts) AS snip, "
                f"ts_rank(f.tsv, {match}) AS rank "
                "FROM files_fts f JOIN files d ON d.id = f.file_id "
                f"WHERE f.tsv @@ {match} AND f.user_id = :uid "
                "AND d.deleted_at IS NULL "
                "ORDER BY rank DESC LIMIT :limit"
            ),
            {
                "q": plain,
                "uid": user_id,
                "limit": limit,
                "opts": _PG_HEADLINE_OPTS,
            },
        ).fetchall()
        count = con.execute(
            text(
                "SELECT COUNT(*) FROM files_fts f JOIN files d ON d.id = f.file_id "
                f"WHERE f.tsv @@ {match} AND f.user_id = :uid "
                "AND d.deleted_at IS NULL"
            ),
            {"q": plain, "uid": user_id},
        ).scalar_one()
    hits = [
        SearchHit(
            file_id=r[0],
            name=r[1],
            snippet=escape_snippet(r[2] or ""),
            score=float(r[3] or 0.0),
        )
        for r in rows
    ]
    return hits, int(count)
