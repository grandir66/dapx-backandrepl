#!/bin/bash
#
# DAPX-backandrepl - Deploy Automatico Container LXC
# Script completo che scarica da GitHub e crea tutto automaticamente
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

log_step() {
    echo -e "\n${BLUE}${BOLD}▶ $1${NC}"
}

# ============== CONFIGURAZIONE ==============
GITHUB_REPO="grandir66/dapx-backandrepl"
GITHUB_BRANCH="main"
WORK_DIR="/root/dapx-lxc-deploy"

# Parametri container (modificabili)
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

# Template Debian
TEMPLATE="debian-12-standard_12.0-1_amd64.tar.zst"

log_info "════════════════════════════════════════════════"
log_info "${BOLD}DAPX-backandrepl - Deploy Automatico LXC${NC}"
log_info "════════════════════════════════════════════════"
echo ""

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
    log_warning "Usa un ID diverso o elimina il container esistente:"
    echo "  pct destroy ${CTID}"
    exit 1
fi

# ============== STEP 1: Preparazione ambiente ==============
log_step "Step 1/5: Preparazione ambiente"

# Crea directory lavoro
mkdir -p ${WORK_DIR}
cd ${WORK_DIR}

# Installa git se necessario
if ! command -v git &> /dev/null; then
    log_info "Installazione git..."
    apt-get update -qq
    apt-get install -y git > /dev/null 2>&1
fi

log_success "Ambiente preparato"

# ============== STEP 2: Download da GitHub ==============
log_step "Step 2/5: Download file da GitHub"

log_info "Repository: https://github.com/${GITHUB_REPO}"
log_info "Branch: ${GITHUB_BRANCH}"

# Clona o aggiorna repository
if [ -d "${WORK_DIR}/dapx-backandrepl" ]; then
    log_info "Repository già presente, aggiornamento..."
    cd ${WORK_DIR}/dapx-backandrepl
    git fetch origin > /dev/null 2>&1 || true
    git reset --hard origin/${GITHUB_BRANCH} > /dev/null 2>&1 || true
    git pull origin ${GITHUB_BRANCH} > /dev/null 2>&1 || true
else
    log_info "Clone repository..."
    cd ${WORK_DIR}
    git clone --depth 1 --branch ${GITHUB_BRANCH} \
        https://github.com/${GITHUB_REPO}.git > /dev/null 2>&1
fi

if [ ! -d "${WORK_DIR}/dapx-backandrepl/lxc" ]; then
    log_error "Directory lxc non trovata nel repository!"
    exit 1
fi

cd ${WORK_DIR}/dapx-backandrepl/lxc
chmod +x *.sh

log_success "File scaricati da GitHub"

# ============== STEP 3: Verifica prerequisiti ==============
log_step "Step 3/5: Verifica prerequisiti"

# Verifica storage
if ! pvesm status | grep -q "${STORAGE}"; then
    log_warning "Storage '${STORAGE}' non trovato. Storage disponibili:"
    pvesm status | grep -E "active|enabled" | awk '{print "  - " $1}'
    log_error "Modifica lo script o crea lo storage '${STORAGE}'"
    exit 1
fi

# Verifica bridge
if ! ip addr show | grep -q "${NETWORK_BRIDGE}:"; then
    log_warning "Bridge '${NETWORK_BRIDGE}' non trovato. Bridge disponibili:"
    ip addr show | grep -E "^[0-9]+:.*:" | awk '{print "  - " $2}' | tr -d ':'
    log_error "Modifica lo script o usa un bridge esistente"
    exit 1
fi

