#!/bin/bash
#
# DAPX-backandrepl - Script di Aggiornamento
# Aggiorna installazioni esistenti (standard o container LXC)
#

set -e

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
NC='\033[0m'
BOLD='\033[1m'

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

# Configurazione
GITHUB_REPO="grandir66/dapx-backandrepl"
GITHUB_BRANCH="main"

# Directory installazione (rileva automaticamente)
if [ -d "/opt/dapx-backandrepl" ]; then
    INSTALL_DIR="/opt/dapx-backandrepl"
elif [ -d "/opt/sanoid-manager" ]; then
    INSTALL_DIR="/opt/sanoid-manager"
else
    INSTALL_DIR="/opt/dapx-backandrepl"
fi

# Servizio
SERVICE_NAME="dapx-backandrepl"
if ! systemctl list-unit-files | grep -q "${SERVICE_NAME}"; then
    SERVICE_NAME="sanoid-manager"
fi

log_info "════════════════════════════════════════════════"
log_info "${BOLD}DAPX-backandrepl - Aggiornamento${NC}"
log_info "════════════════════════════════════════════════"
echo ""

# Verifica permessi root
if [ "$EUID" -ne 0 ]; then 
    log_error "Questo script deve essere eseguito come root"
    exit 1
fi

# Rileva tipo installazione
log_info "Rilevamento installazione..."
echo "  Directory: ${INSTALL_DIR}"
echo "  Servizio: ${SERVICE_NAME}"

# Verifica che l'installazione esista
if [ ! -d "${INSTALL_DIR}" ]; then
    log_error "Directory installazione non trovata: ${INSTALL_DIR}"
    log_info "Sei sicuro che il sistema sia installato?"
    exit 1
fi

# Backup configurazione
log_info "Backup configurazione..."
BACKUP_DIR="/tmp/dapx-backup-$(date +%Y%m%d_%H%M%S)"
mkdir -p ${BACKUP_DIR}

# Backup database
if [ -f "/var/lib/dapx-backandrepl/dapx-backandrepl.db" ]; then
    cp /var/lib/dapx-backandrepl/dapx-backandrepl.db ${BACKUP_DIR}/ 2>/dev/null || true
fi
if [ -f "/var/lib/sanoid-manager/sanoid-manager.db" ]; then
    cp /var/lib/sanoid-manager/sanoid-manager.db ${BACKUP_DIR}/ 2>/dev/null || true
fi

# Backup .env
if [ -f "/etc/dapx-backandrepl/.env" ]; then
    cp /etc/dapx-backandrepl/.env ${BACKUP_DIR}/ 2>/dev/null || true
fi

log_success "Backup salvato in: ${BACKUP_DIR}"

# Ferma servizio
log_info "Fermata servizio..."
systemctl stop ${SERVICE_NAME} 2>/dev/null || true

# Aggiorna codice
log_info "Aggiornamento codice da GitHub..."
cd ${INSTALL_DIR}

if [ -d ".git" ]; then
    # Repository Git esistente
    git fetch origin ${GITHUB_BRANCH}
    git reset --hard origin/${GITHUB_BRANCH}
    git pull origin ${GITHUB_BRANCH}
else
    # Non è un repository Git, scarica nuova versione
    log_warning "Non è un repository Git. Download nuova versione..."
    cd /tmp
    rm -rf dapx-update
    git clone --depth 1 --branch ${GITHUB_BRANCH} https://github.com/${GITHUB_REPO}.git dapx-update
    
    # Copia nuovi file
    rsync -av --exclude='.git' /tmp/dapx-update/ ${INSTALL_DIR}/
    rm -rf /tmp/dapx-update
fi

log_success "Codice aggiornato"

# Aggiorna dipendenze Python
log_info "Aggiornamento dipendenze Python..."
cd ${INSTALL_DIR}/backend
pip3 install --no-cache-dir -r requirements.txt --upgrade 2>/dev/null || \
pip install --no-cache-dir -r requirements.txt --upgrade

log_success "Dipendenze aggiornate"

# Aggiorna frontend
log_info "Aggiornamento frontend..."
if [ -d "${INSTALL_DIR}/frontend/dist" ]; then
    log_success "Frontend aggiornato"
fi

# Riavvia servizio
log_info "Riavvio servizio..."
systemctl daemon-reload
systemctl start ${SERVICE_NAME}

# Verifica servizio
sleep 3
if systemctl is-active --quiet ${SERVICE_NAME}; then
    log_success "Servizio avviato correttamente"
else
    log_error "Errore avvio servizio. Controlla i log:"
    echo "  journalctl -u ${SERVICE_NAME} -n 50"
    exit 1
fi

# Mostra versione
VERSION=$(grep -oP 'version.*".*?"' ${INSTALL_DIR}/backend/main.py 2>/dev/null | head -1 || echo "N/A")
log_success "════════════════════════════════════════════════"
log_success "Aggiornamento completato!"
echo ""
log_info "Backup salvato in: ${BACKUP_DIR}"
log_info "Log servizio: journalctl -u ${SERVICE_NAME} -f"
log_success "════════════════════════════════════════════════"
