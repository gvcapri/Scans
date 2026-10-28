# LexScan

Plataforma de conversão e tratamento de documentos para advogados e escritórios
de advocacia brasileiros. Envie PDF, imagens ou Word e converta, trate e
proteja documentos com foco em rotinas jurídicas: OCR, PDF Blindado,
compressão para tribunal, redação de dados, numeração e certificado de integridade.

> **Status:** Fases 1 a 3 concluídas — upload/download, OCR, PDF Blindado,
> mesclar, dividir, converter, comprimir (com perfis de tribunal e PDF/A),
> redação de dados com revisão manual, metadados CNJ + renomeação,
> numeração/Bates/Fls. com marca d'água, sumário/índice de anexos e
> certificado de integridade SHA-256. Fases 4 e 5 conforme
> `docs/IMPLEMENTATION_PLAN.md`.

---

## 1. Requisitos

| Item | Versão usada |
|---|---|
| Python | 3.11+ (testado com 3.14) |
| Node.js | 18+ (testado com 24) |
| Tesseract OCR | 5.x com idiomas `por` e `eng` |
| LibreOffice | 7+ (conversão Word → PDF) |
| Ghostscript | 9.50+ (compressão e PDF/A) |
| Docker (opcional) | entrega final da Fase 5 |

### Instalar o Tesseract (necessário para o OCR)

* **Windows:** `winget install UB-Mannheim.TesseractOCR` e baixar
  `por.traineddata` de <https://github.com/tesseract-ocr/tessdata> para dentro
  de `./tessdata` (este repositório já acompanha `tessdata/` com `por`, `eng` e `osd`).
* **Linux (Debian/Ubuntu):**
  `sudo apt install tesseract-ocr tesseract-ocr-por tesseract-ocr-eng`

O projeto já aponta `TESSDATA_PREFIX=./tessdata`, então basta ter os arquivos lá.

### LibreOffice e Ghostscript (necessários para converter e comprimir)

* **Windows:** `winget install TheDocumentFoundation.LibreOffice` e o instalador
  do Ghostscript em <https://ghostscript.com/releases/gsdnld.html>
  (o autodetecta em `C:\Program Files\gs\gs*\bin\gswin64c.exe`).
* **Linux (Debian/Ubuntu):** `sudo apt install libreoffice ghostscript`

Sem eles, OCR e blindagem continuam funcionando; só conversão Word → PDF e o
compressor ficam indisponíveis (a interface avisa).

---

## 2. Instalação (desenvolvimento local)

```bash
# 1) backend
python -m venv .venv
.venv/Scripts/pip install -r backend/requirements.txt      # Linux/macOS: .venv/bin/pip

# 2) frontend
cd frontend && npm install && cd ..

# 3) variáveis de ambiente
cp .env.example .env

# 4) subir tudo (dois terminais)
.venv/Scripts/python -m uvicorn app.main:app --app-dir backend --reload --port 8000
cd frontend && npm run dev
```

* Aplicação: <http://localhost:5173>
* Swagger/OpenAPI: <http://localhost:8000/docs>
* Health: <http://localhost:8000/api/meta/health>

> No Linux/macOS use `.venv/bin/python` no lugar de `.venv/Scripts/python`.

---

## 3. Variáveis de ambiente

Todas estão documentadas em `.env.example`. As principais:

| Variável | Padrão | Descrição |
|---|---|---|
| `DATABASE_URL` | `sqlite:///./lexscan.db` | banco (Postgres no compose) |
| `STORAGE_ROOT` | `./storage` | raiz do armazenamento **cifrado** |
| `STORAGE_SECRET` | — | chave de cifragem em repouso (gere uma nova!) |
| `TASK_BACKEND` | `local` | `local` (threads) ou `celery` (Redis) |
| `RETENTION_HOURS` | `24` | expurgo automático (LGPD) |
| `MAX_UPLOAD_MB` | `100` | limite por arquivo |
| `TESSERACT_LANGS` | `por+eng` | idiomas do OCR |
| `SOFFICE_CMD` | autodetecta | binário do LibreOffice (Word → PDF) |
| `GHOSTSCRIPT_CMD` | autodetecta | binário do Ghostscript (compressão/PDF-A) |
| `CORS_ORIGINS` | `http://localhost:5173` | origens liberadas |

Gerar uma chave de cifragem:

```bash
python -c "import secrets; print(secrets.token_urlsafe(32))"
```

---

## 4. Exemplos de uso

### 4.1 Enviar arquivo

```bash
curl -F "files=@samples/peticao_escaneada.pdf" http://localhost:8000/api/files
```

Resposta: `[{ "id": "...", "name": "...", "sha256": "...", ... }]`

