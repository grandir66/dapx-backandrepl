#!/bin/bash
#
# Script per trovare e scaricare template disponibili
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

log_warning() {
    echo -e "${YELLOW}[!]${NC} $1"
}

log_error() {
    echo -e "${RED}[✗]${NC} $1"
}

echo -e "${BLUE}════════════════════════════════════════════════${NC}"
echo -e "${BLUE}Ricerca Template Disponibili${NC}"
echo -e "${BLUE}════════════════════════════════════════════════${NC}"
echo ""

# Verifica che pveam esista
if ! command -v pveam &> /dev/null; then
    log_error "pveam non trovato. Questo script deve essere eseguito su un nodo Proxmox."
    exit 1
fi

# Lista template già scaricati
log_info "Template già presenti nel sistema:"
if [ -d "/var/lib/vz/template/cache" ]; then
    ls -lh /var/lib/vz/template/cache/*.tar.zst 2>/dev/null | awk '{print "  " $9}' | xargs -n1 basename || echo "  Nessun template trovato"
else
    echo "  Directory template non trovata"
fi
echo ""

# Lista template disponibili per download
log_info "Template Debian disponibili per download:"
echo ""
DEBIAN_TEMPLATES=$(pveam available --section system 2>/dev/null | grep -i debian || echo "")
if [ -z "${DEBIAN_TEMPLATES}" ]; then
    log_warning "Nessun template Debian trovato nella lista disponibili."
    log_info "Tentativo aggiornamento repository template..."
    pveam update 2>/dev/null || true
    echo ""
    log_info "Template disponibili (tutti):"
    pveam available --section system 2>/dev/null | head -20
else
    echo "${DEBIAN_TEMPLATES}" | head -10
fi
echo ""

# Suggerimenti
log_info "Per scaricare un template, usa:"
echo "  pveam download local <nome-template>"
echo ""
log_info "Esempi comuni:"
echo "  pveam download local debian-12-standard_12.0-1_amd64.tar.zst"
echo "  pveam download local debian-11-standard_11.9-1_amd64.tar.zst"
echo "  pveam download local ubuntu-22.04-standard_22.04-1_amd64.tar.zst"
echo ""

# Prova a trovare template Debian con nomi comuni
log_info "Tentativo download template comuni..."
echo ""

TEMPLATES_TO_TRY=(
    "debian-12-standard"
    "debian-11-standard"
    "debian-10-standard"
    "ubuntu-22.04-standard"
    "ubuntu-20.04-standard"
)

DOWNLOADED=0
for TEMPLATE in "${TEMPLATES_TO_TRY[@]}"; do
    log_info "Tentativo: ${TEMPLATE}..."
    if pveam download local "${TEMPLATE}" 2>/dev/null; then
        log_success "Template ${TEMPLATE} scaricato con successo!"
        DOWNLOADED=1
        break
    fi
done

if [ ${DOWNLOADED} -eq 0 ]; then
    log_warning "Nessun template comune disponibile."
    echo ""
    log_info "Istruzioni manuali:"
    echo ""
    echo "1. Aggiorna repository template:"
    echo "   pveam update"
    echo ""
    echo "2. Lista template disponibili:"
    echo "   pveam available --section system"
    echo ""
    echo "3. Cerca template Debian:"
    echo "   pveam available --section system | grep debian"
    echo ""
    echo "4. Scarica il template trovato (usa il nome completo):"
    echo "   pveam download local <nome-completo-template>"
    echo ""
    log_info "Nota: Il nome del template deve essere esatto come mostrato da 'pveam available'"
fi

