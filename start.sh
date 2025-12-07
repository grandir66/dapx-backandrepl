#!/bin/bash
#
# DAPX-backandrepl - Start Script
# Cross-platform: Proxmox VE, Ubuntu, Debian, macOS
#

set -e

# Colori per output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
PURPLE='\033[0;35m'
NC='\033[0m' # No Color

# Directory dello script
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$SCRIPT_DIR/backend"
VENV_DIR="$BACKEND_DIR/venv"
REQUIREMENTS="$BACKEND_DIR/requirements.txt"

# Rileva sistema operativo
detect_os() {
    case "$(uname -s)" in
        Darwin*)    OS="macos" ;;
        Linux*)     
            # Check per Proxmox (diversi metodi)
            if command -v pveversion &> /dev/null || [ -d /etc/pve ] || [ -f /etc/pve/pve-release ]; then
                OS="proxmox"
            elif [ -f /etc/debian_version ]; then
                OS="debian"
            elif [ -f /etc/redhat-release ]; then
                OS="redhat"
            else
                OS="linux"
            fi
            ;;
        *)          OS="unknown" ;;
    esac
    echo "$OS"
}

OS_TYPE=$(detect_os)

# Configurazione
HOST="${DAPX_HOST:-0.0.0.0}"
PORT="${DAPX_PORT:-8420}"
RELOAD="${DAPX_RELOAD:-false}"

# SSL Configuration
SSL_ENABLED="${DAPX_SSL:-false}"
SSL_CERT="${DAPX_SSL_CERT:-}"
SSL_KEY="${DAPX_SSL_KEY:-}"
CERTS_DIR="$SCRIPT_DIR/backend/certs"

# Directory database in base al sistema
get_db_dir() {
    case "$OS_TYPE" in
        macos)
            # macOS: usa directory utente
            echo "$HOME/.dapx-backandrepl"
            ;;
        proxmox|debian|linux)
            # Linux: prova /var/lib, fallback a home
            if [ -w "/var/lib" ] 2>/dev/null; then
                echo "/var/lib/dapx-backandrepl"
            else
                echo "$HOME/.dapx-backandrepl"
            fi
            ;;
        *)
            echo "$SCRIPT_DIR/data"
            ;;
    esac
}

# Funzione per terminare istanze esistenti
kill_existing_instance() {
    echo -e "${YELLOW}► Verifica istanze esistenti...${NC}"
    
    # Cerca processi uvicorn che usano main:app
    if [ "$OS_TYPE" = "macos" ]; then
        EXISTING_PIDS=$(pgrep -f "uvicorn.*main:app" 2>/dev/null || true)
    else
        EXISTING_PIDS=$(pgrep -f "uvicorn.*main:app" 2>/dev/null || true)
    fi
    
    if [ -n "$EXISTING_PIDS" ]; then
        echo -e "  ${YELLOW}!${NC} Trovate istanze in esecuzione (PID: $EXISTING_PIDS)"
        echo -e "  ${BLUE}→${NC} Terminazione in corso..."
        echo "$EXISTING_PIDS" | xargs kill -9 2>/dev/null || true
        sleep 1
        echo -e "  ${GREEN}✓${NC} Istanze precedenti terminate"
    fi
    
    # Verifica anche la porta
    if [ "$OS_TYPE" = "macos" ]; then
        PORT_PID=$(lsof -ti:$PORT 2>/dev/null || true)
    else
        PORT_PID=$(lsof -ti:$PORT 2>/dev/null || ss -tlnp "sport = :$PORT" 2>/dev/null | grep -oP 'pid=\K\d+' || true)
    fi
    
    if [ -n "$PORT_PID" ]; then
        echo -e "  ${YELLOW}!${NC} Porta $PORT occupata (PID: $PORT_PID)"
        echo -e "  ${BLUE}→${NC} Liberazione porta..."
        echo "$PORT_PID" | xargs kill -9 2>/dev/null || true
        sleep 1
        echo -e "  ${GREEN}✓${NC} Porta $PORT liberata"
    else
        echo -e "  ${GREEN}✓${NC} Nessuna istanza in esecuzione"
    fi
}

