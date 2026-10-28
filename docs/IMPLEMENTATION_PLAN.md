# LexScan — Implementation Plan

Plano de implementação da plataforma de conversão e tratamento de documentos para
advogados e escritórios brasileiros. Gerado **antes** da codificação, conforme
pedido. Cada fase termina com uma pausa para aprovação do usuário.

---

## 1. Visão geral da arquitetura

```
┌──────────────────────────────────────────────────────────────────────┐
│  Browser (React + Vite + Tailwind)  — pt-BR, tema claro/escuro, WCAG │
└───────────────┬──────────────────────────────────────────────────────┘
                │ HTTPS / JSON  (REST + polling de progresso)
┌───────────────▼──────────────────────────────────────────────────────┐
│  FastAPI (app/main.py)                                              │
│  ├── api/routes/*      autenticação, arquivos, ferramentas, busca   │
│  ├── core/*            config, segurança, rate limit, runner jobs   │
│  ├── services/*        OCR, blindagem, compressão, redação, hash…   │
│  └── db/*              SQLAlchemy + FTS (Postgres) / FTS5 (SQLite)  │
└───────┬───────────────────────────────┬──────────────────────────────┘
        │ enfileira Job                 │ grava/lê
┌───────▼──────────────┐   ┌────────────▼─────────────────────────────┐
│  Executor de jobs    │   │  Storage em disco, cifrado em repouso    │
│  • local: ThreadPool │   │  <storage_root>/<user_id>/<job_id>/…     │
│  • docker: Celery    │   │  + retenção 24h + "Apagar agora"         │
│    + Redis           │   └──────────────────────────────────────────┘
└──────────────────────┘
        PostgreSQL (docker) / SQLite (dev local)
```

**Decisões-chave**

| Tema | Decisão | Motivo |
|---|---|---|
| Runtime | **Local primeiro** (uvicorn + Vite), `docker-compose.yml` entregue e testado na Fase 5 | iteração rápida; Tesseract/LibreOffice locais |
| Jobs | Interface `JobRunner` com 2 implementações: `LocalRunner` (ThreadPool) e `CeleryRunner` (broker Redis) | mesmo código roda em dev e em produção |
| OCR | **PyMuPDF + Tesseract** (`por`, `eng`), em vez de OCRmyPDF | idêntico no Windows e no Linux; PyMuPDF já renderiza, deskew, limpa ruído e insere a camada de texto invisível |
| Conversão Word | LibreOffice headless (`soffice --headless --convert-to`) | único caminho confiável DOCX↔PDF |
| Banco | `DATABASE_URL` → SQLite (dev) / PostgreSQL (compose) | Fase 4 usa `tsvector` no Postgres e FTS5 no SQLite |
| Armazenamento | disco local cifrado (Fernet/AES-256-GCM por arquivo), substituível por S3-compatível via `STORAGE_BACKEND` | LGPD: at rest + expurgo automático |
| Blindagem | rasteriza página a DPI configurável → PDF só-imagem → `pikepdf` aplica permissões/senha e **apaga metadados** | elimina texto, formulários, scripts e anotações |

### Fluxo de um job

1. Upload → validação (magic bytes MIME, tamanho, nome, anti path-traversal).
2. Registro do `Job` no banco (`queued`) e enfileiramento no runner.
3. Worker executa a cadeia de operações, gravando **progresso por página** e
   mensagens em pt-BR.
4. Frontend faz polling de `/api/jobs/{id}` → barra de progresso + prévia.
5. Conclusão → hash SHA-256, download assinado por usuário, registro no histórico.
6. Retenção (padrão 24h) → expurgo; ou exclusão imediata pelo botão "Apagar agora".

---

## 2. Estrutura de pastas

```
conversor/
├── README.md                        # instalação, env vars, exemplos
├── docker-compose.yml               # api, worker, redis, db, frontend
├── .env.example
├── docs/
│   └── IMPLEMENTATION_PLAN.md       # este documento
├── backend/
│   ├── requirements.txt
│   ├── Dockerfile
│   ├── app/
│   │   ├── main.py                  # app factory, CORS, OpenAPI, rotas
│   │   ├── core/
│   │   │   ├── config.py            # pydantic-settings (env)
│   │   │   ├── security.py          # argon2/bcrypt, JWT, 2FA TOTP
│   │   │   ├── rate_limit.py        # limitação por IP/usuário
│   │   │   ├── logging_setup.py     # logs SEM conteúdo de documento
│   │   │   └── jobs.py              # JobRunner (local | celery)
│   │   ├── db/
│   │   │   ├── session.py
│   │   │   ├── models.py            # User, CaseFolder, Document, Job, …
│   │   │   └── search.py            # FTS Postgres / SQLite FTS5
│   │   ├── api/routes/
│   │   │   ├── auth.py  files.py  jobs.py  ocr.py  pdf.py
│   │   │   ├── redact.py  numbering.py  batch.py  search.py
│   │   │   ├── compare.py  cases.py  profiles.py  legal.py
│   │   ├── services/
│   │   │   ├── storage.py           # cifrado, isolamento por usuário
│   │   │   ├── validation.py        # MIME real, limites, zip seguro
│   │   │   ├── ocr.py               # OCR + deskew + ruído + contraste
│   │   │   ├── blind.py             # PDF Blindado (raster + pikepdf)
│   │   │   ├── compress.py          # perfil de tribunal, PDF/A, split
│   │   │   ├── convert.py           # imagens/Word/PDF ↔ TXT/DOCX
│   │   │   ├── merge_split.py       # mesclar, dividir, reordenar
│   │   │   ├── redact.py            # regex CPF/CNPJ/… e remoção real
│   │   │   ├── numbering.py         # Bates, Fls., marca d'água
│   │   │   ├── outline.py           # sumário/índice/bookmarks
│   │   │   ├── integrity.py         # SHA-256 + relatório (ICP-ready)
│   │   │   ├── metadata.py          # CNJ, partes, datas, tipo de peça
│   │   │   ├── compare.py           # dif lado a lado
│   │   │   ├── batch.py             # fluxos/presets em lote
│   │   │   └── retention.py         # expurgo LGPD
│   │   └── workers/
│   │       ├── celery_app.py
│   │       └── tasks.py
│   └── tests/
│       ├── test_ocr.py  test_blind.py  test_redact.py  test_hash.py …
└── frontend/
    ├── package.json  vite.config.ts  tailwind.config.js  Dockerfile
    └── src/
        ├── App.tsx  main.tsx  theme.tsx
        ├── api/client.ts            # cliente REST tipado
        ├── pages/  Dashboard, Tool, History, Cases, Search, Compare, Auth
        └── components/ Dropzone, JobProgress, PagePreview, Card, Layout
```

