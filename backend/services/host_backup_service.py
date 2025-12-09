"""
Host Backup Service - Backup configurazione host Proxmox PVE e PBS

Ispirato a ProxSave (https://github.com/tis24dev/proxsave)
Esegue il backup dei file di configurazione critici per il disaster recovery.
"""

import os
import tarfile
import tempfile
import logging
from datetime import datetime
from typing import List, Dict, Optional
from pathlib import Path

from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)

# Directory e file critici per PVE
PVE_BACKUP_PATHS = [
    "/etc/pve",                          # Configurazione Proxmox principale
    "/etc/network/interfaces",           # Configurazione di rete
    "/etc/network/interfaces.d",         # Configurazione di rete aggiuntiva
    "/etc/hosts",                         # Hosts file
    "/etc/hostname",                      # Hostname
    "/etc/resolv.conf",                   # DNS
    "/etc/apt/sources.list",              # Repository APT
    "/etc/apt/sources.list.d",            # Repository APT aggiuntivi
    "/etc/modprobe.d",                    # Moduli kernel
    "/etc/modules",                       # Moduli kernel
    "/etc/sysctl.conf",                   # Parametri kernel
    "/etc/sysctl.d",                      # Parametri kernel aggiuntivi
    "/root/.ssh",                         # Chiavi SSH root
    "/var/spool/cron/crontabs/root",     # Cron jobs root
    "/etc/cron.d",                        # Cron jobs di sistema
    "/etc/lvm/lvm.conf",                  # Configurazione LVM
    "/etc/vzdump.conf",                   # Configurazione vzdump
    "/etc/pve/corosync.conf",             # Configurazione cluster
    "/etc/pve/priv",                      # Chiavi private cluster
    "/etc/pve/firewall",                  # Regole firewall
    "/var/lib/pve-cluster",               # Database cluster
]

# Directory e file critici per PBS
PBS_BACKUP_PATHS = [
    "/etc/proxmox-backup",               # Configurazione PBS principale
    "/etc/network/interfaces",           # Configurazione di rete
    "/etc/network/interfaces.d",         # Configurazione di rete aggiuntiva
    "/etc/hosts",                         # Hosts file
    "/etc/hostname",                      # Hostname
    "/etc/resolv.conf",                   # DNS
    "/etc/apt/sources.list",              # Repository APT
    "/etc/apt/sources.list.d",            # Repository APT aggiuntivi
    "/root/.ssh",                         # Chiavi SSH root
    "/var/spool/cron/crontabs/root",     # Cron jobs root
    "/etc/cron.d",                        # Cron jobs di sistema
]


