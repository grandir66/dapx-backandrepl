# DAPX-backandrepl - Dockerfile
# Multi-stage build per ottimizzare dimensioni immagine

# ============== Stage 1: Build ==============
FROM python:3.11-slim as builder

WORKDIR /build

# Installa dipendenze di build
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc \
    g++ \
    make \
    libc6-dev \
    && rm -rf /var/lib/apt/lists/*

# Copia requirements e installa dipendenze
COPY backend/requirements.txt .
RUN pip install --no-cache-dir --user -r requirements.txt

# ============== Stage 2: Runtime ==============
FROM python:3.11-slim

# Metadati
LABEL maintainer="Domarc S.r.l. <info@domarc.it>"
LABEL description="DAPX-backandrepl - Sistema centralizzato di backup e replica per Proxmox VE"
LABEL version="3.5.3"

# Variabili d'ambiente
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    DAPX_DB=/data/dapx-backandrepl.db \
    DAPX_PORT=8420 \
    DAPX_LOG_LEVEL=INFO

# Crea utente non-root
RUN groupadd -r dapx && useradd -r -g dapx -u 1000 dapx

# Installa dipendenze runtime minime
RUN apt-get update && apt-get install -y --no-install-recommends \
    openssh-client \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Crea directory
RUN mkdir -p /app /data /logs /config && \
    chown -R dapx:dapx /app /data /logs /config

WORKDIR /app

# Copia dipendenze Python da builder
COPY --from=builder /root/.local /home/dapx/.local

# Copia codice applicazione
COPY backend/ ./backend/
COPY frontend/dist/ ./frontend/dist/
# Copia file VERSION per la versione
COPY VERSION ./VERSION

# Imposta PATH per Python packages e PYTHONPATH
ENV PATH=/home/dapx/.local/bin:$PATH \
    PYTHONPATH=/app

# Cambia proprietario
RUN chown -R dapx:dapx /app

# Passa a utente non-root
USER dapx

# Esponi porta
EXPOSE 8420

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8420/api/health')" || exit 1

# Entry point
WORKDIR /app
ENTRYPOINT ["python", "-m", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8420"]

