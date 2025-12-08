#!/bin/bash
#
# DAPX-backandrepl - Deploy Automatico Container LXC
# Script completo per Proxmox con selezione interattiva del template
#

set -e

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
MAGENTA='\033[0;35m'
NC='\033[0m'
BOLD='\033[1m'

log_info() { echo -e "${CYAN}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }
log_step() { echo -e "\n${BLUE}${BOLD}▶ $1${NC}"; }

# ============== CONFIGURAZIONE ==============
GITHUB_REPO="grandir66/dapx-backandrepl"
GITHUB_BRANCH="main"
WORK_DIR="/root/dapx-lxc-deploy"

# Parametri container (modificabili via argomenti)
CTID="${1:-}"
CT_NAME="${2:-dapx-backandrepl}"
STORAGE="${3:-}"
ROOTFS_SIZE="${4:-8G}"
MEMORY="${5:-1024}"
CORES="${6:-2}"
NETWORK_BRIDGE="${7:-}"
IP_ADDRESS="${8:-dhcp}"

# Template selezionato
SELECTED_TEMPLATE=""

# ============== FUNZIONI ==============

print_banner() {
    echo -e "${CYAN}"
    echo "╔════════════════════════════════════════════════════════════╗"
    echo "║                                                            ║"
    echo "║   ${BOLD}DAPX-backandrepl - Deploy Automatico LXC${NC}${CYAN}               ║"
    echo "║                                                            ║"
    echo "║   Sistema centralizzato di backup e replica                ║"
    echo "║   per infrastrutture Proxmox VE                            ║"
    echo "║                                                            ║"
    echo "╚════════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

check_root() {
    if [ "$EUID" -ne 0 ]; then 
        log_error "Questo script deve essere eseguito come root"
        exit 1
    fi
}

check_proxmox() {
    if ! command -v pct &> /dev/null; then
        log_error "pct non trovato. Questo script deve essere eseguito su un nodo Proxmox."
        exit 1
    fi
    
    if ! command -v pveam &> /dev/null; then
        log_error "pveam non trovato. Ambiente Proxmox non valido."
        exit 1
    fi
}

select_ctid() {
    if [ -n "${CTID}" ]; then
        # CTID fornito come argomento
        if pct list 2>/dev/null | grep -q "^${CTID} "; then
            log_error "Container con ID ${CTID} già esistente!"
            exit 1
        fi
        return
    fi
    
    echo ""
    log_info "Container esistenti:"
    pct list 2>/dev/null || echo "  Nessun container"
    echo ""
    
    # Trova primo ID disponibile
    local next_id=100
    while pct list 2>/dev/null | grep -q "^${next_id} "; do
        next_id=$((next_id + 1))
    done
    
    read -p "Inserisci ID container [${next_id}]: " input_ctid
    CTID="${input_ctid:-$next_id}"
    
    if pct list 2>/dev/null | grep -q "^${CTID} "; then
        log_error "Container con ID ${CTID} già esistente!"
        exit 1
    fi
    
    log_success "ID container: ${CTID}"
}

select_storage() {
    if [ -n "${STORAGE}" ]; then
        if ! pvesm status 2>/dev/null | grep -q "^${STORAGE}"; then
            log_warning "Storage '${STORAGE}' non trovato."
            STORAGE=""
        else
            return
        fi
    fi
    
    echo ""
    log_info "Storage disponibili:"
    echo ""
    
    local i=1
    local storages=()
    
    while IFS= read -r line; do
        local name=$(echo "$line" | awk '{print $1}')
        local type=$(echo "$line" | awk '{print $2}')
        local status=$(echo "$line" | awk '{print $3}')
        local total=$(echo "$line" | awk '{print $4}')
        local used=$(echo "$line" | awk '{print $5}')
        
        if [ "$status" = "active" ]; then
            storages+=("$name")
            printf "  ${CYAN}%d)${NC} %-15s [%s] - %s usati di %s\n" $i "$name" "$type" "$used" "$total"
            i=$((i + 1))
        fi
    done < <(pvesm status 2>/dev/null | tail -n +2)
    
    echo ""
    read -p "Seleziona storage [1]: " choice
    choice="${choice:-1}"
    
    if [ "$choice" -ge 1 ] && [ "$choice" -le "${#storages[@]}" ]; then
        STORAGE="${storages[$((choice-1))]}"
        log_success "Storage selezionato: ${STORAGE}"
    else
        log_error "Selezione non valida"
        exit 1
    fi
}

select_bridge() {
    if [ -n "${NETWORK_BRIDGE}" ]; then
        if ip link show "${NETWORK_BRIDGE}" &>/dev/null; then
            return
        else
            log_warning "Bridge '${NETWORK_BRIDGE}' non trovato."
            NETWORK_BRIDGE=""
        fi
    fi
    
    echo ""
    log_info "Bridge di rete disponibili:"
    echo ""
    
    local i=1
    local bridges=()
    
    while IFS= read -r line; do
        bridges+=("$line")
        printf "  ${CYAN}%d)${NC} %s\n" $i "$line"
        i=$((i + 1))
    done < <(ip link show | grep -E "^[0-9]+: (vmbr|br)" | awk -F': ' '{print $2}' | cut -d'@' -f1)
    
    if [ ${#bridges[@]} -eq 0 ]; then
        log_error "Nessun bridge trovato. Crea un bridge prima di continuare."
        exit 1
    fi
    
    echo ""
    read -p "Seleziona bridge [1]: " choice
    choice="${choice:-1}"
    
    if [ "$choice" -ge 1 ] && [ "$choice" -le "${#bridges[@]}" ]; then
        NETWORK_BRIDGE="${bridges[$((choice-1))]}"
        log_success "Bridge selezionato: ${NETWORK_BRIDGE}"
    else
        log_error "Selezione non valida"
        exit 1
    fi
}

select_template() {
    echo ""
    log_step "Selezione Template"
    
    # Aggiorna lista template
    log_info "Aggiornamento repository template..."
    pveam update &>/dev/null || true
    
    # Lista template già scaricati
    echo ""
    log_info "Template già presenti nel sistema:"
    echo ""
    
    local i=1
    local local_templates=()
    
    if [ -d "/var/lib/vz/template/cache" ]; then
        while IFS= read -r file; do
            if [ -n "$file" ]; then
                local name=$(basename "$file")
                local size=$(du -h "$file" 2>/dev/null | cut -f1)
                local_templates+=("$name")
                printf "  ${GREEN}%d)${NC} %-50s [%s]\n" $i "$name" "$size"
                i=$((i + 1))
            fi
        done < <(ls -1 /var/lib/vz/template/cache/*.tar.* 2>/dev/null | head -20)
    fi
    
    if [ ${#local_templates[@]} -eq 0 ]; then
        echo "  Nessun template locale trovato"
    fi
    
    # Lista template disponibili per download
    echo ""
    log_info "Template disponibili per download (Debian/Ubuntu):"
    echo ""
    
    local remote_templates=()
    local remote_start=$i
    
    while IFS= read -r line; do
        if [ -n "$line" ]; then
            remote_templates+=("$line")
            printf "  ${YELLOW}%d)${NC} %s ${MAGENTA}[download]${NC}\n" $i "$line"
            i=$((i + 1))
        fi
    done < <(pveam available --section system 2>/dev/null | grep -iE "debian|ubuntu" | awk '{print $2}' | head -10)
    
    if [ ${#remote_templates[@]} -eq 0 ]; then
        echo "  Nessun template disponibile per download"
    fi
    
    echo ""
    echo -e "  ${CYAN}0)${NC} Inserisci nome template manualmente"
    echo ""
    
    read -p "Seleziona template: " choice
    
    if [ "$choice" = "0" ]; then
        read -p "Nome template: " SELECTED_TEMPLATE
    elif [ "$choice" -ge 1 ] && [ "$choice" -lt "$remote_start" ]; then
        # Template locale
        SELECTED_TEMPLATE="${local_templates[$((choice-1))]}"
        log_success "Template locale selezionato: ${SELECTED_TEMPLATE}"
    elif [ "$choice" -ge "$remote_start" ] && [ "$choice" -lt "$i" ]; then
        # Template da scaricare
        local remote_idx=$((choice - remote_start))
        local template_name="${remote_templates[$remote_idx]}"
        
        log_info "Download template: ${template_name}..."
        if pveam download local "${template_name}"; then
            # Trova il file scaricato
            SELECTED_TEMPLATE=$(ls -t /var/lib/vz/template/cache/${template_name}* 2>/dev/null | head -1)
            if [ -n "${SELECTED_TEMPLATE}" ]; then
                SELECTED_TEMPLATE=$(basename "${SELECTED_TEMPLATE}")
                log_success "Template scaricato: ${SELECTED_TEMPLATE}"
            else
                log_error "Template scaricato ma file non trovato"
                exit 1
            fi
        else
            log_error "Errore download template"
            exit 1
        fi
    else
        log_error "Selezione non valida"
        exit 1
    fi
    
    # Verifica che il template esista
    if [ ! -f "/var/lib/vz/template/cache/${SELECTED_TEMPLATE}" ]; then
        log_error "Template non trovato: ${SELECTED_TEMPLATE}"
        exit 1
    fi
}

download_scripts() {
    log_step "Download script da GitHub"
    
    mkdir -p ${WORK_DIR}
    cd ${WORK_DIR}
    
    # Installa git se necessario
    if ! command -v git &> /dev/null; then
        log_info "Installazione git..."
        apt-get update -qq
        apt-get install -y git > /dev/null 2>&1
    fi
    
    log_info "Repository: https://github.com/${GITHUB_REPO}"
    
    # Clona o aggiorna repository
    if [ -d "${WORK_DIR}/dapx-backandrepl" ]; then
        log_info "Aggiornamento repository..."
        cd ${WORK_DIR}/dapx-backandrepl
        git fetch origin &>/dev/null || true
        git reset --hard origin/${GITHUB_BRANCH} &>/dev/null || true
    else
        log_info "Clone repository..."
        cd ${WORK_DIR}
        git clone --depth 1 --branch ${GITHUB_BRANCH} \
            https://github.com/${GITHUB_REPO}.git &>/dev/null
    fi
    
    if [ ! -d "${WORK_DIR}/dapx-backandrepl/lxc" ]; then
        log_error "Directory lxc non trovata nel repository!"
        exit 1
    fi
    
    cd ${WORK_DIR}/dapx-backandrepl/lxc
    chmod +x *.sh 2>/dev/null || true
    
    log_success "Script scaricati"
}

create_container() {
    log_step "Creazione Container LXC"
    
    log_info "Parametri:"
    echo "  ID: ${CTID}"
    echo "  Nome: ${CT_NAME}"
    echo "  Template: ${SELECTED_TEMPLATE}"
    echo "  Storage: ${STORAGE}"
    echo "  Rootfs: ${ROOTFS_SIZE}"
    echo "  Memoria: ${MEMORY} MB"
    echo "  CPU: ${CORES} cores"
    echo "  Bridge: ${NETWORK_BRIDGE}"
    echo "  IP: ${IP_ADDRESS}"
    echo ""
    
    read -p "Confermi la creazione? [Y/n]: " confirm
    confirm="${confirm:-Y}"
    
    if [[ ! "$confirm" =~ ^[Yy]$ ]]; then
        log_warning "Creazione annullata"
        exit 0
    fi
    
    log_info "Creazione container..."
    
    # Converti ROOTFS_SIZE in formato numerico (rimuovi G/GB se presente)
    local rootfs_num=$(echo "${ROOTFS_SIZE}" | sed 's/[^0-9]//g')
    
    # Crea container
    pct create ${CTID} \
        /var/lib/vz/template/cache/${SELECTED_TEMPLATE} \
        --storage ${STORAGE} \
        --rootfs ${STORAGE}:${rootfs_num} \
        --hostname ${CT_NAME} \
        --memory ${MEMORY} \
        --cores ${CORES} \
        --net0 name=eth0,bridge=${NETWORK_BRIDGE},ip=${IP_ADDRESS} \
        --nameserver "8.8.8.8 8.8.4.4" \
        --unprivileged 0 \
        --features nesting=1,keyctl=1 \
        --ostype debian \
        --arch amd64 \
        --start 0
    
    if [ $? -ne 0 ]; then
        log_error "Errore durante creazione container"
        exit 1
    fi
    
    log_success "Container creato"
    
    # Avvia container
    log_info "Avvio container..."
    pct start ${CTID}
    sleep 5
    
    if ! pct status ${CTID} | grep -q "running"; then
        log_error "Container non in esecuzione"
        exit 1
    fi
    
    log_success "Container avviato"
}

install_application() {
    log_step "Installazione Applicazione"
    
    log_info "Copia script installazione..."
    
    # Crea directory nel container
    pct exec ${CTID} -- mkdir -p /tmp/dapx-install
    
    # Copia script
    pct push ${CTID} ${WORK_DIR}/dapx-backandrepl/lxc/install-in-lxc.sh /tmp/dapx-install/install.sh
    pct exec ${CTID} -- chmod +x /tmp/dapx-install/install.sh
    
    log_info "Esecuzione installazione (questo richiede alcuni minuti)..."
    echo ""
    
    # Esegui installazione
    pct exec ${CTID} -- /tmp/dapx-install/install.sh
    
    if [ $? -ne 0 ]; then
        log_error "Errore durante installazione"
        log_warning "Puoi riprovare manualmente con:"
        echo "  pct exec ${CTID} -- /tmp/dapx-install/install.sh"
        exit 1
    fi
    
    log_success "Applicazione installata"
}

show_summary() {
    # Ottieni IP container
    local container_ip=$(pct exec ${CTID} -- hostname -I 2>/dev/null | awk '{print $1}')
    
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║                                                            ║${NC}"
    echo -e "${GREEN}║   ${BOLD}Deploy completato con successo!${NC}${GREEN}                        ║${NC}"
    echo -e "${GREEN}║                                                            ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════════════════════════╝${NC}"
    echo ""
    log_info "${BOLD}Informazioni Container:${NC}"
    echo "  ID: ${CTID}"
    echo "  Nome: ${CT_NAME}"
    echo "  IP: ${container_ip:-N/A}"
    echo "  Porta: 8420"
    echo ""
    log_info "${BOLD}Accesso Web UI:${NC}"
    if [ -n "${container_ip}" ]; then
        echo -e "  ${CYAN}http://${container_ip}:8420${NC}"
    else
        echo "  http://<IP-CONTAINER>:8420"
    fi
    echo ""
    log_info "${BOLD}Comandi utili:${NC}"
    echo "  Stato:     pct status ${CTID}"
    echo "  Console:   pct enter ${CTID}"
    echo "  Log:       pct exec ${CTID} -- journalctl -u dapx-backandrepl -f"
    echo "  Riavvia:   pct exec ${CTID} -- systemctl restart dapx-backandrepl"
    echo ""
    log_info "${BOLD}Gestione:${NC}"
    echo "  ${WORK_DIR}/dapx-backandrepl/lxc/manage-lxc.sh ${CTID} <comando>"
    echo ""
}

# ============== MAIN ==============

print_banner
check_root
check_proxmox

select_ctid
select_storage
select_bridge
select_template
download_scripts
create_container
install_application
show_summary
