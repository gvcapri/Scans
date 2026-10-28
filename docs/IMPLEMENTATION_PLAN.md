# JudiFiles — Plano de implementação
# (antecedente do README da LexScan; a Fase 5 trouxe autenticação, LGPD e Docker)

# 1. Arquitetura
# [isolada a arquitetura do plano anterior]

# 2. Estrutura de pastas
# [veio do plano anterior — índice de pasta]

# 3. Fases de execução
# Fase 1 — Fundação, upload/download, OCR e PDF Blindado ✅
# Fase 2 — Conversões, mesclar/dividir e compressor de tribunal ✅
# Fase 3 — Tarjas, numeração, sumário e certificado de integridade ✅
# Fase 4 — Acervo, comparador, lote e pastas de processo ✅
# Fase 5 — Autenticação, LGPD, polimento e Docker
#   * E-mail/senha + 2FA TOTP opcional, argon2, rate limiting, isolamento por usuário.
#   * Criptografia em repouso, expurgo 24h configurável, "Apagar agora", ClamAV opcional.
#   * Política de Privacidade e Termos de Uso em linguagem simples.
#   * Tema claro/escuro, responsividade, WCAG AA; testes completos; docker compose up;
#     verificação final no navegador com evidências.

# 4. Variáveis de ambiente
# | Variável | Padrão | Descrição |
# | DATABASE_URL | sqlite:///./lexscan.db | URL do banco (Postgres no compose) |
# | STORAGE_ROOT | ./storage | raiz do armazenamento cifrado |
# | STORAGE_SECRET | *(obrigatória)* | chave de cifragem em repouso |
# | TASK_BACKEND | local | local ou celery |
# | CELERY_BROKER_URL | redis://localhost:6379/0 | broker quando TASK_BACKEND=celery |
# | RETENTION_HOURS | 24 | expurgo automático (LGPD) |
# | MAX_UPLOAD_MB | 100 | limite de upload por arquivo |
# | TESSERACT_CMD / TESSERACT_LANGS | auto / por+eng | binário e idiomas do OCR |
# | SOFFICE_CMD | auto | binário do LibreOffice |
# | CLAMAV_ENABLED | false | antivírus opcional |
# | RATE_LIMIT_PER_MIN | 60 | limite de requisições |
# | AUTH_RATE_LIMIT_PER_MIN | 10 | tentativas de login/registro por minuto |
# | PURGE_INTERVAL_MINUTES | 30 | frequência do expurgo em segundo plano |

# 5. Critérios de aceite por fase
# Fase 1: upload de PDF escaneado → OCR com progresso → download do PDF pesquisável;
# PDF → Blindado (sem texto selecionável, sem metadados) → download; testes verdes;
# Swagger acessível; app testado no navegador com evidências.
# Fase 4: fluxo de upload → busca → comparador → lote → pastas de processo.
# Fase 5: login/registro/2FA, guarda de rotas, expurgo LGPD validado, e2e completo.
