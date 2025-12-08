#!/bin/bash
#
# DAPX-backandrepl - Installazione Containerizzata
# Script per installare e avviare DAPX-backandrepl in un container Docker
#

set -e

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

log_info() {
    echo -e "${CYAN}[INFO]${NC} $1"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

log_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# Verifica Docker
if ! command -v docker &> /dev/null; then
    log_error "Docker non trovato. Installa Docker prima di continuare."
    exit 1
fi

# Verifica Docker Compose
if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
    log_error "Docker Compose non trovato. Installa Docker Compose prima di continuare."
    exit 1
fi

# Determina directory di installazione
INSTALL_DIR="${1:-$(pwd)}"
DATA_DIR="${INSTALL_DIR}/data"
CONFIG_DIR="${INSTALL_DIR}/config"
LOGS_DIR="${INSTALL_DIR}/logs"
CERTS_DIR="${INSTALL_DIR}/certs"

log_info "Installazione DAPX-backandrepl in container"
log_info "Directory installazione: ${INSTALL_DIR}"

# Crea directory necessarie
log_info "Creazione directory..."
mkdir -p "${DATA_DIR}" "${CONFIG_DIR}" "${LOGS_DIR}" "${CERTS_DIR}"
chmod 755 "${DATA_DIR}" "${CONFIG_DIR}" "${LOGS_DIR}" "${CERTS_DIR}"

# Verifica chiavi SSH
if [ ! -d "${HOME}/.ssh" ] || [ ! -f "${HOME}/.ssh/id_rsa" ]; then
    log_warning "Chiavi SSH non trovate in ${HOME}/.ssh/"
    log_info "Generazione chiavi SSH..."
    ssh-keygen -t rsa -b 4096 -f "${HOME}/.ssh/id_rsa" -N "" -q || true
    log_success "Chiavi SSH generate"
fi

# Genera secret key se non esiste
if [ ! -f "${CONFIG_DIR}/.env" ]; then
    log_info "Generazione secret key..."
    SECRET_KEY=$(openssl rand -hex 32)
    cat > "${CONFIG_DIR}/.env" << EOF
DAPX_SECRET_KEY=${SECRET_KEY}
DAPX_TOKEN_EXPIRE=480
DAPX_CORS_ORIGINS=
EOF
    log_success "File di configurazione creato"
fi

# Build immagine Docker
log_info "Build immagine Docker..."
docker-compose build || docker compose build

if [ $? -eq 0 ]; then
    log_success "Immagine Docker buildata con successo"
else
    log_error "Errore durante build immagine Docker"
    exit 1
fi

# Avvia container
log_info "Avvio container..."
docker-compose up -d || docker compose up -d

if [ $? -eq 0 ]; then
    log_success "Container avviato con successo"
else
    log_error "Errore durante avvio container"
    exit 1
fi

# Attendi che il servizio sia pronto
log_info "Attesa servizio..."
sleep 5

# Verifica stato
if docker-compose ps | grep -q "Up" || docker compose ps | grep -q "Up"; then
    log_success "Container in esecuzione"
    
    # Mostra informazioni
    echo ""
    log_info "════════════════════════════════════════════════"
    log_success "Installazione completata!"
    echo ""
    log_info "Accesso Web UI:"
    echo "  http://localhost:8420"
    echo ""
    log_info "Comandi utili:"
    echo "  Visualizza log:     docker-compose logs -f"
    echo "  Ferma container:    docker-compose down"
    echo "  Riavvia container:  docker-compose restart"
    echo "  Stato container:    docker-compose ps"
    echo ""
    log_info "Directory:"
    echo "  Database:  ${DATA_DIR}"
    echo "  Config:    ${CONFIG_DIR}"
    echo "  Log:       ${LOGS_DIR}"
    echo ""
    log_info "Chiave SSH pubblica (per autorizzare sui nodi):"
    cat "${HOME}/.ssh/id_rsa.pub"
    echo ""
    log_info "════════════════════════════════════════════════"
else
    log_error "Container non in esecuzione. Controlla i log:"
    echo "  docker-compose logs"
    exit 1
fi

