# JudiFiles

Plataforma de conversão e tratamento de documentos jurídicos com guarda de
sessão, sigilo (cifragem em repouso + expurgo LGPD 24h) e 2FA opcional.

- **Frontend:** `frontend/` — React + Vite + Tailwind, pt-BR, tema claro/escuro.
- **Backend:** `backend/` — FastAPI + SQLAlchemy, Python 3.11+.

## Executando localmente

1. **Backend**
   ```bash
   cd backend
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

Suite atual: ~124 testes, incluindo 7 do expurgo LGPD e 7 do antivírus ClamAV
(mockeado na porta TCP) e a suíte de autenticação/isolamento.

## Deploy

- `docker compose up` (api, worker, redis, db, frontend) — na Fase 5.
- `Dockerfile` individual para api e frontend no repo.