# Banner
show_banner() {
    echo -e "${PURPLE}"
    echo "╔═══════════════════════════════════════════════════════════╗"
    echo "║            🔄 DAPX-backandrepl v3.3.0                     ║"
    echo "║       Backup & Replica per Proxmox (ZFS/BTRFS/PBS)        ║"
    echo "╠═══════════════════════════════════════════════════════════╣"
    case "$OS_TYPE" in
        macos)   echo "║  🍎 Piattaforma: macOS                                      ║" ;;
        proxmox) echo "║  🖥️  Piattaforma: Proxmox VE                                 ║" ;;
        debian)  echo "║  🐧 Piattaforma: Debian/Ubuntu                              ║" ;;
        *)       echo "║  💻 Piattaforma: Linux                                      ║" ;;
    esac
    echo "╚═══════════════════════════════════════════════════════════╝"
    echo -e "${NC}"
}

# Funzione per verificare Python
check_python() {
    echo -e "${YELLOW}► Verifica Python...${NC}"
    
    # Su macOS prova prima python3 da Homebrew o sistema
    if [ "$OS_TYPE" = "macos" ]; then
        if command -v python3 &> /dev/null; then
            PYTHON_CMD="python3"
        elif command -v /usr/local/bin/python3 &> /dev/null; then
            PYTHON_CMD="/usr/local/bin/python3"
        elif command -v /opt/homebrew/bin/python3 &> /dev/null; then
            PYTHON_CMD="/opt/homebrew/bin/python3"
        else
            echo -e "  ${RED}✗ Python non trovato!${NC}"
            echo "  Installa Python: brew install python3"
            exit 1
        fi
    else
        if command -v python3 &> /dev/null; then
            PYTHON_CMD="python3"
        elif command -v python &> /dev/null; then
            PYTHON_CMD="python"
        else
            echo -e "  ${RED}✗ Python non trovato!${NC}"
            echo "  Installa Python: apt install python3 python3-venv python3-pip"
            exit 1
        fi
    fi
    
    PYTHON_VERSION=$($PYTHON_CMD --version 2>&1 | cut -d' ' -f2)
    echo -e "  ${GREEN}✓${NC} Python trovato: $PYTHON_VERSION"
    
    # Verifica versione minima (3.9)
    MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [ "$MAJOR" -lt 3 ] || ([ "$MAJOR" -eq 3 ] && [ "$MINOR" -lt 9 ]); then
        echo -e "  ${RED}✗ Python $PYTHON_VERSION non supportato. Richiesto Python 3.9+${NC}"
        exit 1
    fi
}

# Funzione per verificare/creare venv
setup_venv() {
    echo -e "${YELLOW}► Verifica Virtual Environment...${NC}"
    
    if [ -d "$VENV_DIR" ] && [ -f "$VENV_DIR/bin/activate" ]; then
        echo -e "  ${GREEN}✓${NC} Virtual environment esistente"
    else
        echo -e "  ${BLUE}→${NC} Creazione virtual environment..."
        $PYTHON_CMD -m venv "$VENV_DIR"
        echo -e "  ${GREEN}✓${NC} Virtual environment creato"
    fi
    
    # Attiva venv
    source "$VENV_DIR/bin/activate"
    echo -e "  ${GREEN}✓${NC} Virtual environment attivato"
}

