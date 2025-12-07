#!/bin/bash
#
# Script di deploy per trasferire modifiche al server remoto
#

set -e

# Configurazione
# Server può essere specificato come parametro o variabile d'ambiente
# Es: ./deploy.sh 192.168.40.3
# Es: SERVER=192.168.40.3 ./deploy.sh
SERVER="${1:-${SERVER:-192.168.40.3}}"
SERVER_USER="${SERVER_USER:-root}"
SERVER_DIR="${SERVER_DIR:-/opt/dapx-backandrepl}"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

# Mostra help se richiesto
if [ "$1" = "-h" ] || [ "$1" = "--help" ]; then
    echo "Uso: $0 [SERVER_IP]"
    echo ""
    echo "Esempi:"
    echo "  $0 192.168.40.3"
    echo "  SERVER=192.168.40.3 $0"
    echo "  SERVER_USER=admin SERVER=192.168.40.3 $0"
    echo ""
    echo "Variabili d'ambiente:"
    echo "  SERVER       - Indirizzo IP o hostname del server (default: 192.168.40.3)"
    echo "  SERVER_USER - Utente SSH (default: root)"
    echo "  SERVER_DIR  - Directory installazione sul server (default: /opt/dapx-backandrepl)"
    echo "  SSH_KEY     - Path chiave SSH personalizzata (opzionale)"
    exit 0
fi

# Opzioni SSH (puoi sovrascrivere con variabile d'ambiente)
SSH_KEY="${SSH_KEY:-}"  # Es: SSH_KEY=~/.ssh/id_rsa ./deploy.sh
SSH_OPTS_BASE="-o ConnectTimeout=10 -o StrictHostKeyChecking=no"

