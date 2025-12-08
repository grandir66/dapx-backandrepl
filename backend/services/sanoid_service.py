"""
Sanoid Service - Gestione configurazione e operazioni Sanoid
"""

import asyncio
from typing import Optional, List, Dict, Tuple
import logging
from dataclasses import dataclass

from services.ssh_service import ssh_service, SSHResult

logger = logging.getLogger(__name__)


SANOID_CONF_PATH = "/etc/sanoid/sanoid.conf"
SANOID_DEFAULTS_PATH = "/etc/sanoid/sanoid.defaults.conf"


@dataclass
class SanoidTemplate:
    """Template Sanoid predefinito"""
    name: str
    hourly: int
    daily: int
    weekly: int
    monthly: int
    yearly: int
    autosnap: bool = True
    autoprune: bool = True


# Template predefiniti
DEFAULT_TEMPLATES = {
    "production": SanoidTemplate("production", hourly=48, daily=90, weekly=12, monthly=24, yearly=5),
    "default": SanoidTemplate("default", hourly=24, daily=30, weekly=4, monthly=12, yearly=0),
    "minimal": SanoidTemplate("minimal", hourly=12, daily=7, weekly=0, monthly=0, yearly=0),
    "backup": SanoidTemplate("backup", hourly=0, daily=30, weekly=8, monthly=12, yearly=2),
    "vm": SanoidTemplate("vm", hourly=24, daily=14, weekly=4, monthly=6, yearly=0),
}