# Funzione per verificare/installare dipendenze
install_dependencies() {
    echo -e "${YELLOW}► Verifica dipendenze...${NC}"
    
    # Verifica se requirements.txt esiste
    if [ ! -f "$REQUIREMENTS" ]; then
        echo -e "  ${RED}✗ File requirements.txt non trovato!${NC}"
        exit 1
    fi
    
    # Verifica se le dipendenze principali sono installate
    if pip show fastapi &> /dev/null && pip show uvicorn &> /dev/null && pip show sqlalchemy &> /dev/null; then
        echo -e "  ${GREEN}✓${NC} Dipendenze principali già installate"
        
        # Chiedi se aggiornare
        if [ "$1" == "--update" ] || [ "$1" == "-u" ]; then
            echo -e "  ${BLUE}→${NC} Aggiornamento dipendenze..."
            pip install -q --upgrade -r "$REQUIREMENTS"
            echo -e "  ${GREEN}✓${NC} Dipendenze aggiornate"
        fi
    else
        echo -e "  ${BLUE}→${NC} Installazione dipendenze..."
        pip install -q --upgrade pip
        pip install -q -r "$REQUIREMENTS"
        echo -e "  ${GREEN}✓${NC} Dipendenze installate"
    fi
}

# Funzione per verificare la directory database
setup_database_dir() {
    echo -e "${YELLOW}► Verifica directory database...${NC}"
    
    DB_DIR=$(get_db_dir)
    
    if [ ! -d "$DB_DIR" ]; then
        mkdir -p "$DB_DIR" 2>/dev/null || {
            echo -e "  ${YELLOW}!${NC} Impossibile creare $DB_DIR, uso directory locale"
            DB_DIR="$SCRIPT_DIR/data"
            mkdir -p "$DB_DIR"
        }
    fi
    
    export DAPX_DB="$DB_DIR/dapx.db"
    echo -e "  ${GREEN}✓${NC} Database in: $DAPX_DB"
}

# Funzione per setup SSL
setup_ssl() {
    echo -e "${YELLOW}► Configurazione SSL...${NC}"
    
    # Se certificati specificati, verifica esistenza
    if [ -n "$SSL_CERT" ] && [ -n "$SSL_KEY" ]; then
        if [ -f "$SSL_CERT" ] && [ -f "$SSL_KEY" ]; then
            echo -e "  ${GREEN}✓${NC} Certificati custom trovati"
            return 0
        else
            echo -e "  ${RED}✗${NC} Certificati specificati non trovati!"
            echo "      Cert: $SSL_CERT"
            echo "      Key:  $SSL_KEY"
            return 1
        fi
    fi
    
    # Usa o genera certificati auto-firmati
    SSL_CERT="$CERTS_DIR/server.crt"
    SSL_KEY="$CERTS_DIR/server.key"
    
    if [ -f "$SSL_CERT" ] && [ -f "$SSL_KEY" ]; then
        echo -e "  ${GREEN}✓${NC} Certificati auto-firmati esistenti"
        
        # Verifica scadenza
        if python "$BACKEND_DIR/scripts/generate_cert.py" --check "$SSL_CERT" 2>/dev/null; then
            return 0
        else
            echo -e "  ${YELLOW}!${NC} Certificato scaduto, rigenerazione..."
        fi
    fi
    
    # Genera nuovi certificati
    echo -e "  ${BLUE}→${NC} Generazione certificati auto-firmati..."
    
    # Determina hostname e IP
    CERT_HOSTNAME=$(hostname -f 2>/dev/null || hostname)
    CERT_IPS=""
    
    # Trova IP locale
    if [ "$OS_TYPE" = "macos" ]; then
        LOCAL_IP=$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "")
    else
        LOCAL_IP=$(hostname -I 2>/dev/null | awk '{print $1}' || ip route get 1 2>/dev/null | awk '{print $7}' || echo "")
    fi
    
    if [ -n "$LOCAL_IP" ]; then
        CERT_IPS="--ip $LOCAL_IP"
    fi
    
    python "$BACKEND_DIR/scripts/generate_cert.py" \
        --hostname "$CERT_HOSTNAME" \
        $CERT_IPS \
        --days 365 \
        --output "$CERTS_DIR"
    
    if [ $? -eq 0 ]; then
        echo -e "  ${GREEN}✓${NC} Certificati generati"
        return 0
    else
        echo -e "  ${RED}✗${NC} Errore generazione certificati"
        return 1
    fi
}

