#!/bin/bash
# Script completo per diagnosticare e correggere problemi sul server di produzione

set +e  # Non uscire al primo errore, gestiamo gli errori manualmente

SERVICE_NAME="sanoid-manager"
SERVER_DIR="/opt/dapx-backandrepl"
SERVICE_PORT=8420

echo "=========================================="
echo "  FIX SERVIZIO SANOID-MANAGER"
echo "=========================================="
echo ""

# 1. Termina tutti i processi relitti
echo "[1/8] Pulizia processi relitti..."
pkill -9 -f 'uvicorn.*main:app' 2>/dev/null && echo "  ✓ Processi uvicorn terminati" || echo "  Nessun processo uvicorn"
pkill -9 -f 'python.*backend/main\.py' 2>/dev/null && echo "  ✓ Processi python backend terminati" || echo "  Nessun processo python backend"
pkill -9 -f 'python.*main:app' 2>/dev/null && echo "  ✓ Altri processi python terminati" || echo "  Nessun altro processo"

# Termina processi sulla porta 8420
if command -v lsof >/dev/null 2>&1; then
    PORT_PIDS=$(lsof -ti :$SERVICE_PORT 2>/dev/null)
    if [ -n "$PORT_PIDS" ]; then
        echo "  Terminazione processi sulla porta $SERVICE_PORT..."
        for pid in $PORT_PIDS; do
            kill -9 $pid 2>/dev/null && echo "    ✓ Processo $pid terminato" || true
        done
    fi
fi
sleep 2
echo ""

# 2. Stop servizio
echo "[2/8] Stop servizio systemd..."
systemctl stop $SERVICE_NAME 2>/dev/null || true
sleep 2
echo ""

# 3. Verifica configurazione servizio
echo "[3/8] Verifica configurazione servizio..."
SERVICE_FILE="/etc/systemd/system/${SERVICE_NAME}.service"
if [ -f "$SERVICE_FILE" ]; then
    echo "  ✓ File servizio trovato: $SERVICE_FILE"
    echo "  Contenuto ExecStart:"
    grep "ExecStart" "$SERVICE_FILE" | head -1
    echo "  Contenuto WorkingDirectory:"
    grep "WorkingDirectory" "$SERVICE_FILE" | head -1
else
    echo "  ✗ File servizio NON trovato!"
    echo "  Creazione file servizio..."
    cat > "$SERVICE_FILE" << EOF
[Unit]
Description=Sanoid Manager - ZFS Snapshot Management Web Interface
After=network.target network-online.target
Wants=network-online.target

[Service]
Type=simple
User=root
Group=root
WorkingDirectory=${SERVER_DIR}/backend

# Environment
Environment="PATH=${SERVER_DIR}/venv/bin:/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

# Execution
ExecStart=${SERVER_DIR}/venv/bin/uvicorn main:app --host 0.0.0.0 --port ${SERVICE_PORT} --workers 1
ExecReload=/bin/kill -HUP \$MAINPID

# Restart policy
Restart=always
RestartSec=10
TimeoutStartSec=30
TimeoutStopSec=30

# Logging
StandardOutput=journal
StandardError=journal

# Security
NoNewPrivileges=false
ProtectSystem=false
PrivateTmp=true
ProtectHome=false
ReadWritePaths=${SERVER_DIR} /var/lib/dapx-backandrepl /root/.ssh

[Install]
WantedBy=multi-user.target
EOF
    systemctl daemon-reload
    echo "  ✓ File servizio creato"
fi
echo ""

# 4. Verifica file e directory
echo "[4/8] Verifica file e directory..."
[ -d "$SERVER_DIR" ] && echo "  ✓ Directory $SERVER_DIR esiste" || echo "  ✗ Directory $SERVER_DIR NON esiste"
[ -d "$SERVER_DIR/backend" ] && echo "  ✓ Directory backend esiste" || echo "  ✗ Directory backend NON esiste"
[ -f "$SERVER_DIR/backend/main.py" ] && echo "  ✓ main.py presente" || echo "  ✗ main.py mancante"
[ -f "$SERVER_DIR/venv/bin/uvicorn" ] && echo "  ✓ uvicorn presente" || echo "  ✗ uvicorn mancante"
[ -f "$SERVER_DIR/backend/routers/host_info.py" ] && echo "  ✓ host_info.py presente" || echo "  ✗ host_info.py mancante"
[ -f "$SERVER_DIR/backend/services/host_info_service.py" ] && echo "  ✓ host_info_service.py presente" || echo "  ✗ host_info_service.py mancante"
echo ""

# 5. Verifica virtual environment
echo "[5/8] Verifica virtual environment..."
if [ -f "$SERVER_DIR/venv/bin/activate" ]; then
    echo "  ✓ Virtual environment trovato"
    source "$SERVER_DIR/venv/bin/activate"
    # Verifica dipendenze critiche
    python3 -c "import fastapi" 2>/dev/null && echo "  ✓ fastapi installato" || echo "  ✗ fastapi mancante"
    python3 -c "import uvicorn" 2>/dev/null && echo "  ✓ uvicorn installato" || echo "  ✗ uvicorn mancante"
    python3 -c "import sqlalchemy" 2>/dev/null && echo "  ✓ sqlalchemy installato" || echo "  ✗ sqlalchemy mancante"
    deactivate
