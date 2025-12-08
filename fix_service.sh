#!/bin/bash
# Script per diagnosticare e correggere problemi del servizio

echo "=== DIAGNOSTICA SERVIZIO SANOID-MANAGER ==="
echo ""

SERVICE_NAME="sanoid-manager"
SERVER_DIR="/opt/dapx-backandrepl"

echo "1. Verifica processi Python/uvicorn in esecuzione:"
ps aux | grep -E "(uvicorn|python.*main\.py|python.*backend)" | grep -v grep || echo "  Nessun processo trovato"
echo ""

echo "2. Verifica porta 8420:"
if command -v lsof >/dev/null 2>&1; then
    lsof -i :8420 || echo "  Porta 8420 libera"
elif command -v netstat >/dev/null 2>&1; then
    netstat -tlnp 2>/dev/null | grep 8420 || echo "  Porta 8420 libera"
elif command -v ss >/dev/null 2>&1; then
    ss -tlnp 2>/dev/null | grep 8420 || echo "  Porta 8420 libera"
else
    echo "  Impossibile verificare porta (lsof/netstat/ss non disponibili)"
fi
echo ""

echo "3. Stato servizio systemd:"
systemctl status $SERVICE_NAME --no-pager -l | head -20
echo ""

echo "4. Configurazione servizio:"
systemctl cat $SERVICE_NAME 2>/dev/null | head -30 || echo "  Servizio non trovato"
echo ""

echo "5. Verifica file principali:"
echo "  Directory: $SERVER_DIR"
[ -d "$SERVER_DIR" ] && echo "    ✓ Directory esiste" || echo "    ✗ Directory NON esiste"
[ -f "$SERVER_DIR/backend/main.py" ] && echo "    ✓ main.py presente" || echo "    ✗ main.py mancante"
[ -f "$SERVER_DIR/venv/bin/uvicorn" ] && echo "    ✓ uvicorn presente" || echo "    ✗ uvicorn mancante"
[ -f "$SERVER_DIR/start.sh" ] && echo "    ✓ start.sh presente" || echo "    ✗ start.sh mancante"
echo ""

echo "6. Ultimi 20 log del servizio:"
journalctl -u $SERVICE_NAME -n 20 --no-pager --no-hostname
echo ""

echo "7. Test import Python:"
if [ -f "$SERVER_DIR/venv/bin/activate" ]; then
    cd "$SERVER_DIR/backend" 2>/dev/null || cd "$SERVER_DIR"
    source ../venv/bin/activate 2>/dev/null || source venv/bin/activate 2>/dev/null
    python3 -c "
import sys
try:
    from routers import host_info
    print('  ✓ Import host_info OK')
except Exception as e:
    print(f'  ✗ Errore import host_info: {e}')
    import traceback
    traceback.print_exc()
" 2>&1 | head -20
    deactivate 2>/dev/null || true
else
    echo "  ✗ Virtual environment non trovato"
fi
echo ""

echo "=== OPZIONI DI RIPARAZIONE ==="
echo ""
read -p "Vuoi terminare tutti i processi Python/uvicorn relitti? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Terminazione processi..."
    pkill -9 -f 'uvicorn.*main:app' 2>/dev/null && echo "  ✓ Processi uvicorn terminati" || echo "  Nessun processo uvicorn trovato"
    pkill -9 -f 'python.*backend/main\.py' 2>/dev/null && echo "  ✓ Processi python backend terminati" || echo "  Nessun processo python backend trovato"
    pkill -9 -f 'python.*main:app' 2>/dev/null && echo "  ✓ Altri processi python terminati" || echo "  Nessun altro processo trovato"
    
    # Termina processi sulla porta 8420
    if command -v lsof >/dev/null 2>&1; then
        PORT_PIDS=$(lsof -ti :8420 2>/dev/null)
        if [ -n "$PORT_PIDS" ]; then
            echo "  Terminazione processi sulla porta 8420..."
            for pid in $PORT_PIDS; do
                kill -9 $pid 2>/dev/null && echo "    ✓ Processo $pid terminato" || echo "    ✗ Errore terminazione $pid"
            done
        fi
    fi
    sleep 2
fi

echo ""
read -p "Vuoi riavviare il servizio? (y/N): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    echo "Riavvio servizio..."
    systemctl stop $SERVICE_NAME 2>/dev/null || true
    sleep 2
    systemctl start $SERVICE_NAME 2>/dev/null || true
    sleep 3
    if systemctl is-active --quiet $SERVICE_NAME; then
        echo "  ✓ Servizio avviato correttamente"
    else
        echo "  ✗ Servizio non avviato, verifica log:"
        systemctl status $SERVICE_NAME --no-pager -l | tail -10
    fi
fi

echo ""
echo "=== FINE DIAGNOSTICA ==="



