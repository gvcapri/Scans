"""Redação irreversível de dados sensíveis (Fase 3).

Fluxo em duas etapas, como manda a revisão manual:

1. `detect_sensitive()` varre a camada de texto e devolve os achados
   agrupados por tipo/valor — a interface mostra a lista e o usuário marca
   o que realmente quer tarjar (e pode acrescentar termos manuais);
2. `redact_pdf()` aplica anotações de redação do PyMuPDF, que APAGAM o
   texto por baixo do retângulo — o dado deixa de existir no arquivo
   (não é um retânculo por cima, dá para selecionar/comprovar).

Falsos positivos são reduzidos com validação de dígitos verificadores
(CPF/CNPJ), algoritmo de Luhn (cartão) e padrões estruturais para RG,
telefone, e-mail, endereço e dados bancários. PDF sem camada de texto é
recusado com orientação de rodar o OCR antes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

log = logging.getLogger("lexscan.redact")


# --------------------------------------------------------------------------- #
# validadores (evitam tarjar números aleatórios)                              #
# --------------------------------------------------------------------------- #
def _digits(text: str) -> str:
    return re.sub(r"\D", "", text)


def _valid_cpf(value: str) -> bool:
    d = _digits(value)
    if len(d) != 11 or d == d[0] * 11:
        return False
    for size in (9, 10):
        total = sum(int(d[i]) * ((size + 1) - i) for i in range(size))
        digit = (total * 10) % 11
        digit = 0 if digit in (10, 11) else digit
        if digit != int(d[size]):
            return False
    return True


def _valid_cnpj(value: str) -> bool:
    d = _digits(value)
    if len(d) != 14 or d == d[0] * 14:
        return False
    weights = (6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2)
    for size in (12, 13):
        total = sum(int(d[i]) * weights[13 - size + i] for i in range(size))
        rest = total % 11
        digit = 0 if rest < 2 else 11 - rest
        if digit != int(d[size]):
            return False
    return True


def _valid_luhn(value: str) -> bool:
    d = _digits(value)
    if not 13 <= len(d) <= 19 or d == d[0] * len(d):
        return False
    total = 0
    for i, ch in enumerate(reversed(d)):
        n = int(ch)
        if i % 2:
            n *= 2
            if n > 9:
                n -= 9
        total += n
    return total % 10 == 0


def _valid_phone(value: str) -> bool:
    d = _digits(value)
    return len(d) in (10, 11) and d[0] in "123456789" and d[2] in "123456789"


def _valid_rg(value: str) -> bool:
    # RG: 8-9 dígitos com dígito verificador final às vezes alfabético
    body = re.sub(r"[.\-]", "", value)
    return 7 <= len(body) <= 10


# --------------------------------------------------------------------------- #
# padrões (ordem = prioridade: o primeiro que marcar o trecho "reivindica")    #
# --------------------------------------------------------------------------- #
PATTERNS: list[dict] = [
    {
        "id": "cpf",
        "label": "CPF",
        "regexes": [r"\b\d{3}\.\d{3}\.\d{3}-\d{2}\b", r"\b\d{11}\b"],
        "check": _valid_cpf,
    },
    {
        "id": "cnpj",
        "label": "CNPJ",
        "regexes": [r"\b\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}\b"],
        "check": _valid_cnpj,
    },
    {
        "id": "card",
        "label": "Cartão de crédito",
        "regexes": [r"\b(?:\d{4}[ .-]?){3}\d{4}\b"],
        "check": _valid_luhn,
    },
    {
        "id": "email",
        "label": "E-mail",
        "regexes": [r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"],
        "check": None,
    },
    {
        "id": "phone",
        "label": "Telefone",
        "regexes": [r"\(?\b\d{2}\)?[\s-]?\d{4,5}[-\s]?\d{4}\b"],
        "check": _valid_phone,
    },
    {
        "id": "rg",
        "label": "RG",
        "regexes": [r"\b\d{1,2}\.\d{3}\.\d{3}-?[\dXx]\b", r"\b\d{7,9}-[\dXx]\b"],
        "check": _valid_rg,
    },
    {
        "id": "bank",
        "label": "Dados bancários",
        "regexes": [
            r"(?i)\bag[êe]ncia\s*(?:n[ºo°\.]*)?\s*[:\-]?\s*\d{3,5}\s*(?:[-/]|conta\s*)\s*\d{3,12}(?:-\d{1,3})?",
            r"(?i)\bconta\s+(?:corrente|poupan[çc]a|sal[áa]rio)?\s*(?:n[ºo°\.]*)?\s*[:\-]?\s*\d{4,12}(?:-\d{1,3})?\b",
            r"(?i)\bchave\s+pix\s*[:\-]?\s*[\w.+-]+@[\w.-]+\.\w+",
        ],
        "check": None,
    },
    {
        "id": "address",
        "label": "Endereço",
        "regexes": [
            r"(?i)(?:\brua|\bavenida|\bav\.?|\balameda|\bal\.?|\btravessa|\btv\.?"
            r"|\brodovia|\brod\.?|\bpraça|\bpraca|\bestrada|\blargo|\bviela)"
            r"\s+[A-Za-zÀ-ÿ0-9''\.\-]+(?:\s+[A-Za-zÀ-ÿ0-9''\.\-]+){0,6}"
            r",?\s*(?:n[ºo°]\s*)?\d{1,5}"
        ],
        "check": None,
    },
]

PATTERN_BY_ID = {p["id"]: p for p in PATTERNS}
DEFAULT_TYPES = [p["id"] for p in PATTERNS]
MAX_GROUPS = 400


def _mask(value: str) -> str:
    """Mascara um valor para exibição em log/prévia (não para aplicação)."""
    if len(value) <= 6:
        return "*" * len(value)
    return f"{value[:3]}{'*' * max(3, len(value) - 5)}{value[-2:]}"


# --------------------------------------------------------------------------- #
# detecção                                                                     #
# --------------------------------------------------------------------------- #
@dataclass
class MatchGroup:
    """Um dado sensível encontrado, agrupado por valor."""

    type: str
    label: str
    value: str
    count: int = 0
    pages: list[int] = field(default_factory=list)  # 0-based


@dataclass
class ScanResult:
    groups: list[MatchGroup] = field(default_factory=list)
    has_text_layer: bool = True
    page_count: int = 0
    total: int = 0


def detect_sensitive(
    pdf_path: str | Path, types: list[str] | None = None
) -> ScanResult:
    """Varre a camada de texto e devolve os achados agrupados por valor."""
    wanted = [p for p in PATTERNS if not types or p["id"] in types]
    result = ScanResult()
    doc = pymupdf.open(pdf_path)
    try:
        result.page_count = doc.page_count
        found: dict[tuple[str, str], MatchGroup] = {}
        has_text = False
        for page in doc:
            text = page.get_text() or ""
            if text.strip():
                has_text = True
            claimed: list[tuple[int, int]] = []
            for pattern in wanted:
                for regex in pattern["regexes"]:
                    for match in re.finditer(regex, text):
                        start, end = match.span()
                        if any(s < end and start < e for s, e in claimed):
                            continue  # já coberto por padrão de maior prioridade
                        value = match.group(0).strip()
                        if not value:
                            continue
                        check = pattern["check"]
                        if check is not None and not check(value):
                            continue
                        claimed.append((start, end))
                        key = (pattern["id"], value)
                        group = found.get(key)
                        if group is None:
                            if len(found) >= MAX_GROUPS:
                                continue
                            group = MatchGroup(
                                type=pattern["id"],
                                label=pattern["label"],
                                value=value,
                            )
                            found[key] = group
                        group.count += 1
                        if page.number not in group.pages:
                            group.pages.append(page.number)
        result.groups = list(found.values())
        result.total = sum(g.count for g in result.groups)
        result.has_text_layer = has_text
    finally:
        doc.close()
    return result


# --------------------------------------------------------------------------- #
# aplicação                                                                    #
# --------------------------------------------------------------------------- #
@dataclass
class RedactOptions:
    """Opções da redação."""

    mode: str = "black"      # black = tarja preta | white = apagar (fundo branco)
    terms: list[str] = field(default_factory=list)   # valores aprovados na revisão
    types: list[str] = field(default_factory=list)   # auto ao detectar (termos vazios)

    @classmethod
    def from_dict(cls, data: dict | None) -> "RedactOptions":
        data = data or {}
        valid = {f: data[f] for f in cls.__dataclass_fields__ if f in data}
        opts = cls(**valid)
        opts.mode = "white" if str(opts.mode) == "white" else "black"
        opts.terms = [str(t).strip() for t in (opts.terms or []) if str(t).strip()]
        opts.types = [str(t) for t in (opts.types or []) if str(t) in PATTERN_BY_ID]
        return opts


@dataclass
class RedactResult:
    file: Path
    redacted: int = 0
    values: int = 0
    preview: str = ""


def redact_pdf(
    pdf_path: str | Path,
    workdir: Path,
    opts: RedactOptions | None = None,
    progress=None,
) -> RedactResult:
    """Aplica as tarjas de forma irreversível e grava o PDF resultante."""
    opts = opts or RedactOptions()
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)

    doc = pymupdf.open(pdf_path)
    try:
        if doc.page_count == 0:
            raise ValueError("O PDF não tem páginas.")

        values = list(dict.fromkeys(opts.terms))  # preserva ordem, remove duplicados
        if not values:
            scan = detect_sensitive(pdf_path, opts.types or None)
            if not scan.has_text_layer:
                raise ValueError(
                    "O PDF não tem camada de texto (é imagem). Execute o OCR "
                    "antes de redigir."
                )
            values = [g.value for g in scan.groups]
        if not values:
            raise ValueError(
                "Nenhum dado sensível localizado para redigir. Revise a busca "
                "ou informe os termos manualmente."
            )

        fill = (0, 0, 0) if opts.mode == "black" else (1, 1, 1)
        total_pages = doc.page_count
        applied = 0
        missing: list[str] = []

        for index, page in enumerate(doc, start=1):
            if progress:
                progress(index - 1, total_pages, f"Redigindo página {index} de {total_pages}...")
            found_on_page = 0
            for value in values:
                rects = page.search_for(value)
                for rect in rects:
                    page.add_redact_annot(rect, fill=fill)
                    found_on_page += 1
            if found_on_page:
                page.apply_redactions()
                applied += found_on_page

        if applied == 0:
            raise ValueError(
                "Os dados informados não foram localizados visualmente no PDF. "
                "Se o documento for escaneado, execute o OCR antes de redigir."
            )

        # valores não localizados viram aviso no prévio (não bloqueia)
        for value in values:
            if not any(doc[i].search_for(value) for i in range(doc.page_count)):
                missing.append(_mask(value))

        stem = Path(pdf_path).stem
        dest = workdir / f"{stem}_redigido.pdf"
        doc.save(dest, garbage=4, deflate=True)
    finally:
        doc.close()

    shown = [(_mask(v)) for v in values[:8]]
    extra = f" (+{len(values) - 8} outros)" if len(values) > 8 else ""
    preview = (
        f"{applied} ocorrência(s) removida(s) de forma irreversível em "
        f"{len(values)} dado(s): {', '.join(shown)}{extra}."
    )
    if missing:
        preview += (
            " Atenção: não localizado em texto (talvez esteja em imagem): "
            + ", ".join(missing[:6])
            + "."
        )
    return RedactResult(file=dest, redacted=applied, values=len(values), preview=preview)
