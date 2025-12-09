#!/bin/bash
#
# DAPX-backandrepl - Esporta container LXC come template
# Crea un backup del container che può essere usato come template
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

# ============== CONFIGURAZIONE ==============
CTID="${1:-100}"
STORAGE="${2:-local}"
BACKUP_DIR="${3:-/var/lib/vz/dump}"
COMPRESS="${4:-zstd}"

log_info "════════════════════════════════════════════════"
log_info "Esportazione Container LXC: ${CTID}"
log_info "════════════════════════════════════════════════"

# Verifica permessi root
if [ "$EUID" -ne 0 ]; then 
    log_error "Questo script deve essere eseguito come root"
    exit 1
fi

# Verifica che vzdump esista
if ! command -v vzdump &> /dev/null; then
    log_error "vzdump non trovato. Questo script deve essere eseguito su un nodo Proxmox."
    exit 1
fi

# Verifica che il container esista
if ! pct list | grep -q "^${CTID} "; then
    log_error "Container con ID ${CTID} non trovato!"
    exit 1
fi

# Crea directory backup
mkdir -p ${BACKUP_DIR}

# Ferma container se in esecuzione
if pct status ${CTID} | grep -q "running"; then
    log_info "Fermata container per backup..."
    pct stop ${CTID}
    STOPPED=1
else
    STOPPED=0
fi

# Crea backup
log_info "Creazione backup..."
vzdump ${CTID} \
    --storage ${STORAGE} \
    --dumpdir ${BACKUP_DIR} \
    --compress ${COMPRESS} \
    --mode snapshot \
    --remove 0

if [ $? -ne 0 ]; then
    log_error "Errore durante creazione backup"
    # Riavvia container se era in esecuzione
    if [ ${STOPPED} -eq 1 ]; then
        pct start ${CTID}
    fi
    exit 1
fi

# Riavvia container se era in esecuzione
if [ ${STOPPED} -eq 1 ]; then
    log_info "Riavvio container..."
    pct start ${CTID}
fi

# Trova file backup creato
BACKUP_FILE=$(ls -t ${BACKUP_DIR}/vzdump-lxc-${CTID}-*.tar.${COMPRESS} 2>/dev/null | head -1)

if [ -z "${BACKUP_FILE}" ]; then
    log_error "File backup non trovato"
    exit 1
fi

log_success "════════════════════════════════════════════════"
log_success "Backup creato con successo!"
echo ""
log_info "File backup: ${BACKUP_FILE}"
log_info "Dimensione: $(du -h ${BACKUP_FILE} | cut -f1)"
echo ""
log_info "Per ripristinare il backup:"
echo "  pct restore <NEW_CTID> ${BACKUP_FILE} --storage ${STORAGE}"
echo ""
log_info "Per creare un template:"
echo "  mv ${BACKUP_FILE} /var/lib/vz/template/cache/dapx-backandrepl-template.tar.${COMPRESS}"
echo ""
log_success "════════════════════════════════════════════════"



