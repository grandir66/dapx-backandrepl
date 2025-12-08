#!/bin/bash
#
# DAPX-backandrepl - Installazione dentro container LXC
# Script da eseguire dentro il container LXC
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

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

# ============== CONFIGURAZIONE ==============
INSTALL_DIR="/opt/dapx-backandrepl"
DATA_DIR="/var/lib/dapx-backandrepl"
LOG_DIR="/var/log/dapx-backandrepl"
CONFIG_DIR="/etc/dapx-backandrepl"
SERVICE_USER="root"
SERVICE_PORT="8420"
PYTHON_MIN_VERSION="3.9"
GITHUB_REPO="grandir66/dapx-backandrepl"

log_info "════════════════════════════════════════════════"
log_info "Installazione DAPX-backandrepl in Container LXC"
log_info "════════════════════════════════════════════════"

# Verifica Python e pip
log_info "Verifica Python3 e pip3..."
apt-get update
apt-get install -y python3 python3-pip python3-venv python3-full

# Verifica versione
PYTHON_VERSION=$(python3 --version | cut -d' ' -f2 | cut -d'.' -f1,2)
log_info "Python versione: ${PYTHON_VERSION}"

# Verifica pip
if ! command -v pip3 &> /dev/null; then
    log_error "pip3 non trovato dopo installazione"
    # Prova installazione alternativa
    apt-get install -y python3-pip || python3 -m ensurepip --upgrade
fi

# Crea directory
log_info "Creazione directory..."
mkdir -p ${INSTALL_DIR} ${DATA_DIR} ${LOG_DIR} ${CONFIG_DIR}

# Installa dipendenze sistema
log_info "Installazione dipendenze sistema..."
apt-get update
apt-get install -y \
    git \
    openssh-client \
    ca-certificates \
    curl \
    wget \
    rsync \
    build-essential \
    libssl-dev \
    libffi-dev \
    python3-dev

# Clona repository
log_info "Download applicazione..."
if [ -d "${INSTALL_DIR}/.git" ]; then
    log_info "Repository già presente, aggiornamento..."
    cd ${INSTALL_DIR}
    git pull
else
    cd /tmp
    git clone https://github.com/${GITHUB_REPO}.git dapx-backandrepl
    mv dapx-backandrepl/* ${INSTALL_DIR}/
    rm -rf dapx-backandrepl
fi

# Installa dipendenze Python
log_info "Installazione dipendenze Python..."
cd ${INSTALL_DIR}/backend

# In Debian 12+ pip richiede --break-system-packages o venv
# Usiamo --break-system-packages per semplicità in container dedicato
pip3 install --no-cache-dir --break-system-packages -r requirements.txt 2>/dev/null || \
pip3 install --no-cache-dir -r requirements.txt

# Crea file di configurazione
log_info "Creazione configurazione..."

# Genera secret key
SECRET_KEY=$(openssl rand -hex 32)

cat > ${CONFIG_DIR}/.env << EOF
DAPX_DB=${DATA_DIR}/dapx-backandrepl.db
DAPX_PORT=${SERVICE_PORT}
DAPX_LOG_LEVEL=INFO
DAPX_SECRET_KEY=${SECRET_KEY}
DAPX_TOKEN_EXPIRE=480
DAPX_CORS_ORIGINS=
EOF

# Crea systemd service
log_info "Creazione servizio systemd..."
cat > /etc/systemd/system/dapx-backandrepl.service << EOF
[Unit]
Description=DAPX-backandrepl - Backup & Replica per Proxmox
Documentation=https://github.com/${GITHUB_REPO}
After=network.target

[Service]
Type=simple
User=${SERVICE_USER}
WorkingDirectory=${INSTALL_DIR}/backend
Environment="PYTHONPATH=${INSTALL_DIR}/backend"
EnvironmentFile=${CONFIG_DIR}/.env
ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port ${SERVICE_PORT}
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=dapx-backandrepl

# Security
NoNewPrivileges=true
PrivateTmp=true

# Resource limits
LimitNOFILE=65536
MemoryMax=2G
CPUQuota=200%

[Install]
WantedBy=multi-user.target
EOF

# Abilita e avvia servizio
log_info "Abilitazione servizio..."
systemctl daemon-reload
systemctl enable dapx-backandrepl
systemctl start dapx-backandrepl

# Attendi avvio
sleep 3

# Verifica servizio
if systemctl is-active --quiet dapx-backandrepl; then
    log_success "Servizio avviato con successo"
else
    log_error "Errore avvio servizio. Controlla: systemctl status dapx-backandrepl"
    exit 1
fi

# Informazioni finali
log_success "════════════════════════════════════════════════"
log_success "Installazione completata!"
echo ""
log_info "Directory installazione: ${INSTALL_DIR}"
log_info "Directory dati: ${DATA_DIR}"
log_info "Directory log: ${LOG_DIR}"
log_info "Directory config: ${CONFIG_DIR}"
echo ""
log_info "Accesso Web UI:"
echo "  http://<IP-CONTAINER>:${SERVICE_PORT}"
echo ""
log_info "Comandi utili:"
echo "  systemctl status dapx-backandrepl"
echo "  systemctl restart dapx-backandrepl"
echo "  journalctl -u dapx-backandrepl -f"
echo ""
log_success "════════════════════════════════════════════════"

