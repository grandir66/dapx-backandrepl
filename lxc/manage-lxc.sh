#!/bin/bash
#
# DAPX-backandrepl - Gestione container LXC
# Script per gestire facilmente il container LXC
#

set -e

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
BLUE='\033[0;34m'
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
ACTION="${2:-status}"

show_help() {
    echo -e "${BLUE}Uso:${NC} $0 <CTID> <azione>"
    echo ""
    echo -e "${BLUE}Azioni disponibili:${NC}"
    echo "  status      - Mostra stato container e servizio"
    echo "  start       - Avvia container"
    echo "  stop        - Ferma container"
    echo "  restart     - Riavvia container"
    echo "  enter        - Entra nel container (shell)"
    echo "  logs         - Mostra log del servizio"
    echo "  config       - Mostra configurazione container"
    echo "  backup       - Crea backup del container"
    echo "  update       - Aggiorna applicazione"
    echo "  service-start   - Avvia servizio dapx-backandrepl"
    echo "  service-stop    - Ferma servizio dapx-backandrepl"
    echo "  service-restart - Riavvia servizio dapx-backandrepl"
    echo "  service-status  - Stato servizio dapx-backandrepl"
    echo ""
    echo -e "${BLUE}Esempi:${NC}"
    echo "  $0 100 status"
    echo "  $0 100 logs"
    echo "  $0 100 backup"
}

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

# Verifica che il container esista
if ! pct list | grep -q "^${CTID} "; then
    log_error "Container con ID ${CTID} non trovato!"
    exit 1
fi

case "${ACTION}" in
    status)
        log_info "Stato Container LXC ${CTID}:"
        pct status ${CTID}
        echo ""
        log_info "Stato Servizio dapx-backandrepl:"
        pct exec ${CTID} -- systemctl status dapx-backandrepl --no-pager || true
        echo ""
        log_info "Informazioni Container:"
        pct config ${CTID} | head -20
        ;;
    
    start)
        log_info "Avvio container ${CTID}..."
        pct start ${CTID}
        sleep 2
        if pct status ${CTID} | grep -q "running"; then
            log_success "Container avviato"
        else
            log_error "Errore avvio container"
            exit 1
        fi
        ;;
    
    stop)
        log_info "Fermata container ${CTID}..."
        pct stop ${CTID}
        sleep 2
        if pct status ${CTID} | grep -q "stopped"; then
            log_success "Container fermato"
        else
            log_error "Errore fermata container"
            exit 1
        fi
        ;;
    
    restart)
        log_info "Riavvio container ${CTID}..."
        pct stop ${CTID} || true
        sleep 2
        pct start ${CTID}
        sleep 2
        if pct status ${CTID} | grep -q "running"; then
            log_success "Container riavviato"
        else
            log_error "Errore riavvio container"
            exit 1
        fi
        ;;
    
    enter)
        log_info "Accesso al container ${CTID}..."
        pct enter ${CTID}
        ;;
    
    logs)
        log_info "Log servizio dapx-backandrepl:"
        pct exec ${CTID} -- journalctl -u dapx-backandrepl -n 50 --no-pager
        echo ""
        log_info "Per log in tempo reale:"
        echo "  pct exec ${CTID} -- journalctl -u dapx-backandrepl -f"
        ;;
    
    config)
        log_info "Configurazione Container ${CTID}:"
        pct config ${CTID}
        ;;
    
    backup)
        log_info "Creazione backup container ${CTID}..."
        SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
        ${SCRIPT_DIR}/export-lxc-template.sh ${CTID}
        ;;
    
    update)
        log_info "Aggiornamento applicazione nel container ${CTID}..."
        pct exec ${CTID} -- bash -c "
            cd /opt/dapx-backandrepl
            git pull
            cd backend
            pip3 install --no-cache-dir -r requirements.txt
            systemctl restart dapx-backandrepl
        "
        log_success "Applicazione aggiornata"
        ;;
    
    service-start)
        log_info "Avvio servizio dapx-backandrepl..."
        pct exec ${CTID} -- systemctl start dapx-backandrepl
        log_success "Servizio avviato"
        ;;
    
    service-stop)
        log_info "Fermata servizio dapx-backandrepl..."
        pct exec ${CTID} -- systemctl stop dapx-backandrepl
        log_success "Servizio fermato"
        ;;
    
    service-restart)
        log_info "Riavvio servizio dapx-backandrepl..."
        pct exec ${CTID} -- systemctl restart dapx-backandrepl
        log_success "Servizio riavviato"
        ;;
    
    service-status)
        log_info "Stato servizio dapx-backandrepl:"
        pct exec ${CTID} -- systemctl status dapx-backandrepl --no-pager
        ;;
    
    help|--help|-h)
        show_help
        ;;
    
    *)
        log_error "Azione sconosciuta: ${ACTION}"
        echo ""
        show_help
        exit 1
        ;;
esac



