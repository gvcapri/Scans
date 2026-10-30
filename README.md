# JudiFiles

Plataforma de conversão e tratamento de documentos jurídicos com guarda de
sessão, sigilo (cifragem em repouso + expurgo LGPD 24h) e 2FA opcional.

- **Frontend:** `frontend/` — React + Vite + Tailwind, pt-BR, tema claro/escuro.
- **Backend:** `backend/` — FastAPI + SQLAlchemy, Python 3.11+.

## Executando localmente

1. **Backend**
   ```bash
   cd backend
   # primeira vez: cria o ambiente de desenvolvimento (o padrão é prod,
   # que exige STORAGE_SECRET real de 32+ caracteres e recusa subir)
   echo "ENVIRONMENT=dev" > .env
   python -m venv .venv
   # Windows:
   .venv\Scripts\python -m pip install -r requirements.txt
   # Linux/macOS:
   .venv/bin/python -m pip install -r requirements.txt
   ..\Scripts\uvicorn app.main:app --reload --port 8000
   ```

2. **Frontend**
   ```bash
   cd frontend
   npm install
   npm run dev   # porta 5173, proxy /api → http://127.0.0.1:8000
   ```

3. **Banco de dados** — SQLite (dev) ou Postgres (compose). Não precisa nada
   a mais: a primeira vez o próprio servidor cria as tabelas.

## Credenciais de desenvolvimento

| Usuário | E-mail | Senha |
|---|---|---|
| Usuário local (dev) | `local@lexscan.local` | `lexscan-dev` |
| (em production, crie pela tela de cadastro) | e-mail seu | 8+ caracteres |

O backend só cria o usuário `local@lexscan.local` em `ENVIRONMENT != prod`.

## Autenticação (Fase 5)

- `POST /api/auth/register` — e-mail + senha (mínimo 8 caracteres) → entra, cookie httpOnly.
- `POST /api/auth/login` — e-mail + senha → token em cookie *e* no corpo.
- `POST /api/auth/login/2fa` — conclusão do login com código TOTP.
- `POST /api/auth/2fa/enable` + `POST /api/auth/2fa/confirm` — ativa 2FA (QR no app autenticador).
- `DELETE /api/auth/2fa` — desliga (exige código corrente).
- `POST /api/auth/logout`, `GET /api/auth/me`.
- Tentativas de login/registro são limitadas por IP (registro) e IP+e-mail (login) —
  `429` quando o limite é excedido. Em `ENVIRONMENT=prod` todo acesso a `/api/*`
  exige sessão real.

## Armazenamento e LGPD

- Cada arquivo é **cifrado em repouso** (chave de aplicação, `STORAGE_SECRET`)
  e só o usuário dono pode descriptografar.
- Arquivos e jobs concluídos com mais de `RETENTION_HOURS` (24h padrão)
  são **expurgados automaticamente** — disco, banco e índice de busca.
- "Apagar agora" (`DELETE /api/files/{id}`) é imediato e expurge o registro do
  índice de busca.

## API resumida

| Método | Rota | Descrição |
|---|---|---|
| `POST` | `/api/auth/register` | Criar conta |
| `POST` | `/api/auth/login` | Entrar |
| `POST` | `/api/auth/login/2fa` | Concluir login (2FA) |
| `POST` | `/api/auth/2fa/enable` | Ativar 2FA |
| `POST` | `/api/auth/2fa/confirm` | Confirmar 2FA |
| `DELETE` | `/api/auth/2fa` | Desligar 2FA |
| `POST` | `/api/auth/logout` | Sair |
| `GET` | `/api/auth/me` | Qual usuário está logado |
| `GET` | `/api/meta/health` | Saúde (pública, em prod) |
| `GET/POST` | `/api/files` | Listar / enviar arquivos |
| `DELETE` | `/api/files/{id}` | Apagar agora |
| `GET` | `/api/files/{id}/download` | Baixar (descriptografado) |
| `POST` | `/api/jobs` | Submeter um trabalho |
| `GET` | `/api/jobs/{id}` | Status do trabalho |
| `GET/POST` | `/api/search` | Busca full-text |
| `POST` | `/api/compare` | Comparar duas versões |
| `GET/POST` | `/api/cases` | Pastas de processo |

