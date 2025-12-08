#!/bin/bash
#
# DAPX-backandrepl - Script creazione container LXC per Proxmox
# Crea un container LXC con l'applicazione preinstallata
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

# ============== CONFIGURAZIONE ==============
CTID="${1:-100}"
CT_NAME="${2:-dapx-backandrepl}"
STORAGE="${3:-local-lvm}"
ROOTFS_SIZE="${4:-8G}"
MEMORY="${5:-1024}"
CORES="${6:-2}"
NETWORK_BRIDGE="${7:-vmbr0}"
IP_ADDRESS="${8:-dhcp}"
GATEWAY="${9:-}"
DNS_SERVERS="${10:-8.8.8.8 8.8.4.4}"
PASSWORD="${11:-}"
SSH_PUBLIC_KEY="${12:-}"

# Template da usare (Debian 12 Bookworm)
TEMPLATE="debian-12-standard_12.0-1_amd64.tar.zst"

# Directory script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INSTALL_SCRIPT="${SCRIPT_DIR}/install-in-lxc.sh"

log_info "════════════════════════════════════════════════"
log_info "Creazione Container LXC: ${CT_NAME} (ID: ${CTID})"
log_info "════════════════════════════════════════════════"

# Verifica permessi root
if [ "$EUID" -ne 0 ]; then 
    log_error "Questo script deve essere eseguito come root"
    exit 1
fi

# Verifica che pct esista
if ! command -v pct &> /dev/null; then
    log_error "pct non trovato. Questo script deve essere eseguito su un nodo Proxmox."
    exit 1
fi

# Verifica che il CTID non esista già
if pct list | grep -q "^${CTID} "; then
    log_error "Container con ID ${CTID} già esistente!"
    exit 1
fi

# Verifica template
if [ ! -f "/var/lib/vz/template/cache/${TEMPLATE}" ]; then
    log_warning "Template ${TEMPLATE} non trovato. Download..."
    pveam download local ${TEMPLATE%.tar.zst} || {
        log_error "Impossibile scaricare template. Verifica connessione internet."
        exit 1
    }
fi

log_info "Creazione container LXC..."

# Crea container
pct create ${CTID} \
    /var/lib/vz/template/cache/${TEMPLATE} \
    --storage ${STORAGE} \
    --rootfs ${STORAGE}:${ROOTFS_SIZE} \
    --hostname ${CT_NAME} \
    --memory ${MEMORY} \
    --cores ${CORES} \
    --net0 name=eth0,bridge=${NETWORK_BRIDGE},ip=${IP_ADDRESS},gw=${GATEWAY} \
    --nameserver "${DNS_SERVERS}" \
    --unprivileged 0 \
    --features nesting=1,keyctl=1 \
    --ostype debian \
    --arch amd64 \
    --password "${PASSWORD}" \
    --ssh-public-keys "${SSH_PUBLIC_KEY}" \
    --start 0

if [ $? -ne 0 ]; then
    log_error "Errore durante creazione container"
    exit 1
fi

log_success "Container creato con successo"

# Configura container
log_info "Configurazione container..."

# Abilita features necessarie
pct set ${CTID} -features nesting=1,keyctl=1

# Monta directory per dati persistenti
pct set ${CTID} -mp0 ${STORAGE}:8,mp=/var/lib/dapx-backandrepl,backup=1

# Avvia container
log_info "Avvio container..."
pct start ${CTID}

# Attendi che il container sia pronto
log_info "Attesa container pronto..."
sleep 5

# Verifica che il container sia in esecuzione
if ! pct status ${CTID} | grep -q "running"; then
    log_error "Container non in esecuzione"
    exit 1
fi

log_success "Container avviato"

# Copia script di installazione nel container
log_info "Preparazione installazione applicazione..."

# Crea directory temporanea nel container
pct exec ${CTID} -- mkdir -p /tmp/dapx-install

# Copia script di installazione
if [ -f "${INSTALL_SCRIPT}" ]; then
    pct push ${CTID} "${INSTALL_SCRIPT}" /tmp/dapx-install/install.sh
    pct exec ${CTID} -- chmod +x /tmp/dapx-install/install.sh
else
    log_warning "Script di installazione non trovato. Installazione manuale richiesta."
fi

# Informazioni finali
log_success "════════════════════════════════════════════════"
log_success "Container LXC creato con successo!"
echo ""
log_info "ID Container: ${CTID}"
log_info "Nome: ${CT_NAME}"
log_info "Storage: ${STORAGE}"
log_info "Memoria: ${MEMORY} MB"
log_info "CPU: ${CORES} cores"
echo ""
log_info "Per completare l'installazione:"
echo "  pct exec ${CTID} -- /tmp/dapx-install/install.sh"
echo ""
log_info "Per accedere al container:"
echo "  pct enter ${CTID}"
echo ""
log_info "Per avviare/fermare:"
echo "  pct start ${CTID}"
echo "  pct stop ${CTID}"
echo ""
log_info "Per esportare il container:"
echo "  vzdump ${CTID} --storage ${STORAGE} --compress zstd"
echo ""
log_success "════════════════════════════════════════════════"

