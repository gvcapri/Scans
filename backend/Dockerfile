# JudiFiles — backend (FastAPI)
#
# Construção com cache (usar --build-arg PYDeps=... para repintar
# requirements apenas quando mudarem):
#   docker build -t judifiles-api -f backend/Dockerfile .
#
# Rodar:
#   docker run --env-file .env -p 8000:8000 judifiles-api
#
FROM python:3.11-slim AS build

WORKDIR /app

# instala dependências do sistema (se precisar de libs C extras)
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# copiar requirements e instalar (cached)
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# app
COPY backend /app
ENV PYTHONUNBUFFERED=1
ENV PYTHONDONTWRITEBYTECODE=1

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