## Testes

```bash
cd backend
.venv\Scripts\python -m pytest -q
```

Suite atual: 130 testes, incluindo 7 do expurgo LGPD, 7 do antivírus ClamAV
(mockeado na porta TCP), a suíte de autenticação/isolamento e os testes de
segurança do deploy (401, 503 por flag, índice GIN no Postgres, isolamento
de busca).

## Deploy em VM pequena (1 GB de RAM)

O alvo é uma VM de 1 GB com Docker: `docker compose up` sobe Postgres, API,
frontend (nginx) e Caddy (HTTPS automático) — **só 80/443 são publicados**;
tudo o mais fala por rede interna do compose.

1. **Requisitos:** Docker + plugin compose, domínio com registro `A`
   apontando para a VM, portas 80/443 liberadas.
2. **Ambiente:** `cp .env.example .env` e preencha (nunca vai para o git):
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(32))"  # STORAGE_SECRET
   ```
   `ENVIRONMENT=prod` é o padrão: sem `STORAGE_SECRET` real de 32+ caracteres
   o backend **não sobe** (falha fechada).
3. **Subir:** `docker compose up -d --build` — o Caddy busca o certificado do
   domínio sozinho e força HSTS; o nginx do frontend entrega o build estático
   e repassa `/api/` para a API (com `X-Forwarded-For` confiável).
4. **Verificar:** `scripts/smoke_test.sh https://SEU-DOMINIO` — exercita
   saúde, catálogo público, 401 sem sessão, registro/login, upload,
   download, busca e logout; sai com código ≠ 0 se algo falhar.
5. **Atualizar:** `docker compose up -d --build` após `git pull`.

Por que aguenta 1 GB: pool de banco enxuto (3+2 conexões por processo),
semáforo de jobs pesados (1 por vez por padrão), download/upload em
streaming e **feature flags pesadas desligadas em prod**. Ferramenta com
flag desligada responde `503 {code:"feature_disabled"}` e aparece no painel
como **"Em breve"** — nada de 500 por recurso indisponível.

### Feature flags (`ENVIRONMENT=prod`)

Toda variável `FEATURE_*` aceita `true`/`false`; sem definição vale o
padrão abaixo. Mudou o `.env`: `docker compose up -d` (recria a API).

| Variável | Padrão em prod | O que liga |
|---|---|---|
| `FEATURE_OCR` | `false` | OCR (Tesseract) — também liga o PDF Blindado |
| `FEATURE_CONVERT` | `false` | Conversão via LibreOffice (Word → PDF) |
| `FEATURE_REDACT` | `false` | Redação com tarja irreversível |
| `FEATURE_COMPARE` | `false` | Comparação lado a lado |
| `FEATURE_BATCH` | `false` | Processamento em lote |
| `FEATURE_SEARCH` | `true` | Busca full-text (leve) |
| `FEATURE_CASES` | `true` | Pastas de processo (leve) |
| `FEATURE_JOBS` | `true` | Fila de trabalhos (leve) |
| `FEATURE_NUMBERING` | `true` | Numerar páginas (leve) |
| `FEATURE_OUTLINE` | `true` | Sumário/bookmarks (leve) |
| `FEATURE_INTEGRITY` | `true` | Certificado de integridade (leve) |
| `REGISTRATION_OPEN` | `true` | Aceita novo cadastro (`false` = só convidados) |
| `ALLOWED_EMAIL_DOMAINS` | vazio | Domínios permitidos no cadastro, vírgula-separados |
| `PUBLIC_TOOLS` | vazio | Ferramentas leves públicas (sem login), vírgula-separados |

Outras variáveis da VM: `STORAGE_SECRET` e `SECRET_KEY` (JWT de sessão) —
**ambos obrigatórios em prod** (32+ caracteres; sem eles a API recusa
subir), `POSTGRES_PASSWORD`, `MAX_UPLOAD_MB` (padrão 100),
`RETENTION_HOURS` (expurgo, padrão 24), `TASK_BACKEND=celery`,
`MAX_CONCURRENT_JOBS` (semáforo de memória, padrão 1), `DB_POOL_SIZE` /
`DB_MAX_OVERFLOW` (pool por processo, padrão 3/2).
