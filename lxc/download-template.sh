#!/bin/bash
#
# Helper script per scaricare template Debian per LXC
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

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

log_info "════════════════════════════════════════════════"
log_info "Download Template Debian per LXC"
log_info "════════════════════════════════════════════════"
echo ""

# Verifica che pveam esista
if ! command -v pveam &> /dev/null; then
    log_error "pveam non trovato. Questo script deve essere eseguito su un nodo Proxmox."
    exit 1
fi

# Lista template disponibili
log_info "Template Debian disponibili:"
echo ""
pveam available --section system | grep -i debian | head -10
echo ""

# Prova a scaricare template Debian 12
log_info "Tentativo download template Debian 12..."
if pveam download local debian-12-standard; then
    log_success "Template debian-12-standard scaricato!"
    TEMPLATE=$(ls -t /var/lib/vz/template/cache/debian-12-standard*.tar.zst 2>/dev/null | head -1)
    if [ -n "${TEMPLATE}" ]; then
        log_info "File: $(basename ${TEMPLATE})"
        log_info "Dimensione: $(du -h ${TEMPLATE} | cut -f1)"
    fi
    exit 0
fi

# Prova Debian 11
log_info "Tentativo download template Debian 11..."
if pveam download local debian-11-standard; then
    log_success "Template debian-11-standard scaricato!"
    TEMPLATE=$(ls -t /var/lib/vz/template/cache/debian-11-standard*.tar.zst 2>/dev/null | head -1)
    if [ -n "${TEMPLATE}" ]; then
        log_info "File: $(basename ${TEMPLATE})"
        log_info "Dimensione: $(du -h ${TEMPLATE} | cut -f1)"
    fi
    exit 0
fi

# Se fallisce, mostra istruzioni
log_error "Impossibile scaricare template automaticamente."
echo ""
log_info "Scarica manualmente un template:"
echo ""
echo "1. Vedi template disponibili:"
echo "   pveam available --section system | grep debian"
echo ""
echo "2. Scarica un template (esempio):"
echo "   pveam download local debian-12-standard"
echo ""
echo "3. Verifica template scaricati:"
echo "   ls -lh /var/lib/vz/template/cache/"
echo ""


