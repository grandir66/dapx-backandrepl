#!/bin/bash
#
# DAPX-backandrepl - Aggiornamento Remoto
# Aggiorna sistemi remoti via SSH
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

show_help() {
    echo -e "${BLUE}DAPX-backandrepl - Aggiornamento Remoto${NC}"
    echo ""
    echo "Uso: $0 <comando> [host1] [host2] ..."
    echo ""
    echo "Comandi:"
    echo "  update <host> [host2...]    Aggiorna sistemi remoti"
    echo "  status <host> [host2...]    Verifica stato sistemi"
    echo "  logs <host>                 Mostra log sistema remoto"
    echo "  restart <host> [host2...]   Riavvia servizio"
    echo "  version <host> [host2...]   Mostra versione installata"
    echo ""
    echo "Esempi:"
    echo "  $0 update 192.168.40.3"
    echo "  $0 update 192.168.40.3 192.168.40.4 192.168.40.5"
    echo "  $0 status 192.168.40.3"
    echo "  $0 logs 192.168.40.3"
    echo ""
    echo "Opzioni:"
    echo "  -u, --user USER    Utente SSH (default: root)"
    echo "  -p, --port PORT    Porta SSH (default: 22)"
    echo "  -i, --key FILE     Chiave SSH"
    echo ""
}

# Parametri default
SSH_USER="root"
SSH_PORT="22"
SSH_KEY=""

# Parse opzioni
while [[ $# -gt 0 ]]; do
    case $1 in
        -u|--user)
            SSH_USER="$2"
            shift 2
            ;;
        -p|--port)
            SSH_PORT="$2"
            shift 2
            ;;
        -i|--key)
            SSH_KEY="-i $2"
            shift 2
            ;;
        -h|--help)
            show_help
            exit 0
            ;;
        *)
            break
            ;;
    esac
done

COMMAND="${1:-}"
shift || true

if [ -z "${COMMAND}" ]; then
    show_help
    exit 1
fi

# Funzione per eseguire comando su host remoto
remote_exec() {
    local HOST=$1
    local CMD=$2
    ssh ${SSH_KEY} -p ${SSH_PORT} -o ConnectTimeout=10 -o StrictHostKeyChecking=no ${SSH_USER}@${HOST} "${CMD}"
}

# Aggiorna singolo host
update_host() {
    local HOST=$1
    log_info "Aggiornamento ${HOST}..."
    
    # Scarica ed esegui script di aggiornamento
    remote_exec ${HOST} "
        cd /tmp && \
        wget -q https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/update.sh -O update.sh && \
        chmod +x update.sh && \
        ./update.sh
    "
    
    if [ $? -eq 0 ]; then
        log_success "${HOST}: Aggiornato"
    else
        log_error "${HOST}: Errore aggiornamento"
    fi
}

# Verifica stato host
status_host() {
    local HOST=$1
    log_info "Stato ${HOST}:"
    
    remote_exec ${HOST} "
        SERVICE=\$(systemctl list-unit-files | grep -E 'dapx|sanoid-manager' | awk '{print \$1}' | head -1)
        if [ -n \"\${SERVICE}\" ]; then
            systemctl status \${SERVICE} --no-pager | head -10
        else
            echo 'Servizio non trovato'
        fi
    "
}

# Mostra log host
logs_host() {
    local HOST=$1
    log_info "Log ${HOST}:"
    
    remote_exec ${HOST} "
        SERVICE=\$(systemctl list-unit-files | grep -E 'dapx|sanoid-manager' | awk '{print \$1}' | head -1)
        if [ -n \"\${SERVICE}\" ]; then
            journalctl -u \${SERVICE} -n 50 --no-pager
        else
            echo 'Servizio non trovato'
        fi
    "
}

# Riavvia servizio host
restart_host() {
    local HOST=$1
    log_info "Riavvio ${HOST}..."
    
    remote_exec ${HOST} "
        SERVICE=\$(systemctl list-unit-files | grep -E 'dapx|sanoid-manager' | awk '{print \$1}' | head -1)
        if [ -n \"\${SERVICE}\" ]; then
            systemctl restart \${SERVICE}
            sleep 2
            systemctl is-active \${SERVICE}
        else
            echo 'Servizio non trovato'
            exit 1
        fi
    "
    
    if [ $? -eq 0 ]; then
        log_success "${HOST}: Riavviato"
    else
        log_error "${HOST}: Errore riavvio"
    fi
}

# Mostra versione host
version_host() {
    local HOST=$1
    
    VERSION=$(remote_exec ${HOST} "
        if [ -f /opt/dapx-backandrepl/version.txt ]; then
            cat /opt/dapx-backandrepl/version.txt
        elif [ -f /opt/sanoid-manager/version.txt ]; then
            cat /opt/sanoid-manager/version.txt
        else
            cd /opt/dapx-backandrepl 2>/dev/null || cd /opt/sanoid-manager 2>/dev/null
            git describe --tags 2>/dev/null || git rev-parse --short HEAD 2>/dev/null || echo 'N/A'
        fi
    " 2>/dev/null)
    
    echo "${HOST}: ${VERSION}"
}

# Esegui comando
case ${COMMAND} in
    update)
        if [ $# -eq 0 ]; then
            log_error "Specifica almeno un host"
            exit 1
        fi
        
        log_info "════════════════════════════════════════════════"
        log_info "${BOLD}Aggiornamento Remoto${NC}"
        log_info "════════════════════════════════════════════════"
        echo ""
        
        for HOST in "$@"; do
            update_host ${HOST}
            echo ""
        done
        
        log_success "Aggiornamento completato"
        ;;
    
    status)
        if [ $# -eq 0 ]; then
            log_error "Specifica almeno un host"
            exit 1
        fi
        
        for HOST in "$@"; do
            status_host ${HOST}
            echo ""
        done
        ;;
    
    logs)
        if [ $# -eq 0 ]; then
            log_error "Specifica un host"
            exit 1
        fi
        logs_host $1
        ;;
    
    restart)
        if [ $# -eq 0 ]; then
            log_error "Specifica almeno un host"
            exit 1
        fi
        
        for HOST in "$@"; do
            restart_host ${HOST}
        done
        ;;
    
    version)
        if [ $# -eq 0 ]; then
            log_error "Specifica almeno un host"
            exit 1
        fi
        
        log_info "Versioni installate:"
        for HOST in "$@"; do
            version_host ${HOST}
        done
        ;;
    
    *)
        log_error "Comando sconosciuto: ${COMMAND}"
        show_help
        exit 1
        ;;
esac



