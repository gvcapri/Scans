# JudiFiles — backend (FastAPI)
#
# Build a partir da RAIZ do repositório:
#   docker build -t judifiles-api -f backend/Dockerfile .
#   docker build --build-arg ENABLE_OCR=true -t judifiles-api -f backend/Dockerfile .
#
# ENABLE_OCR=true instala o binário tesseract-ocr (+ pacote de idioma por)
# na imagem; o FEATURE_OCR continua decidindo em runtime se a rota responde
# ou devolve 503. Nesta VM de 1 GB o compose builda com ENABLE_OCR=false.

FROM python:3.11-slim

WORKDIR /app

ARG ENABLE_OCR=false

# gcc só durante o pip install (libs C de dependências sem wheel);
# tesseract entra somente quando ENABLE_OCR=true.
# ghostscript (binário `gs`) é obrigatório: compressão, divisão e lote
# falham com "Ghostscript não encontrado" sem ele — antes só existia fora
# do Docker, quando o teste rodava na máquina local.
COPY backend/requirements.txt .
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        ghostscript \
        $([ "$ENABLE_OCR" = "true" ] && echo "tesseract-ocr tesseract-ocr-por") \
    && pip install --no-cache-dir -r requirements.txt \
    && apt-get purge -y gcc \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# app
COPY backend /app
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

# usuário não-root (o volume de storage é criado/chownado no compose)
RUN useradd --create-home --uid 10001 appuser \
    && mkdir -p /data/storage \
    && chown -R appuser:appuser /data/storage
USER appuser

EXPOSE 8000
# 1 worker, sem reload (VM de 1 GB)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-access-log"]