# Colori
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info() { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[✓]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[!]${NC} $1"; }
log_error() { echo -e "${RED}[✗]${NC} $1"; }

# Aggiungi chiave SSH se specificata (dopo definizione funzioni log)
if [ -n "$SSH_KEY" ] && [ -f "$SSH_KEY" ]; then
    SSH_OPTS_BASE="$SSH_OPTS_BASE -i $SSH_KEY"
    log_info "Usando chiave SSH: $SSH_KEY"
fi

SSH_OPTS="$SSH_OPTS_BASE"

# Banner
echo ""
echo -e "${GREEN}╔════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║     Sanoid Manager - Deploy Tool           ║${NC}"
echo -e "${GREEN}╚════════════════════════════════════════════╝${NC}"
echo ""
log_info "Server: ${SERVER_USER}@${SERVER}"
log_info "Directory: ${SERVER_DIR}"
echo ""

# Verifica connessione
log_info "Verifica connessione al server ${SERVER}..."
# Usa le stesse opzioni SSH che funzionano manualmente (senza BatchMode per permettere password/key)
if ! ssh $SSH_OPTS "${SERVER_USER}@${SERVER}" "echo 'OK'" 2>&1; then
    log_error "Impossibile connettersi al server ${SERVER}"
    log_info "Assicurati che:"
    log_info "  1. Il server sia raggiungibile"
    log_info "  2. SSH key sia configurata o password disponibile"
    log_info "  3. L'utente ${SERVER_USER} abbia accesso"
    log_info ""
    log_info "Prova manualmente: ssh ${SERVER_USER}@${SERVER}"
    exit 1
fi
log_success "Connessione OK"

# Verifica directory server
log_info "Verifica directory installazione sul server..."
if ! ssh $SSH_OPTS "${SERVER_USER}@${SERVER}" "test -d ${SERVER_DIR}" 2>&1; then
    log_error "Directory ${SERVER_DIR} non trovata sul server"
    log_info "Verifica il percorso di installazione"
    exit 1
fi
log_success "Directory trovata"

# Backup sul server
log_info "Backup installazione corrente sul server..."
ssh $SSH_OPTS "${SERVER_USER}@${SERVER}" "
    if [ -d ${SERVER_DIR} ]; then
        BACKUP_DIR=\"/opt/dapx-backandrepl-backup-\$(date +%Y%m%d-%H%M%S)\"
        cp -r ${SERVER_DIR} \"\${BACKUP_DIR}\"
        echo \"Backup creato: \${BACKUP_DIR}\"
    fi
" || log_warning "Backup non creato (potrebbe essere normale)"

# File da trasferire (solo modifiche recenti)
log_info "Preparazione file da trasferire..."

# Crea archivio temporaneo
TEMP_ARCHIVE="/tmp/sanoid-manager-deploy-$(date +%s).tar.gz"
cd "$LOCAL_DIR"

# File modificati e nuovi
FILES_TO_DEPLOY=(
    "backend/routers/host_info.py"
    "backend/services/host_info_service.py"
    "backend/routers/recovery_jobs.py"
    "backend/services/pbs_service.py"
    "backend/services/proxmox_service.py"
    "backend/services/notification_service.py"
    "backend/database.py"
    "backend/main.py"
    "backend/requirements.txt"
    "backend/scripts/verify_database.py"
    "frontend/dist/index.html"
    "start.sh"
    "fix_production.sh"
)

# Verifica quali file esistono
EXISTING_FILES=()
for file in "${FILES_TO_DEPLOY[@]}"; do
    if [ -f "$file" ]; then
        EXISTING_FILES+=("$file")
    else
        log_warning "File non trovato: $file"
    fi
done

if [ ${#EXISTING_FILES[@]} -eq 0 ]; then
    log_error "Nessun file da trasferire"
    exit 1
fi

log_info "File da trasferire (${#EXISTING_FILES[@]}):"
for file in "${EXISTING_FILES[@]}"; do
    echo "  - $file"
done

# Crea archivio
log_info "Creazione archivio..."
tar -czf "$TEMP_ARCHIVE" "${EXISTING_FILES[@]}" 2>/dev/null || {
    log_error "Errore creazione archivio"
    exit 1
}

# Trasferisci archivio
log_info "Trasferimento file al server..."
scp $SSH_OPTS "$TEMP_ARCHIVE" "${SERVER_USER}@${SERVER}:/tmp/" || {
    log_error "Errore trasferimento"
    rm -f "$TEMP_ARCHIVE"
    exit 1
}

# Estrai e copia file sul server
log_info "Installazione file sul server..."
ssh $SSH_OPTS "${SERVER_USER}@${SERVER}" "
    set +e  # Non uscire al primo errore, gestiamo gli errori manualmente
    cd /tmp || exit 1
    ARCHIVE=\$(ls -t sanoid-manager-deploy-*.tar.gz 2>/dev/null | head -1)
    if [ -z \"\${ARCHIVE}\" ]; then
        echo 'ERRORE: Archivio non trovato in /tmp'
        exit 1
    fi
    echo \"Archivio trovato: \${ARCHIVE}\"
    
    # Stop servizio
    systemctl stop sanoid-manager 2>/dev/null || true
    sleep 2
    
    # Uccidi eventuali processi relitti (uvicorn/python che potrebbero tenere la porta)
    echo 'Pulizia processi relitti...'
    # Cerca processi uvicorn o python che usano la porta 8420 o eseguono main.py
    pkill -f 'uvicorn.*main:app' 2>/dev/null || true
    pkill -f 'python.*backend/main\.py' 2>/dev/null || true
    pkill -f 'python.*main:app' 2>/dev/null || true
    
    # Verifica se la porta è ancora in uso
    sleep 1
    if command -v lsof >/dev/null 2>&1; then
        PORT_PID=\$(lsof -ti :8420 2>/dev/null)
        if [ -n \"\${PORT_PID}\" ]; then
            echo \"Processo \${PORT_PID} sta ancora usando la porta 8420, terminazione forzata...\"
            kill -9 \${PORT_PID} 2>/dev/null || true
            sleep 1
        fi
    fi
    
    # Estrai archivio in directory temporanea
    TEMP_DIR=\"/tmp/sanoid-deploy-\$\$\"
    mkdir -p \"\${TEMP_DIR}\" || {
        echo 'ERRORE: Impossibile creare directory temporanea'
        exit 1
    }
    echo \"Estrazione archivio in \${TEMP_DIR}...\"
    tar -xzf \"\${ARCHIVE}\" -C \"\${TEMP_DIR}\" || {
        echo \"ERRORE: Estrazione archivio fallita: \${ARCHIVE}\"
        rm -rf \"\${TEMP_DIR}\"
        exit 1
    }
    echo \"Archivio estratto correttamente\"
    
    # Copia file nella directory di installazione
    cd \"\${TEMP_DIR}\" || {
        echo 'ERRORE: Impossibile accedere alla directory temporanea'
        exit 1
    }
    
    # Backend files - preserva struttura directory
    if [ -d backend ]; then
        echo \"Copia file backend...\"
        # Crea directory backend se non esiste
        mkdir -p ${SERVER_DIR}/backend || exit 1
        # Copia contenuto mantenendo struttura
        if cp -r backend/* ${SERVER_DIR}/backend/ 2>/dev/null; then
            echo \"File backend copiati\"
        else
            echo \"Fallback: copia file singolarmente...\"
            # Fallback: copia file singolarmente
            for item in backend/*; do
                if [ -f \"\$item\" ]; then
                    cp \"\$item\" ${SERVER_DIR}/backend/ 2>/dev/null || echo \"Errore copia \${item}\"
                elif [ -d \"\$item\" ]; then
                    cp -r \"\$item\" ${SERVER_DIR}/backend/ 2>/dev/null || echo \"Errore copia directory \${item}\"
                fi
            done
        fi
    else
        echo \"ATTENZIONE: Directory backend non trovata nell'archivio\"
    fi
    
    # Frontend files
    if [ -d frontend ]; then
        echo \"Copia file frontend...\"
        rm -rf ${SERVER_DIR}/frontend || true
        if cp -r frontend ${SERVER_DIR}/; then
            echo \"File frontend copiati\"
        else
            echo \"ERRORE: Copia frontend fallita\"
            exit 1
        fi
    else
        echo \"ATTENZIONE: Directory frontend non trovata nell'archivio\"
    fi
    
    # Scripts
    if [ -f start.sh ]; then
        echo \"Copia start.sh...\"
        if cp start.sh ${SERVER_DIR}/; then
            chmod +x ${SERVER_DIR}/start.sh || true
            echo \"start.sh copiato\"
        else
            echo \"ERRORE: Copia start.sh fallita\"
            exit 1
        fi
    fi
    
    # Script di fix produzione
    if [ -f fix_production.sh ]; then
        echo \"Copia fix_production.sh...\"
        cp fix_production.sh ${SERVER_DIR}/ && chmod +x ${SERVER_DIR}/fix_production.sh && echo \"fix_production.sh copiato\" || echo \"ATTENZIONE: fix_production.sh non copiato\"
    fi
    
    # Cleanup
    echo \"Pulizia file temporanei...\"
    rm -rf \"\${TEMP_DIR}\" \"\${ARCHIVE}\" || true
    echo \"Pulizia completata\"
    
    # Aggiorna dipendenze Python se necessario
    if [ -f ${SERVER_DIR}/requirements.txt ]; then
        source ${SERVER_DIR}/venv/bin/activate 2>/dev/null || true
        pip install -q -r ${SERVER_DIR}/requirements.txt 2>/dev/null || true
        deactivate 2>/dev/null || true
    fi
    
    # Aggiorna database schema
    cd ${SERVER_DIR}
    source venv/bin/activate 2>/dev/null || true
    python -c 'from database import Base, engine; Base.metadata.create_all(bind=engine)' 2>/dev/null || true
    deactivate 2>/dev/null || true
    
    # Applica migrazioni database specifiche
    echo 'Verifica e applicazione migrazioni database...'
    cd ${SERVER_DIR}
    source venv/bin/activate 2>/dev/null || true
    
    # Usa script Python per verificare e applicare migrazioni
    # Prova diversi percorsi possibili
    DB_SCRIPT=\"\"
    for script_path in \"${SERVER_DIR}/backend/scripts/verify_database.py\" \"${SERVER_DIR}/scripts/verify_database.py\"; do
        if [ -f \"\${script_path}\" ]; then
            DB_SCRIPT=\"\${script_path}\"
            break
        fi
    done
    
    if [ -n \"\${DB_SCRIPT}\" ] && [ -f \"\${DB_SCRIPT}\" ]; then
        echo \"Esecuzione script: \${DB_SCRIPT}\"
        cd ${SERVER_DIR}/backend 2>/dev/null || cd ${SERVER_DIR}
        python \"\${DB_SCRIPT}\" 2>&1 || {
            echo 'Errore durante verifica database, applicazione migrazioni manuali...'
            
            # Fallback: migrazioni manuali
            DB_FILE=\"\"
            for path in \"/var/lib/dapx-backandrepl/dapx.db\" \"${SERVER_DIR}/dapx.db\" \"${SERVER_DIR}/sanoid-manager.db\" \"/var/lib/sanoid-manager/sanoid-manager.db\"; do
                if [ -f \"\${path}\" ]; then
                    DB_FILE=\"\${path}\"
                    break
                fi
            done
            
            if [ -n \"\${DB_FILE}\" ] && [ -f \"\${DB_FILE}\" ]; then
                # Verifica e aggiungi colonna notify_on_each_run
                sqlite3 \"\${DB_FILE}\" \"PRAGMA table_info(recovery_jobs);\" 2>/dev/null | grep -q \"notify_on_each_run\" || {
                    echo 'Aggiunta colonna notify_on_each_run...'
                    sqlite3 \"\${DB_FILE}\" \"ALTER TABLE recovery_jobs ADD COLUMN notify_on_each_run BOOLEAN DEFAULT 0;\" 2>/dev/null || true
                }
                echo 'Migrazioni manuali completate'
            else
                echo 'Database non trovato per migrazioni manuali'
            fi
        }
    else
        echo 'Script verify_database.py non trovato, applicazione migrazioni base...'
        # Migrazione base
        DB_FILE=\"\"
        for path in \"/var/lib/dapx-backandrepl/dapx.db\" \"${SERVER_DIR}/dapx.db\" \"${SERVER_DIR}/sanoid-manager.db\" \"/var/lib/sanoid-manager/sanoid-manager.db\"; do
            if [ -f \"\${path}\" ]; then
                DB_FILE=\"\${path}\"
                break
            fi
        done
        
        if [ -n \"\${DB_FILE}\" ] && [ -f \"\${DB_FILE}\" ]; then
            sqlite3 \"\${DB_FILE}\" \"PRAGMA table_info(recovery_jobs);\" 2>/dev/null | grep -q \"notify_on_each_run\" || {
                sqlite3 \"\${DB_FILE}\" \"ALTER TABLE recovery_jobs ADD COLUMN notify_on_each_run BOOLEAN DEFAULT 0;\" 2>/dev/null || true
            }
        fi
    fi
    
    deactivate 2>/dev/null || true
    
    # Verifica che i file siano stati copiati
    echo 'Verifica file copiati...'
    if [ -f ${SERVER_DIR}/backend/routers/host_info.py ]; then
        echo '✓ host_info.py copiato'
    else
        echo '✗ ERRORE: host_info.py non trovato!'
    fi
    if [ -f ${SERVER_DIR}/backend/services/host_info_service.py ]; then
        echo '✓ host_info_service.py copiato'
    else
        echo '✗ ERRORE: host_info_service.py non trovato!'
    fi
    if [ -f ${SERVER_DIR}/frontend/dist/index.html ]; then
        echo '✓ index.html copiato'
    else
        echo '✗ ERRORE: index.html non trovato!'
    fi
    
    # Verifica che la porta sia libera prima di riavviare
    echo 'Verifica porta 8420...'
    if command -v lsof >/dev/null 2>&1; then
        PORT_PID=\$(lsof -ti :8420 2>/dev/null)
        if [ -n \"\${PORT_PID}\" ]; then
            echo \"ATTENZIONE: Porta 8420 ancora in uso da processo \${PORT_PID}, terminazione forzata...\"
            kill -9 \${PORT_PID} 2>/dev/null || true
            sleep 2
        else
            echo '✓ Porta 8420 libera'
        fi
    fi
    
    # Restart servizio (non solo start, per assicurarsi che ricarichi i file)
    echo 'Riavvio servizio sanoid-manager...'
    systemctl restart sanoid-manager 2>/dev/null || {
        echo 'Errore restart servizio, provo stop + start...'
        systemctl stop sanoid-manager 2>/dev/null || true
        sleep 2
        # Verifica ancora una volta che non ci siano processi relitti
        pkill -9 -f 'uvicorn.*main:app' 2>/dev/null || true
        pkill -9 -f 'python.*backend/main\.py' 2>/dev/null || true
        sleep 1
        systemctl start sanoid-manager 2>/dev/null || true
    }
    
    # Verifica stato servizio
    sleep 3
    if systemctl is-active --quiet sanoid-manager; then
        echo '✓ Servizio attivo'
        # Verifica che la porta sia effettivamente in uso dal servizio
        if command -v lsof >/dev/null 2>&1; then
            PORT_PID=\$(lsof -ti :8420 2>/dev/null)
            if [ -n \"\${PORT_PID}\" ]; then
                echo \"✓ Porta 8420 in uso da processo \${PORT_PID}\"
            else
                echo '⚠ ATTENZIONE: Servizio attivo ma porta 8420 non in uso!'
            fi
        fi
    else
        echo '✗ ATTENZIONE: Servizio non attivo!'
        systemctl status sanoid-manager --no-pager -l || true
        echo ''
        echo 'Processi Python/uvicorn ancora in esecuzione:'
        ps aux | grep -E '(uvicorn|python.*main)' | grep -v grep || echo 'Nessuno'
    fi
    
    echo 'Installazione completata'
    
    # Se disponibile, esegui script di fix
    if [ -f ${SERVER_DIR}/fix_production.sh ]; then
        echo 'Esecuzione script di fix...'
        bash ${SERVER_DIR}/fix_production.sh || {
            echo 'ATTENZIONE: Script di fix ha riportato errori, verifica manualmente'
        }
    fi
    
    exit 0
"
SSH_EXIT_CODE=$?
if [ $SSH_EXIT_CODE -ne 0 ]; then
    log_error "Errore installazione sul server (exit code: $SSH_EXIT_CODE)"
    log_info ""
    log_info "Per risolvere manualmente, esegui sul server:"
    log_info "  ssh ${SERVER_USER}@${SERVER}"
    log_info "  bash /opt/dapx-backandrepl/fix_production.sh"
    log_info ""
    log_info "Oppure verifica i log:"
    log_info "  ssh ${SERVER_USER}@${SERVER} 'journalctl -u sanoid-manager -n 50 --no-pager'"
    rm -f "$TEMP_ARCHIVE"
    exit 1
fi

# Cleanup locale
rm -f "$TEMP_ARCHIVE"

log_success "Deploy completato!"
log_info ""
log_info "Verifica lo stato del servizio con:"
log_info "  ssh ${SERVER_USER}@${SERVER} 'systemctl status sanoid-manager'"

