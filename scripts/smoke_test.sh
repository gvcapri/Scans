#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# smoke_test.sh — verificação rápida de ponta a ponta do JudiFiles.
#
# Sobe contra uma instância já no ar (Docker ou local) e exercita o caminho
# real: Caddy/nginx -> API -> Postgres/SQLite, incluindo as garantias de
# segurança do deploy (401 sem sessão, 503 por flag, catálogo público).
#
# Uso:
#   scripts/smoke_test.sh                       # http://localhost (compose)
#   scripts/smoke_test.sh http://127.0.0.1:8000 # backend direto (dev)
#
# Opcionais (ambiente):
#   SMOKE_EMAIL / SMOKE_PASSWORD  usa login em vez de criar conta
#                                 (útil com REGISTRATION_OPEN=false)
# ---------------------------------------------------------------------------
set -u

BASE_URL="${1:-http://localhost}"
BASE_URL="${BASE_URL%/}"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
# curl do Windows (MinGW) não abre caminhos estilo MSYS (/c/...) no -F:
# em Git Bash usamos o caminho nativo; no Linux, o caminho normal.
ROOT_FORM="$(cd "$SCRIPT_DIR/.." && pwd -W 2>/dev/null || printf '%s' "$ROOT")"
PDF="$ROOT_FORM/samples/contrato.pdf"

JAR="$(mktemp)"
BODY_FILE="$(mktemp)"
trap 'rm -f "$JAR" "$BODY_FILE"' EXIT

FAILURES=0
STEP=0

step() {
  STEP=$((STEP + 1))
  printf '\n%02d) %s\n' "$STEP" "$1"
}

ok()   { printf '   OK   %s\n' "$1"; }
fail() { printf '   FALHA %s\n' "$1"; FAILURES=$((FAILURES + 1)); }

# req METHOD PATH [curl-args...] -> grava o status em $STATUS, o corpo em
# $BODY (texto, sem NULs) e o corpo bruto em $BODY_FILE (para binários).
req() {
  local method="$1" path="$2"
  shift 2
  local out
  out="$(curl -sS -o "$BODY_FILE" -w '%{http_code}' \
    -X "$method" "$BASE_URL$path" -b "$JAR" -c "$JAR" "$@")" || out="000"
  STATUS="$out"
  BODY="$(tr -d '\0' < "$BODY_FILE" 2>/dev/null || true)"
}

check() { # check "descrição" condicao
  if [ "$2" = "0" ]; then ok "$1"; else fail "$1"; fi
}

json_field() { # json_field campo  (1º valor do corpo atual)
  printf '%s' "$BODY" | sed -n "s/.*\"$1\": *\"\([^\"]*\)\".*/\1/p" | head -n 1
}

echo "=== JudiFiles smoke test — $BASE_URL ==="

# ---------------------------------------------------------------- público --
step "Rotas públicas respondem"
req GET /api/meta/health
check "health 200 (got $STATUS)" "$([ "$STATUS" = 200 ]; echo $?)"

req GET /api/meta/features
check "features 200 (got $STATUS)" "$([ "$STATUS" = 200 ]; echo $?)"

req GET /api/meta/tools
TOOLS_JSON="$BODY"
check "tools 200 (got $STATUS)" "$([ "$STATUS" = 200 ]; echo $?)"

# ------------------------------------------------------------------ 401 ----
step "Rota protegida sem sessão devolve 401"
rm -f "$JAR"; : > "$JAR"
req GET /api/files
check "GET /api/files -> 401 unauthorized (got $STATUS)" \
  "$([ "$STATUS" = 401 ] && printf '%s' "$BODY" | grep -q '"unauthorized"'; echo $?)"

# ----------------------------------------------------------------- acesso --
EMAIL="${SMOKE_EMAIL:-smoke-$(date +%s)-$RANDOM@example.com}"
PASSWORD="${SMOKE_PASSWORD:-senha-forte-123}"

step "Acesso (registro ou login)"
if [ -n "${SMOKE_EMAIL:-}" ]; then
  req POST /api/auth/login -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
else
  req POST /api/auth/register -H 'Content-Type: application/json' \
    -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}"
fi
check "login/registro 200 (got $STATUS: $(printf '%s' "$BODY" | head -c 160))" \
  "$([ "$STATUS" = 200 ]; echo $?)"

# ----------------------------------------------------------- upload/leitura --
step "Upload, listagem e download"
if [ ! -f "$PDF" ]; then
  fail "amostra ausente: samples/contrato.pdf (rode scripts/make_samples.py)"
  FILE_ID=""
else
  req POST /api/files -F "files=@$PDF;type=application/pdf"
  FILE_ID="$(json_field id)"
  check "upload 200 com id (got $STATUS)" \
    "$([ "$STATUS" = 200 ] && [ -n "$FILE_ID" ]; echo $?)"
fi

if [ -n "$FILE_ID" ]; then
  req GET "/api/files/$FILE_ID"
  check "GET /api/files/{id} 200 (got $STATUS)" "$([ "$STATUS" = 200 ]; echo $?)"

  req GET "/api/files/$FILE_ID/download"
  HEAD="$(head -c 4 "$BODY_FILE" 2>/dev/null || true)"
  check "download 200 iniciando com %PDF (got $STATUS, head=$HEAD)" \
    "$([ "$STATUS" = 200 ] && [ "$HEAD" = "%PDF" ]; echo $?)"

  req GET "/api/search" -G --data-urlencode "q=PRESTACAO"
  check "busca full-text 200 (got $STATUS)" "$([ "$STATUS" = 200 ]; echo $?)"
fi

# ------------------------------------------------------- flags (503) --------
step "Feature flags refletidas no catálogo"
DISABLED="$(printf '%s' "$TOOLS_JSON" | tr ',' '\n' | grep -cE '"available": *false' || true)"
ENABLED="$(printf '%s' "$TOOLS_JSON" | tr ',' '\n' | grep -cE '"available": *true' || true)"
check "catálogo traz ferramentas disponíveis ($ENABLED) e 'em breve' ($DISABLED)" \
  "$([ "$ENABLED" -gt 0 ]; echo $?)"

req POST /api/compare -H 'Content-Type: application/json' -d '{}'
if [ "$STATUS" = 503 ]; then
  check "flag desligada -> 503 feature_disabled" \
    "$(printf '%s' "$BODY" | grep -q '"feature_disabled"'; echo $?)"
else
  ok "compare ativa nesta instância (status $STATUS) — sem 503 esperado"
fi

# -------------------------------------------------------------- 401 final ---
step "Logout devolve 401 nas rotas protegidas"
req POST /api/auth/logout
check "logout 200 (got $STATUS)" "$([ "$STATUS" = 200 ]; echo $?)"
req GET /api/files
check "após logout -> 401 (got $STATUS)" "$([ "$STATUS" = 401 ]; echo $?)"

# ------------------------------------------------------------------ resumo --
echo
if [ "$FAILURES" -eq 0 ]; then
  echo "=== SMOKE OK ($STEP passos) ==="
  exit 0
fi
echo "=== SMOKE FALHOU: $FAILURES verificações com erro em $STEP passos ==="
exit 1