class SanoidService:
    """Servizio per gestione Sanoid su nodi remoti"""
    
    async def install_sanoid(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """Installa Sanoid su un nodo Proxmox/Debian"""
        
        # Prima verifica se già installato (veloce)
        check_result = await ssh_service.execute(
            hostname=hostname,
            command="command -v sanoid && sanoid --version 2>/dev/null",
            port=port,
            username=username,
            key_path=key_path,
            timeout=30
        )
        
        if check_result.success and "sanoid" in check_result.stdout.lower():
            return True, f"Sanoid già installato: {check_result.stdout.strip()}"
        
        install_script = """
#!/bin/bash
set -e

echo "=== Installazione Sanoid ==="

# Verifica connessione internet
if ! ping -c 1 github.com &>/dev/null; then
    echo "ERRORE: Nessuna connessione a internet"
    exit 1
fi

# Metodo 1: Prova con apt (Debian/Ubuntu)
echo "Tentativo installazione da repository..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq

# Su alcune versioni Debian/Proxmox sanoid è disponibile nel repo
if apt-cache show sanoid &>/dev/null; then
    echo "Sanoid disponibile nel repository, installo..."
    apt-get install -y -qq sanoid
    if command -v sanoid &>/dev/null; then
        echo "Installato da repository"
        sanoid --version
        mkdir -p /etc/sanoid
        touch /etc/sanoid/sanoid.conf
        exit 0
    fi
fi

# Metodo 2: Installazione manuale
echo "Installazione manuale..."

# Installa dipendenze
apt-get install -y -qq debhelper libcapture-tiny-perl libconfig-inifiles-perl pv lzop mbuffer git build-essential 2>/dev/null || true

# Clona repository
cd /tmp
rm -rf sanoid sanoid_*.deb 2>/dev/null || true
timeout 120 git clone --depth 1 https://github.com/jimsalterjrs/sanoid.git || {
    echo "ERRORE: Clone git fallito (timeout o rete)"
    exit 1
}
cd sanoid

# Prova build con dpkg
echo "Tentativo build pacchetto..."
if [ -d "packages/debian" ]; then
    ln -sf packages/debian . 2>/dev/null || true
    if dpkg-buildpackage -uc -us -b 2>/dev/null; then
        apt-get install -y ../sanoid_*.deb 2>/dev/null && {
            echo "Installato con dpkg-buildpackage"
            sanoid --version
            mkdir -p /etc/sanoid
            touch /etc/sanoid/sanoid.conf
            rm -rf /tmp/sanoid /tmp/sanoid_*.deb 2>/dev/null || true
            exit 0
        }
    fi
fi

# Metodo 3: Installazione diretta (fallback)
echo "Installazione diretta..."
mkdir -p /usr/local/sbin /etc/sanoid
cp sanoid syncoid findoid sleepymutex /usr/local/sbin/ 2>/dev/null || cp sanoid syncoid /usr/local/sbin/
chmod +x /usr/local/sbin/sanoid /usr/local/sbin/syncoid
[ -f sanoid.defaults.conf ] && cp sanoid.defaults.conf /etc/sanoid/
touch /etc/sanoid/sanoid.conf
ln -sf /usr/local/sbin/sanoid /usr/sbin/sanoid 2>/dev/null || true
ln -sf /usr/local/sbin/syncoid /usr/sbin/syncoid 2>/dev/null || true

# Cleanup
cd /
rm -rf /tmp/sanoid /tmp/sanoid_*.deb 2>/dev/null || true

# Verifica finale
if command -v sanoid &>/dev/null; then
    echo "=== Sanoid installato con successo ==="
    sanoid --version 2>/dev/null || echo "Versione: manual install"
    exit 0
else
    echo "ERRORE: Installazione fallita"
    exit 1
fi
"""
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=install_script,
            port=port,
            username=username,
            key_path=key_path,
            timeout=300  # 5 minuti dovrebbero bastare
        )
        
        return result.success, result.stdout + result.stderr
    
    async def get_config(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """Legge la configurazione Sanoid corrente"""
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"cat {SANOID_CONF_PATH} 2>/dev/null || echo ''",
            port=port,
            username=username,
            key_path=key_path
        )
        
        return result.success, result.stdout
    
    async def set_config(
        self,
        hostname: str,
        config_content: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> SSHResult:
        """Scrive la configurazione Sanoid"""
        # Escape del contenuto per bash
        escaped_content = config_content.replace("'", "'\"'\"'")
        
        cmd = f"""
mkdir -p /etc/sanoid
cp {SANOID_CONF_PATH} {SANOID_CONF_PATH}.bak 2>/dev/null || true
cat > {SANOID_CONF_PATH} << 'SANOID_EOF'
{config_content}
SANOID_EOF
echo "Configuration saved"
"""
        
        return await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
    
    def generate_config(self, datasets: List[Dict]) -> str:
        """
        Genera il contenuto del file sanoid.conf
        
        datasets: lista di dict con keys:
            - name: nome dataset ZFS
            - template: nome template (o custom settings)
            - hourly, daily, weekly, monthly, yearly: retention
            - autosnap, autoprune: bool
        """
        lines = [
            "# Sanoid configuration",
            "# Managed by DAPX-backandrepl",
            "# Do not edit manually",
            "",
            "# Templates",
        ]
        
        # Aggiungi template predefiniti
        for name, tpl in DEFAULT_TEMPLATES.items():
            lines.extend([
                f"[template_{name}]",
                f"  hourly = {tpl.hourly}",
                f"  daily = {tpl.daily}",
                f"  weekly = {tpl.weekly}",
                f"  monthly = {tpl.monthly}",
                f"  yearly = {tpl.yearly}",
                f"  autosnap = {'yes' if tpl.autosnap else 'no'}",
                f"  autoprune = {'yes' if tpl.autoprune else 'no'}",
                "",
            ])
        
        lines.append("# Datasets")
        lines.append("")
        
        # Aggiungi dataset configurati
        for ds in datasets:
            if not ds.get("sanoid_enabled", False):
                continue
                
            lines.append(f"[{ds['name']}]")
            
            template = ds.get("sanoid_template", "default")
            if template and template in DEFAULT_TEMPLATES:
                lines.append(f"  use_template = {template}")
            else:
                # Configurazione custom
                lines.append(f"  hourly = {ds.get('hourly', 24)}")
                lines.append(f"  daily = {ds.get('daily', 30)}")
                lines.append(f"  weekly = {ds.get('weekly', 4)}")
                lines.append(f"  monthly = {ds.get('monthly', 12)}")
                lines.append(f"  yearly = {ds.get('yearly', 0)}")
            
            lines.append(f"  autosnap = {'yes' if ds.get('autosnap', True) else 'no'}")
            lines.append(f"  autoprune = {'yes' if ds.get('autoprune', True) else 'no'}")
            lines.append("")
        
        return "\n".join(lines)
    
    async def run_sanoid(
        self,
        hostname: str,
        cron: bool = False,
        prune: bool = False,
        verbose: bool = False,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> SSHResult:
        """Esegue Sanoid manualmente"""
        flags = []
        if cron:
            flags.append("--cron")
        if prune:
            flags.append("--prune-snapshots")
        if verbose:
            flags.append("--verbose")
        
        cmd = f"sanoid {' '.join(flags)}"
        
        return await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=600
        )
    
    async def get_sanoid_status(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """Ottiene lo stato di Sanoid"""
        
        status = {
            "installed": False,
            "version": None,
            "timer_active": False,
            "last_run": None,
            "next_run": None
        }
        
        # Check installazione e versione
        result = await ssh_service.execute(
            hostname=hostname,
            command="sanoid --version 2>&1",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success:
            status["installed"] = True
            status["version"] = result.stdout.strip()
        
        # Check timer systemd
        result = await ssh_service.execute(
            hostname=hostname,
            command="systemctl is-active sanoid.timer 2>/dev/null && systemctl show sanoid.timer --property=LastTriggerUSec,NextElapseUSecRealtime --value",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and "active" in result.stdout:
            status["timer_active"] = True
            lines = result.stdout.strip().split('\n')
            if len(lines) >= 3:
                status["last_run"] = lines[1] if lines[1] != "n/a" else None
                status["next_run"] = lines[2] if lines[2] != "n/a" else None
        
        return status


# Singleton
sanoid_service = SanoidService()