# Funzione per avviare il server
start_server() {
    echo -e "${YELLOW}► Avvio server...${NC}"
    echo ""
    
    cd "$BACKEND_DIR"
    
    UVICORN_ARGS="main:app --host $HOST --port $PORT"
    
    if [ "$RELOAD" == "true" ] || [ "$1" == "--dev" ]; then
        UVICORN_ARGS="$UVICORN_ARGS --reload"
        echo -e "${BLUE}Modalità sviluppo (hot-reload attivo)${NC}"
    fi
    
    # SSL configuration
    PROTOCOL="http"
    if [ "$SSL_ENABLED" == "true" ]; then
        if setup_ssl; then
            UVICORN_ARGS="$UVICORN_ARGS --ssl-keyfile $SSL_KEY --ssl-certfile $SSL_CERT"
            PROTOCOL="https"
            echo -e "${GREEN}🔒 SSL abilitato${NC}"
        else
            echo -e "${YELLOW}⚠️  SSL richiesto ma setup fallito, avvio in HTTP${NC}"
        fi
    fi
    
    echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
    echo -e "${GREEN}  Server avviato su: $PROTOCOL://$HOST:$PORT${NC}"
    if [ "$OS_TYPE" = "macos" ]; then
        echo -e "${GREEN}  Apri nel browser: $PROTOCOL://localhost:$PORT${NC}"
    fi
    echo -e "${GREEN}  API Docs: $PROTOCOL://$HOST:$PORT/docs${NC}"
    if [ "$PROTOCOL" == "https" ]; then
        echo -e "${YELLOW}  Nota: Certificato auto-firmato, accetta eccezione browser${NC}"
    fi
    echo -e "${GREEN}  Premi Ctrl+C per fermare${NC}"
    echo -e "${GREEN}════════════════════════════════════════════════════════════${NC}"
    echo ""
    
    exec python -m uvicorn $UVICORN_ARGS
}

# Mostra help
show_help() {
    echo "DAPX-backandrepl - Sistema di Backup e Replica per Proxmox"
    echo ""
    echo "Uso: $0 [opzioni]"
    echo ""
    echo "Opzioni:"
    echo "  --dev, -d       Avvia in modalità sviluppo (hot-reload)"
    echo "  --update, -u    Aggiorna le dipendenze prima di avviare"
    echo "  --install-only  Solo installa dipendenze, non avvia"
    echo "  --stop          Ferma il server senza riavviarlo"
    echo "  --restart       Riavvia il server (default)"
    echo "  --status        Mostra stato del server"
    echo "  --ssl           Abilita HTTPS (genera cert auto-firmato se necessario)"
    echo "  --gen-cert      Genera solo certificato SSL senza avviare"
    echo "  --help, -h      Mostra questo messaggio"
    echo ""
    echo "Variabili ambiente:"
    echo "  DAPX_HOST       Host (default: 0.0.0.0)"
    echo "  DAPX_PORT       Porta (default: 8420)"
    echo "  DAPX_DB         Path database SQLite"
    echo "  DAPX_SSL        Abilita SSL (true/false)"
    echo "  DAPX_SSL_CERT   Path certificato SSL custom"
    echo "  DAPX_SSL_KEY    Path chiave privata SSL custom"
    echo ""
    echo "Piattaforme supportate:"
    echo "  - Proxmox VE (Debian-based)"
    echo "  - Ubuntu / Debian"
    echo "  - macOS (con Homebrew Python)"
    echo ""
    echo "Esempi HTTPS:"
    echo "  $0 --ssl                    # Avvia con certificato auto-firmato"
    echo "  DAPX_SSL_CERT=/path/to/cert.pem DAPX_SSL_KEY=/path/to/key.pem $0 --ssl"
    echo ""
}