# Verifica template - prima cerca template già presenti
if [ ! -f "/var/lib/vz/template/cache/${TEMPLATE}" ]; then
    log_warning "Template ${TEMPLATE} non trovato."
    
    # Cerca template Debian già presenti
    EXISTING_TEMPLATE=$(ls -t /var/lib/vz/template/cache/debian*.tar.zst 2>/dev/null | head -1)
    if [ -n "${EXISTING_TEMPLATE}" ]; then
        TEMPLATE=$(basename ${EXISTING_TEMPLATE})
        log_success "Trovato template esistente: ${TEMPLATE}"
    else
        # Nessun template presente, prova a scaricarne uno
        log_info "Nessun template Debian trovato. Tentativo download..."
        
        # Aggiorna repository template
        log_info "Aggiornamento repository template..."
        pveam update > /dev/null 2>&1 || true
        
        # Lista template disponibili
        log_info "Template Debian disponibili:"
        pveam available --section system 2>/dev/null | grep -i debian | head -5 || echo "  Nessun template Debian disponibile"
        echo ""
        
        # Prova a scaricare template Debian
        log_info "Tentativo download template Debian..."
        
        # Lista di template da provare (in ordine di preferenza)
        TEMPLATES_TO_TRY=(
            "debian-12-standard"
            "debian-11-standard"
            "debian-10-standard"
            "ubuntu-22.04-standard"
            "ubuntu-20.04-standard"
        )
        
        DOWNLOADED=0
        for TEMPLATE_NAME in "${TEMPLATES_TO_TRY[@]}"; do
            log_info "Tentativo: ${TEMPLATE_NAME}..."
            if pveam download local "${TEMPLATE_NAME}" 2>/dev/null; then
                log_success "Template scaricato: ${TEMPLATE_NAME}"
                # Trova il file scaricato
                DOWNLOADED_TEMPLATE=$(ls -t /var/lib/vz/template/cache/${TEMPLATE_NAME}*.tar.zst 2>/dev/null | head -1)
                if [ -n "${DOWNLOADED_TEMPLATE}" ]; then
                    TEMPLATE=$(basename ${DOWNLOADED_TEMPLATE})
                    log_info "Usando template: ${TEMPLATE}"
                    DOWNLOADED=1
                    break
                fi
            fi
        done
        
        if [ ${DOWNLOADED} -eq 0 ]; then
            log_error "Impossibile scaricare template automaticamente."
            echo ""
            log_info "Template disponibili nel sistema:"
            ls -lh /var/lib/vz/template/cache/*.tar.zst 2>/dev/null | head -5 || echo "  Nessun template trovato"
            echo ""
            log_info "Istruzioni:"
            echo "1. Aggiorna repository: pveam update"
            echo "2. Lista template: pveam available --section system | grep debian"
            echo "3. Scarica template: pveam download local <nome-template>"
            echo ""
            log_info "Oppure usa uno script helper:"
            echo "  wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/find-template.sh"
            echo "  chmod +x find-template.sh"
            echo "  ./find-template.sh"
            exit 1
        fi
    fi
fi

# Verifica finale che il template esista
if [ ! -f "/var/lib/vz/template/cache/${TEMPLATE}" ]; then
    log_error "Template ${TEMPLATE} non trovato in /var/lib/vz/template/cache/"
    exit 1
fi

log_success "Template verificato: ${TEMPLATE}"

log_success "Prerequisiti verificati"

# ============== STEP 4: Creazione container ==============
log_step "Step 4/5: Creazione container LXC"

log_info "Parametri container:"
echo "  ID: ${CTID}"
echo "  Nome: ${CT_NAME}"
echo "  Storage: ${STORAGE}"
echo "  Rootfs: ${ROOTFS_SIZE}"
echo "  Memoria: ${MEMORY} MB"
echo "  CPU: ${CORES} cores"
echo "  Bridge: ${NETWORK_BRIDGE}"
echo "  IP: ${IP_ADDRESS}"

# Crea container usando lo script
log_info "Creazione container..."
${WORK_DIR}/dapx-backandrepl/lxc/create-lxc-container.sh \
    ${CTID} \
    ${CT_NAME} \
    ${STORAGE} \
    ${ROOTFS_SIZE} \
    ${MEMORY} \
    ${CORES} \
    ${NETWORK_BRIDGE} \
    ${IP_ADDRESS} \
    "${GATEWAY}" \
    "${DNS_SERVERS}" \
    "" \
    ""

if [ $? -ne 0 ]; then
    log_error "Errore durante creazione container"
    exit 1
fi

log_success "Container creato"

# ============== STEP 5: Installazione applicazione ==============
log_step "Step 5/5: Installazione applicazione"

log_info "Copia script installazione nel container..."

# Copia script installazione
pct push ${CTID} \
    ${WORK_DIR}/dapx-backandrepl/lxc/install-in-lxc.sh \
    /tmp/dapx-install/install.sh

pct exec ${CTID} -- chmod +x /tmp/dapx-install/install.sh

log_info "Esecuzione installazione (questo può richiedere alcuni minuti)..."

# Esegui installazione
pct exec ${CTID} -- /tmp/dapx-install/install.sh

if [ $? -ne 0 ]; then
    log_error "Errore durante installazione"
    log_warning "Puoi provare manualmente:"
    echo "  pct exec ${CTID} -- /tmp/dapx-install/install.sh"
    exit 1
fi

log_success "Applicazione installata"

# ============== Verifica finale ==============
log_step "Verifica installazione"

# Attendi che il servizio sia pronto
sleep 3

# Verifica stato container
if ! pct status ${CTID} | grep -q "running"; then
    log_warning "Container non in esecuzione. Avvio..."
    pct start ${CTID}
    sleep 3
fi

# Verifica servizio
if pct exec ${CTID} -- systemctl is-active --quiet dapx-backandrepl; then
    log_success "Servizio dapx-backandrepl attivo"
else
    log_warning "Servizio non attivo. Controlla i log:"
    echo "  pct exec ${CTID} -- journalctl -u dapx-backandrepl -n 50"
fi

# Ottieni IP
CONTAINER_IP=$(pct exec ${CTID} -- hostname -I | awk '{print $1}')

# ============== Riepilogo finale ==============
echo ""
log_success "════════════════════════════════════════════════"
log_success "${BOLD}Deploy completato con successo!${NC}"
log_success "════════════════════════════════════════════════"
echo ""
log_info "${BOLD}Informazioni Container:${NC}"
echo "  ID: ${CTID}"
echo "  Nome: ${CT_NAME}"
echo "  IP: ${CONTAINER_IP}"
echo "  Porta: 8420"
echo ""
log_info "${BOLD}Accesso Web UI:${NC}"
echo "  http://${CONTAINER_IP}:8420"
echo ""
log_info "${BOLD}Comandi utili:${NC}"
echo "  Stato container:     pct status ${CTID}"
echo "  Log servizio:        pct exec ${CTID} -- journalctl -u dapx-backandrepl -f"
echo "  Entra nel container: pct enter ${CTID}"
echo "  Gestione completa:   ${WORK_DIR}/dapx-backandrepl/lxc/manage-lxc.sh ${CTID} <azione>"
echo ""
log_info "${BOLD}File di gestione:${NC}"
echo "  Directory: ${WORK_DIR}/dapx-backandrepl/lxc/"
echo "  Script gestione: ${WORK_DIR}/dapx-backandrepl/lxc/manage-lxc.sh"
echo ""
log_success "════════════════════════════════════════════════"