else
    echo "  ✗ Virtual environment NON trovato!"
    echo "  Creazione virtual environment..."
    python3 -m venv "$SERVER_DIR/venv" || {
        echo "  ✗ Errore creazione venv"
        exit 1
    }
    source "$SERVER_DIR/venv/bin/activate"
    if [ -f "$SERVER_DIR/backend/requirements.txt" ]; then
        echo "  Installazione dipendenze..."
        if ! pip install -q -r "$SERVER_DIR/backend/requirements.txt"; then
            echo "  ✗ Errore installazione dipendenze"
            exit 1
        fi
    fi
    deactivate 2>/dev/null || true
    echo "  ✓ Virtual environment creato"
fi
echo ""

# 6. Test import Python
echo "[6/8] Test import moduli Python..."
cd "$SERVER_DIR/backend" 2>/dev/null || cd "$SERVER_DIR"
source "$SERVER_DIR/venv/bin/activate"
python3 -c "
import sys
errors = []
try:
    from routers import host_info
    print('  ✓ Import host_info OK')
except Exception as e:
    errors.append(f'host_info: {e}')
    print(f'  ✗ Errore import host_info: {e}')

try:
    from services import host_info_service
    print('  ✓ Import host_info_service OK')
except Exception as e:
    errors.append(f'host_info_service: {e}')
    print(f'  ✗ Errore import host_info_service: {e}')

try:
    from main import app
    print('  ✓ Import main OK')
except Exception as e:
    errors.append(f'main: {e}')
    print(f'  ✗ Errore import main: {e}')
    import traceback
    traceback.print_exc()

if errors:
    sys.exit(1)
" 2>&1
IMPORT_OK=$?
deactivate
if [ $IMPORT_OK -ne 0 ]; then
    echo "  ✗ ERRORE: Import falliti, verifica dipendenze"
    echo "  Esegui: cd $SERVER_DIR/backend && source ../venv/bin/activate && pip install -r requirements.txt"
    exit 1
fi
echo ""

# 7. Verifica porta libera
echo "[7/8] Verifica porta $SERVICE_PORT..."
if command -v lsof >/dev/null 2>&1; then
    PORT_PID=$(lsof -ti :$SERVICE_PORT 2>/dev/null)
    if [ -n "$PORT_PID" ]; then
        echo "  ⚠ Porta ancora in uso da processo $PORT_PID, terminazione forzata..."
        kill -9 $PORT_PID 2>/dev/null || true
        sleep 2
    fi
    PORT_PID=$(lsof -ti :$SERVICE_PORT 2>/dev/null)
    if [ -z "$PORT_PID" ]; then
        echo "  ✓ Porta $SERVICE_PORT libera"
    else
        echo "  ✗ Porta $SERVICE_PORT ancora in uso!"
    fi
else
    echo "  ⚠ Impossibile verificare porta (lsof non disponibile)"
fi
echo ""

# 8. Riavvio servizio
echo "[8/8] Riavvio servizio..."
systemctl daemon-reload
systemctl enable $SERVICE_NAME 2>/dev/null || true
systemctl start $SERVICE_NAME 2>/dev/null || {
    echo "  ✗ Errore avvio servizio"
    echo "  Log servizio:"
    journalctl -u $SERVICE_NAME -n 30 --no-pager --no-hostname
    exit 1
}

sleep 3

if systemctl is-active --quiet $SERVICE_NAME; then
    echo "  ✓ Servizio avviato correttamente"
    
    # Verifica porta
    if command -v lsof >/dev/null 2>&1; then
        PORT_PID=$(lsof -ti :$SERVICE_PORT 2>/dev/null)
        if [ -n "$PORT_PID" ]; then
            echo "  ✓ Porta $SERVICE_PORT in uso da processo $PORT_PID"
        else
            echo "  ⚠ Servizio attivo ma porta $SERVICE_PORT non in uso"
        fi
    fi
    
    echo ""
    echo "=========================================="
    echo "  ✓ SERVIZIO RIPARATO E AVVIATO"
    echo "=========================================="
    echo ""
    echo "Verifica stato:"
    echo "  systemctl status $SERVICE_NAME"
    echo ""
    echo "Log in tempo reale:"
    echo "  journalctl -u $SERVICE_NAME -f"
    echo ""
    echo "Test connessione:"
    echo "  curl http://localhost:$SERVICE_PORT/api/auth/login"
else
    echo "  ✗ Servizio NON avviato!"
    echo ""
    echo "Log errori:"
    journalctl -u $SERVICE_NAME -n 50 --no-pager --no-hostname | tail -30
    echo ""
    echo "=========================================="
    echo "  ✗ ERRORE: Servizio non avviato"
    echo "=========================================="
    exit 1
fi