---

## 3. Fases de execução

> **Ritmo acordado:** ao fim de cada fase, parar, resumir e pedir aprovação.

### Fase 1 — Fundação, upload/download, OCR e PDF Blindado ✅ concluída
- Esqueleto do repositório, config, banco, storage cifrado, validação de upload.
- Runner de jobs + progresso por página.
- Serviço e endpoint de **OCR** (PDF escaneado/JPG/PNG/TIFF → PDF pesquisável/TXT/DOCX;
  idioma, deskew, ruído, rotação, contraste).
- Serviço e endpoint de **PDF Blindado** (DPI 150/200/300, toggle de camada de
  texto via OCR, senha de proprietário, remoção de metadados, qualidade JPEG).
- Frontend: shell, dashboard com cards, drag & drop, progresso, prévia e download.
- Testes de OCR, blindagem e hash.

### Fase 2 — Conversões, mesclar/dividir e compressor de tribunal ✅ concluída
- Imagens→PDF, Word→PDF (LibreOffice), PDF→PNG/JPG, PDF→TXT/DOCX.
- Mesclar com reordenação por arrastar e soltar; dividir por intervalo/extração.
- Compressor com **perfis de tribunal salvos pelo usuário** (limite em MB),
  divisão automática em partes e conversão para PDF/A.

### Fase 3 — Tarjas, numeração, sumário e certificado de integridade ✅ concluída
- Redação irreversível com regex (CPF, CNPJ, RG, telefone, e-mail, endereço,
  dados bancários) + revisão manual antes de aplicar.
- Metadados jurídicos (número CNJ, partes, datas, tipo de peça) e renomeação.
- Sumário/índice com nomeação de anexos; numeração/Bates, "Fls.", marca d'água.
- Certificado SHA-256 + relatório PDF, estrutura preparada para ICP-Brasil.

### Fase 4 — Acervo, comparador, lote e pastas de processo
- Busca full-text com destaque do trecho (Postgres FTS / SQLite FTS5).
- Comparador de versões lado a lado.
- Processamento em lote (pasta/ZIP) com fluxos salvos como presets.
- Pastas de processo/cliente com histórico de operações.

### Fase 5 — Autenticação, LGPD, polimento e Docker
- E-mail/senha + 2FA TOTP opcional, argon2, rate limiting, isolamento por usuário.
- Criptografia em repouso, expurgo 24h configurável, "Apagar agora", ClamAV opcional,
  Política de Privacidade e Termos de Uso em linguagem simples.
- Tema claro/escuro, responsividade, WCAG AA; testes completos; **docker compose up**;
  verificação final no navegador com evidências.

---

## 4. Variáveis de ambiente (`.env.example`)

| Variável | Padrão | Descrição |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./lexscan.db` | URL do banco (Postgres no compose) |
| `STORAGE_ROOT` | `./storage` | raiz do armazenamento cifrado |
| `STORAGE_SECRET` | *(obrigatória)* | chave de cifragem em repouso |
| `TASK_BACKEND` | `local` | `local` ou `celery` |
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | broker quando `TASK_BACKEND=celery` |
| `RETENTION_HOURS` | `24` | expurgo automático (LGPD) |
| `MAX_UPLOAD_MB` | `100` | limite de upload por arquivo |
| `TESSERACT_CMD` / `TESSERACT_LANGS` | auto / `por+eng` | binário e idiomas do OCR |
| `SOFFICE_CMD` | auto | binário do LibreOffice |
| `CLAMAV_ENABLED` | `false` | antivírus opcional |
| `RATE_LIMIT_PER_MIN` | `60` | limite de requisições |

---

## 5. Critérios de aceite por fase

- **Fase 1:** upload de PDF escaneado → OCR com progresso → download do PDF
  pesquisável; PDF → Blindado (sem texto selecionável, sem metadados) → download;
  testes verdes; Swagger acessível; app testado no navegador com evidências.