# Mostra stato
show_status() {
    echo -e "${YELLOW}► Stato DAPX-backandrepl${NC}"
    echo -e "  Piattaforma: $OS_TYPE"
    
    if [ "$OS_TYPE" = "macos" ]; then
        PIDS=$(pgrep -f "uvicorn.*main:app" 2>/dev/null || true)
    else
        PIDS=$(pgrep -f "uvicorn.*main:app" 2>/dev/null || true)
    fi
    
    if [ -n "$PIDS" ]; then
        echo -e "  ${GREEN}●${NC} Server in esecuzione"
        echo -e "    PID: $PIDS"
        echo -e "    URL: http://localhost:$PORT"
    else
        echo -e "  ${RED}●${NC} Server non in esecuzione"
    fi
    
    # Mostra info database
    DB_DIR=$(get_db_dir)
    if [ -f "$DB_DIR/dapx.db" ]; then
        DB_SIZE=$(ls -lh "$DB_DIR/dapx.db" 2>/dev/null | awk '{print $5}')
        echo -e "  📁 Database: $DB_DIR/dapx.db ($DB_SIZE)"
    else
        echo -e "  📁 Database: non inizializzato"
    fi
}

# Solo stop
stop_server() {
    echo -e "${YELLOW}► Arresto DAPX-backandrepl...${NC}"
    
    if [ "$OS_TYPE" = "macos" ]; then
        PIDS=$(pgrep -f "uvicorn.*main:app" 2>/dev/null || true)
    else
        PIDS=$(pgrep -f "uvicorn.*main:app" 2>/dev/null || true)
    fi
    
    if [ -n "$PIDS" ]; then
        echo "$PIDS" | xargs kill -9 2>/dev/null || true
        sleep 1
        echo -e "  ${GREEN}✓${NC} Server arrestato"
    else
        echo -e "  ${YELLOW}!${NC} Nessun server in esecuzione"
    fi
    
    # Libera anche la porta se occupata
    if [ "$OS_TYPE" = "macos" ]; then
        PORT_PID=$(lsof -ti:$PORT 2>/dev/null || true)
    else
        PORT_PID=$(lsof -ti:$PORT 2>/dev/null || true)
    fi
    
    if [ -n "$PORT_PID" ]; then
        echo "$PORT_PID" | xargs kill -9 2>/dev/null || true
        echo -e "  ${GREEN}✓${NC} Porta $PORT liberata"
    fi
}

# Main
main() {
    # Parse argomenti
    INSTALL_ONLY=false
    UPDATE_DEPS=false
    DEV_MODE=false
    STOP_ONLY=false
    SHOW_STATUS=false
    GEN_CERT_ONLY=false
    
    for arg in "$@"; do
        case $arg in
            --help|-h)
                show_help
                exit 0
                ;;
            --stop)
                STOP_ONLY=true
                ;;
            --status)
                SHOW_STATUS=true
                ;;
            --install-only)
                INSTALL_ONLY=true
                ;;
            --update|-u)
                UPDATE_DEPS=true
                ;;
            --dev|-d)
                DEV_MODE=true
                RELOAD="true"
                ;;
            --ssl)
                SSL_ENABLED="true"
                ;;
            --gen-cert)
                GEN_CERT_ONLY=true
                SSL_ENABLED="true"
                ;;
        esac
    done
    
    # Banner
    show_banner
    
    # Comandi che non richiedono setup
    if [ "$SHOW_STATUS" == "true" ]; then
        show_status
        exit 0
    fi
    
    if [ "$STOP_ONLY" == "true" ]; then
        stop_server
        exit 0
    fi
    
    # Termina istanze esistenti
    kill_existing_instance
    
    # Esegui setup
    check_python
    setup_venv
    
    if [ "$UPDATE_DEPS" == "true" ]; then
        install_dependencies --update
    else
        install_dependencies
    fi
    
    setup_database_dir
    
    if [ "$INSTALL_ONLY" == "true" ]; then
        echo ""
        echo -e "${GREEN}✓ Setup completato!${NC}"
        echo -e "  Esegui ${BLUE}$0${NC} per avviare il server"
        exit 0
    fi
    
    # Solo generazione certificato
    if [ "$GEN_CERT_ONLY" == "true" ]; then
        echo ""
        setup_ssl
        exit $?
    fi
    
    # Avvia server
    echo ""
    if [ "$DEV_MODE" == "true" ]; then
        start_server --dev
    else
        start_server
    fi
}

# Esegui
main "$@"