### 4.2 Rodar OCR (PDF pesquisável)

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"kind":"ocr","file_ids":["<FILE_ID>"],"options":{"output":"pdf","dpi":300,"lang":"por+eng"}}'
```

Acompanhar o progresso (página a página):

```bash
curl http://localhost:8000/api/jobs/<JOB_ID>
# {"status":"running","progress":50,"page_current":1,"page_total":2,...}
```

Baixar o resultado (`output_file_ids`):

```bash
curl -OJ http://localhost:8000/api/files/<OUTPUT_ID>/download
```

### 4.3 PDF Blindado

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"kind":"blind","file_ids":["<FILE_ID>"],"options":{"dpi":300,"jpeg_quality":75,"keep_text_layer":true,"owner_password":""}}'
```

Opções: `dpi` (150/200/300), `jpeg_quality` (20–95), `keep_text_layer`
(OCR invisível por cima da imagem) e `owner_password` (bloqueia edição/cópia).

### 4.4 Mesclar, dividir, converter e comprimir (Fase 2)

Mesclagem com reordenação (a ordem de `file_ids` é a ordem do PDF final,
com 2 a 50 arquivos):

```bash
curl -X POST http://localhost:8000/api/jobs \
  -H "Content-Type: application/json" \
  -d '{"kind":"merge","file_ids":["<A>","<B>"],"options":{"bookmarks":true}}'
```

Dividir por intervalo, extrair páginas ou cortar em blocos:

```bash
# cada intervalo vira um arquivo
-d '{"kind":"split","file_ids":["<ID>"],"options":{"mode":"ranges","ranges":"1-5,8,10-12"}}'
# páginas escolhidas num único PDF
-d '{"kind":"split","file_ids":["<ID>"],"options":{"mode":"extract","ranges":"2,4-6"}}'
# blocos de 10 páginas
-d '{"kind":"split","file_ids":["<ID>"],"options":{"mode":"every","every":10}}'
```

Conversões (a direção é escolhida pelo `target` ou detectada pela extensão):

```bash
-d '{"kind":"convert","file_ids":["<ID>"],"options":{"target":"pdf"}}'   # imagem/Word → PDF
-d '{"kind":"convert","file_ids":["<ID>"],"options":{"target":"png","dpi":200}}'  # PDF → PNG (ZIP se várias páginas)
-d '{"kind":"convert","file_ids":["<ID>"],"options":{"target":"txt"}}'    # PDF → TXT/DOCX
```

Compressor com limite do tribunal, divisão automática e PDF/A:

```bash
-d '{"kind":"compress","file_ids":["<ID>"],"options":{"limit_mb":10,"quality":"ebook","split":true,"pdfa":false}}'
```

`limit_mb=0` desliga o limite; se o arquivo não couber e `split=true`, o job
gera `..._parte_1.pdf`, `..._parte_2.pdf`… cada um dentro do limite.
`pdfa=true` grava PDF/A-2b (Ghostscript + perfil ICC sRGB).

### 4.5 Perfis de tribunal (presets)

```bash
curl "http://localhost:8000/api/presets?tool=compress"      # embutidos + salvos
curl -X POST http://localhost:8000/api/presets \
  -H "Content-Type: application/json" \
  -d '{"tool":"compress","name":"Meu Tribunal — 7 MB","options":{"limit_mb":7,"quality":"printer","pdfa":true,"split":true}}'
curl -X DELETE http://localhost:8000/api/presets/<PRESET_ID>
```

Os embutidos (PJe, e-SAJ, e-Proc, Projudi, e-mail 2 MB) trazem limites de
referência publicados pelos sistemas — **confirme o valor exigido pelo seu
tribunal** antes de protocolar; é possível editar e salvar o próprio perfil.

### 4.6 Redigir, metadados, numerar, sumário e certificado (Fase 3)

Redação em duas etapas — primeiro a **revisão** (lista os achados para o
usuário marcar), depois o job com os termos aprovados:

```bash
# 1) revisão: quais dados sensíveis existem no PDF?
curl -X POST http://localhost:8000/api/redact/scan \
  -H "Content-Type: application/json" \
  -d '{"file_id":"<FILE_ID>"}'
# → {"groups":[{"type":"cpf","label":"CPF","value":"...","count":1,...}], ...}

# 2) aplicar a tarja de forma irreversível (modo: black | white)
-d '{"kind":"redact","file_ids":["<ID>"],"options":{"terms":["529.982.247-25"],"mode":"black"}}'
# sem `terms`, o backend auto-detecta pelos tipos de `types`
```

Metadados jurídicos + renomeação (CNJ validado no formato
`NNNNNNN-DD.AAAA.J.TR.OOOO`):

