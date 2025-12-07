#!/bin/bash
# Script per verificare lo stato del servizio e pulire processi relitti

echo "=== Verifica nome servizio ==="
SERVICE_NAME="sanoid-manager"
echo "Servizio: $SERVICE_NAME"

echo ""
echo "=== Stato servizio systemd ==="
systemctl status $SERVICE_NAME --no-pager -l | head -15

echo ""
echo "=== Processi Python/uvicorn in esecuzione ==="
ps aux | grep -E "(uvicorn|python.*main\.py|python.*backend)" | grep -v grep

echo ""
echo "=== Porta 8420 in uso ==="
lsof -i :8420 2>/dev/null || netstat -tlnp 2>/dev/null | grep 8420 || ss -tlnp 2>/dev/null | grep 8420

echo ""
echo "=== Processi che potrebbero essere relitti ==="
# Cerca processi uvicorn o python che potrebbero essere vecchie istanze
OLD_PIDS=$(ps aux | grep -E "uvicorn.*main:app|python.*backend/main\.py" | grep -v grep | awk '{print $2}')
if [ -n "$OLD_PIDS" ]; then
    echo "Trovati processi potenzialmente relitti:"
    ps aux | grep -E "uvicorn.*main:app|python.*backend/main\.py" | grep -v grep
    echo ""
    read -p "Vuoi terminare questi processi? (y/N): " -n 1 -r
    echo
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        for pid in $OLD_PIDS; do
            echo "Terminando processo $pid..."
            kill -TERM $pid 2>/dev/null || kill -KILL $pid 2>/dev/null
        done
        sleep 2
        echo "Processi terminati"
    fi
else
    echo "Nessun processo relitto trovato"
fi

echo ""
echo "=== Ultimi 30 log con errori ==="
journalctl -u $SERVICE_NAME -n 30 --no-pager | grep -i error || echo "Nessun errore trovato negli ultimi 30 log"

echo ""
echo "=== Ultimi 20 log completi ==="
journalctl -u $SERVICE_NAME -n 20 --no-pager

echo ""
echo "=== Verifica file principali ==="
SERVER_DIR="/opt/dapx-backandrepl"
echo "Directory: $SERVER_DIR"
ls -la $SERVER_DIR/backend/routers/host_info.py 2>/dev/null && echo "✓ host_info.py presente" || echo "✗ host_info.py mancante"
ls -la $SERVER_DIR/backend/services/host_info_service.py 2>/dev/null && echo "✓ host_info_service.py presente" || echo "✗ host_info_service.py mancante"
ls -la $SERVER_DIR/backend/main.py 2>/dev/null && echo "✓ main.py presente" || echo "✗ main.py mancante"

echo ""
echo "=== Test import Python ==="
if [ -d "$SERVER_DIR/backend" ] && [ -f "$SERVER_DIR/venv/bin/activate" ]; then
    cd $SERVER_DIR/backend
    source ../venv/bin/activate
    python3 -c "
import sys
try:
    from routers import host_info
    print('✓ Import host_info OK')
except Exception as e:
    print(f'✗ Errore import host_info: {e}')
    import traceback
    traceback.print_exc()
" 2>&1
    deactivate
else
    echo "Directory o venv non trovati"
fi

echo ""
echo "=== Configurazione servizio systemd ==="
systemctl cat $SERVICE_NAME 2>/dev/null | head -20