class HostBackupService:
    """Servizio per il backup della configurazione host Proxmox."""

    async def detect_host_type(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: Optional[str] = None
    ) -> str:
        """
        Rileva il tipo di host Proxmox (pve o pbs).
        
        Returns:
            'pve' per Proxmox VE
            'pbs' per Proxmox Backup Server
            'unknown' se non riconosciuto
        """
        # Check per PVE
        result = await ssh_service.execute(
            hostname=hostname,
            command="test -d /etc/pve && echo 'pve'",
            port=port,
            username=username,
            key_path=key_path
        )
        if result.success and result.stdout and 'pve' in result.stdout:
            return 'pve'
        
        # Check per PBS
        result = await ssh_service.execute(
            hostname=hostname,
            command="test -d /etc/proxmox-backup && echo 'pbs'",
            port=port,
            username=username,
            key_path=key_path
        )
        if result.success and result.stdout and 'pbs' in result.stdout:
            return 'pbs'
        
        return 'unknown'

    async def list_backup_paths(
        self,
        hostname: str,
        host_type: str = 'pve',
        port: int = 22,
        username: str = "root",
        key_path: Optional[str] = None
    ) -> List[Dict]:
        """
        Elenca i percorsi di backup con dimensioni e stato.
        """
        paths = PVE_BACKUP_PATHS if host_type == 'pve' else PBS_BACKUP_PATHS
        result_paths = []
        
        for path in paths:
            cmd = f"if [ -e '{path}' ]; then du -sb '{path}' 2>/dev/null | cut -f1; else echo 'NOT_FOUND'; fi"
            result = await ssh_service.execute(
                hostname=hostname,
                command=cmd,
                port=port,
                username=username,
                key_path=key_path
            )
            
            size = 0
            exists = False
            if result.success and result.stdout:
                output = result.stdout.strip()
                if output != 'NOT_FOUND':
                    try:
                        size = int(output)
                        exists = True
                    except ValueError:
                        pass
            
            result_paths.append({
                "path": path,
                "exists": exists,
                "size": size,
                "size_human": self._format_size(size)
            })
        
        return result_paths

    async def create_host_backup(
        self,
        hostname: str,
        host_type: str = 'pve',
        port: int = 22,
        username: str = "root",
        key_path: Optional[str] = None,
        dest_path: str = "/var/backups/proxmox-config",
        compress: bool = True,
        encrypt: bool = False,
        encrypt_password: Optional[str] = None
    ) -> Dict:
        """
        Crea un backup della configurazione host.
        
        Args:
            hostname: Host da backuppare
            host_type: 'pve' o 'pbs'
            dest_path: Percorso di destinazione sul host
            compress: Comprime con gzip
            encrypt: Cripta con openssl (richiede encrypt_password)
            encrypt_password: Password per cifratura
            
        Returns:
            Dict con risultato operazione
        """
        paths = PVE_BACKUP_PATHS if host_type == 'pve' else PBS_BACKUP_PATHS
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_name = f"proxmox-{host_type}-config-{timestamp}"
        
        # Crea directory destinazione
        await ssh_service.execute(
            hostname=hostname,
            command=f"mkdir -p {dest_path}",
            port=port,
            username=username,
            key_path=key_path
        )
        
        # Costruisci lista file esistenti
        existing_paths = []
        for path in paths:
            check_result = await ssh_service.execute(
                hostname=hostname,
                command=f"test -e '{path}' && echo 'exists'",
                port=port,
                username=username,
                key_path=key_path
            )
            if check_result.success and check_result.stdout and 'exists' in check_result.stdout:
                existing_paths.append(path)
        
        if not existing_paths:
            return {
                "success": False,
                "error": "Nessun file di configurazione trovato da backuppare"
            }
        
        # Crea il tar
        paths_str = " ".join(f"'{p}'" for p in existing_paths)
        
        if compress and encrypt and encrypt_password:
            # Tar + gzip + openssl
            backup_file = f"{dest_path}/{backup_name}.tar.gz.enc"
            cmd = f"tar czf - {paths_str} 2>/dev/null | openssl enc -aes-256-cbc -salt -pbkdf2 -pass pass:'{encrypt_password}' -out '{backup_file}'"
        elif compress:
            # Solo tar + gzip
            backup_file = f"{dest_path}/{backup_name}.tar.gz"
            cmd = f"tar czf '{backup_file}' {paths_str} 2>/dev/null"
        else:
            # Solo tar
            backup_file = f"{dest_path}/{backup_name}.tar"
            cmd = f"tar cf '{backup_file}' {paths_str} 2>/dev/null"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if not result.success:
            return {
                "success": False,
                "error": f"Errore creazione backup: {result.stderr or result.stdout}"
            }
        
        # Verifica dimensione file creato
        size_result = await ssh_service.execute(
            hostname=hostname,
            command=f"stat -c %s '{backup_file}' 2>/dev/null || echo '0'",
            port=port,
            username=username,
            key_path=key_path
        )
        
        size = 0
        if size_result.success and size_result.stdout:
            try:
                size = int(size_result.stdout.strip())
            except ValueError:
                pass
        
        return {
            "success": True,
            "backup_file": backup_file,
            "backup_name": backup_name,
            "size": size,
            "size_human": self._format_size(size),
            "paths_backed_up": len(existing_paths),
            "encrypted": encrypt and encrypt_password is not None,
            "compressed": compress,
            "timestamp": timestamp
        }

    async def list_host_backups(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: Optional[str] = None,
        backup_path: str = "/var/backups/proxmox-config"
    ) -> List[Dict]:
        """
        Elenca i backup esistenti sull'host.
        """
        cmd = f"ls -la {backup_path}/proxmox-*.tar* 2>/dev/null | awk '{{print $5, $6, $7, $8, $9}}'"
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path
        )
        
        backups = []
        if result.success and result.stdout:
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split()
                    if len(parts) >= 5:
                        try:
                            size = int(parts[0])
                            filename = parts[-1]
                            date_str = " ".join(parts[1:-1])
                            
                            backups.append({
                                "filename": os.path.basename(filename),
                                "path": filename,
                                "size": size,
                                "size_human": self._format_size(size),
                                "date": date_str,
                                "encrypted": filename.endswith('.enc')
                            })
                        except (ValueError, IndexError):
                            pass
        
        return sorted(backups, key=lambda x: x.get('filename', ''), reverse=True)

    async def delete_host_backup(
        self,
        hostname: str,
        backup_path: str,
        port: int = 22,
        username: str = "root",
        key_path: Optional[str] = None
    ) -> Dict:
        """
        Elimina un backup esistente.
        """
        # Verifica che il path sia valido
        if not backup_path.startswith('/var/backups/') or '..' in backup_path:
            return {"success": False, "error": "Percorso non valido"}
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"rm -f '{backup_path}'",
            port=port,
            username=username,
            key_path=key_path
        )
        
        return {
            "success": result.success,
            "error": result.stderr if not result.success else None
        }

    async def apply_retention(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: Optional[str] = None,
        backup_path: str = "/var/backups/proxmox-config",
        keep_last: int = 7
    ) -> Dict:
        """
        Applica retention policy eliminando backup vecchi.
        """
        backups = await self.list_host_backups(
            hostname=hostname,
            port=port,
            username=username,
            key_path=key_path,
            backup_path=backup_path
        )
        
        deleted = []
        kept = []
        
        for i, backup in enumerate(backups):
            if i < keep_last:
                kept.append(backup['filename'])
            else:
                result = await self.delete_host_backup(
                    hostname=hostname,
                    backup_path=backup['path'],
                    port=port,
                    username=username,
                    key_path=key_path
                )
                if result['success']:
                    deleted.append(backup['filename'])
        
        return {
            "success": True,
            "kept": kept,
            "deleted": deleted,
            "kept_count": len(kept),
            "deleted_count": len(deleted)
        }

    def _format_size(self, size: int) -> str:
        """Formatta dimensione in formato leggibile."""
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if size < 1024:
                return f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} PB"


# Singleton
host_backup_service = HostBackupService()