```bash
-d '{"kind":"metadata","file_ids":["<ID>"],"options":{"cnj":"0000001-10.2026.8.01.0001","tipo":"Contestação","autor":"João da Silva","reu":"Transportes Ltda","data":"2026-10-28"}}'
```

Numeração, carimbo "Fls.", Bates e marca d'água (`pages` usa a mesma
sintaxe do Dividir; vazio = todas as páginas):

```bash
-d '{"kind":"number","file_ids":["<ID>"],"options":{"style":"bates","prefix":"PROC","start":1,"pad":6,"position":"bottom-center","watermark":"USO JUDICIAL","watermark_opacity":0.15}}'
# styles: "fls" (Fls. 001) | "bates" (PREFIXO000001) | "plain" (1, 2, 3...)
```

Sumário/índice com nomeação de anexos (as páginas são do documento
original; o deslocamento pelo índice é automático):

```bash
-d '{"kind":"outline","file_ids":["<ID>"],"options":{"title":"ÍNDICE","insert_index":true,"bookmarks":true,"entries":[{"label":"ANEXO I — Procuração","page":1}]}}'
# entries vazio = deriva dos bookmarks já existentes no PDF
```

Certificado de integridade (1 a 20 arquivos por job):

```bash
-d '{"kind":"integrity","file_ids":["<A>","<B>"],"options":{"emitente":"Escritório Silva","observacao":"Processo 123..."}}'
# gera certificado_integridade_<data>.pdf com o SHA-256 de cada arquivo
```

### 4.7 Apagar um arquivo agora (LGPD)

```bash
curl -X DELETE http://localhost:8000/api/files/<FILE_ID>
```

### 4.8 Amostras e verificações

```bash
.venv/Scripts/python scripts/make_samples.py   # gera PDFs de exemplo em ./samples
.venv/Scripts/python -m pytest                 # testes dos módulos críticos
.venv/Scripts/python scripts/e2e_check.py      # teste no navegador + evidências
```

---

## 5. Estrutura do projeto

```
├── docs/IMPLEMENTATION_PLAN.md   # arquitetura, pastas e fases
├── backend/
│   ├── app/
│   │   ├── main.py               # app FastAPI + OpenAPI
│   │   ├── core/                 # config, logging sem conteúdo, runner de jobs
│   │   ├── db/                   # modelos (User, StoredFile, Job, CaseFolder)
│   │   ├── api/routes/           # files, jobs, meta, presets, redact
│   │   ├── services/             # ocr, blind, merge, split, convert, compress,
│   │   │                         # redact, number, outline, metadata, integrity,
│   │   │                         # storage cifrado, validação, hash
│   │   └── workers/              # execução de jobs + tarefas Celery
│   └── tests/                    # OCR, blindagem, hash, validação, API
├── frontend/                     # React + Vite + Tailwind (pt-BR, claro/escuro)
├── scripts/                      # amostras e verificação no navegador
├── tessdata/                     # idiomas do Tesseract (por, eng, osd)
└── evidence/                     # screenshots da verificação no navegador
```

---

## 6. Segurança e LGPD (implementado na Fase 1)

* Arquivos cifrados em repouso (Fernet/AES) por usuário, em pasta isolada.
* Nome de arquivo nunca vira caminho de disco (anti path traversal).
* Upload validado por **magic bytes** reais, limite de tamanho e extensão coerente.
* Logs nunca contêm conteúdo de documento (filtro automático).
* Downloads servidos em streaming descriptografado, com `Cache-Control: no-store`.
* Botão **“Apagar agora”** remove o arquivo imediatamente; expurgo automático de
  24 h configurável por `RETENTION_HOURS` (Fase 5).

---

## 7. Testes

```bash
cd backend && python -m pytest
```

Cobertura dos módulos críticos: OCR (PDF pesquisável, TXT, DOCX, deskew,
normalização de opções), blindagem (achatamento, metadados, permissões,
camada pesquisável), hash SHA-256, validação de uploads, mesclagem (ordem e
sumário), divisão (intervalos, extração, blocos), conversões (imagem, Word,
PDF → imagens/texto), compressão (redução, divisão automática, PDF/A) e
Fase 3 (detecção por regex com validação CPF/CNPJ/Luhn, tarja irreversível,
numeração/Bates/marca d'água, índice com deslocamento de páginas,
metadados CNJ e certificado SHA-256), além dos fluxos ponta a ponta da API
(84 testes).

Verificação no navegador (Playwright/Chromium): 47 checagens cobrem as
onze ferramentas ativas, com screenshots e PDFs gerados em `./evidence`.

---

## 8. Documentação da API

A especificação OpenAPI é servida em `/openapi.json` e a interface interativa
em `/docs` (Swagger). Tags: `arquivos`, `jobs`, `meta`, `perfis`, `redact`.
