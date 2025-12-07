"""
BTRFS Service - Gestione replica VM Proxmox con BTRFS send/receive
Integrato nel progetto DAPX-backandrepl per supportare storage BTRFS oltre a ZFS.

Questo servizio implementa la sincronizzazione di VM Proxmox tra nodi
usando snapshot BTRFS e btrfs send/receive per trasferimenti incrementali.
"""

import asyncio
from datetime import datetime
from typing import Optional, Dict, List, Tuple
import logging
import re
import os

from services.ssh_service import ssh_service, SSHResult

logger = logging.getLogger(__name__)


class BTRFSConfig:
    """Configurazione per BTRFS sync"""
    
    def __init__(
        self,
        btrfs_mount: str = "/mnt/btrfs-storage",
        snapshot_dir: Optional[str] = None,
        max_snapshots: int = 5,
        log_file: str = "/var/log/proxmox-btrfs-sync.log"
    ):
        self.btrfs_mount = btrfs_mount
        self.snapshot_dir = snapshot_dir or f"{btrfs_mount}/.snapshots"
        self.max_snapshots = max_snapshots
        self.log_file = log_file


class BTRFSService:
    """Servizio per replica VM Proxmox con BTRFS"""
    
    def __init__(self, config: Optional[BTRFSConfig] = None):
        self.config = config or BTRFSConfig()
    
    async def check_btrfs_available(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """Verifica se BTRFS è disponibile sul nodo"""
        
        result = await ssh_service.execute(
            hostname=hostname,
            command="which btrfs && btrfs --version",
            port=port,
            username=username,
            key_path=key_path,
            timeout=30
        )
        
        if result.success:
            return True, result.stdout.strip()
        return False, result.stderr
    
    async def check_btrfs_mount(
        self,
        hostname: str,
        mount_point: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, Dict]:
        """Verifica se un mount point BTRFS esiste ed è accessibile"""
        
        cmd = f"""
        if [ -d "{mount_point}" ]; then
            FS_TYPE=$(df -T "{mount_point}" 2>/dev/null | tail -1 | awk '{{print $2}}')
            if [ "$FS_TYPE" = "btrfs" ]; then
                USAGE=$(btrfs filesystem df "{mount_point}" 2>/dev/null | head -1)
                echo "OK|$FS_TYPE|$USAGE"
            else
                echo "NOT_BTRFS|$FS_TYPE|"
            fi
        else
            echo "NOT_EXISTS||"
        fi
        """
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=30
        )
        
        if result.success:
            parts = result.stdout.strip().split('|')
            status = parts[0] if parts else "ERROR"
            
            if status == "OK":
                return True, {
                    "exists": True,
                    "is_btrfs": True,
                    "fs_type": parts[1] if len(parts) > 1 else "btrfs",
                    "usage": parts[2] if len(parts) > 2 else ""
                }
            elif status == "NOT_BTRFS":
                return False, {
                    "exists": True,
                    "is_btrfs": False,
                    "fs_type": parts[1] if len(parts) > 1 else "unknown",
                    "error": f"Il mount point non è BTRFS (tipo: {parts[1]})"
                }
            else:
                return False, {
                    "exists": False,
                    "is_btrfs": False,
                    "error": f"Mount point {mount_point} non esiste"
                }
        
        return False, {"error": result.stderr}
    
    async def list_btrfs_subvolumes(
        self,
        hostname: str,
        path: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """Lista i subvolume BTRFS in un path"""
        
        cmd = f"btrfs subvolume list -o {path} 2>/dev/null"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=60
        )
        
        subvolumes = []
        if result.success:
            for line in result.stdout.strip().split('\n'):
                if line:
                    parts = line.split()
                    if len(parts) >= 9:
                        subvolumes.append({
                            "id": parts[1],
                            "gen": parts[3],
                            "top_level": parts[6],
                            "path": parts[8]
                        })
        
        return subvolumes
    
    async def get_vm_btrfs_disks(
        self,
        hostname: str,
        vmid: int,
        btrfs_mount: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """
        Ottiene i dischi BTRFS di una VM Proxmox.
        Simile a get_vm_disks_with_size ma per storage BTRFS.
        """
        
        config_cmd = f"qm config {vmid} 2>/dev/null"
        result = await ssh_service.execute(
            hostname=hostname,
            command=config_cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=30
        )
        
        if not result.success:
            logger.warning(f"VM {vmid} non trovata o non accessibile")
            return []
        
        config = result.stdout
        disks = []
        
        # Pattern per dischi: scsi0: storage:volume,size=32G o file=/path/to/disk
        disk_pattern = r'((?:scsi|sata|virtio|ide)\d+):\s*(.+)'
        
        for match in re.finditer(disk_pattern, config):
            disk_name = match.group(1)
            disk_spec = match.group(2)
            
            disk_path = None
            
            # Cerca il path del disco
            if f"file={btrfs_mount}" in disk_spec:
                file_match = re.search(r'file=([^,]+)', disk_spec)
                if file_match:
                    disk_path = file_match.group(1)
            elif disk_spec.startswith(btrfs_mount):
                disk_path = disk_spec.split(',')[0]
            
            if disk_path:
                # Verifica se è un subvolume BTRFS
                check_cmd = f"btrfs subvolume show '{disk_path}' 2>/dev/null"
                check_result = await ssh_service.execute(
                    hostname=hostname,
                    command=check_cmd,
                    port=port,
                    username=username,
                    key_path=key_path,
                    timeout=30
                )
                
                is_subvolume = check_result.success
                
                # Ottieni dimensione
                size_cmd = f"du -sh '{disk_path}' 2>/dev/null | cut -f1"
                size_result = await ssh_service.execute(
                    hostname=hostname,
                    command=size_cmd,
                    port=port,
                    username=username,
                    key_path=key_path,
                    timeout=30
                )
                
                disks.append({
                    "disk_name": disk_name,
                    "path": disk_path,
                    "is_subvolume": is_subvolume,
                    "size": size_result.stdout.strip() if size_result.success else "N/A"
                })
        
        return disks
    
    async def create_snapshot(
        self,
        hostname: str,
        source_path: str,
        snapshot_path: str,
        readonly: bool = True,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> SSHResult:
        """Crea uno snapshot BTRFS"""
        
        flags = "-r" if readonly else ""
        cmd = f"""
        mkdir -p "$(dirname '{snapshot_path}')"
        btrfs subvolume snapshot {flags} '{source_path}' '{snapshot_path}'
        """
        
        return await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=120
        )
    
    async def delete_snapshot(
        self,
        hostname: str,
        snapshot_path: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> SSHResult:
        """Elimina uno snapshot/subvolume BTRFS"""
        
        cmd = f"btrfs subvolume delete '{snapshot_path}'"
        
        return await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=120
        )
    
    async def convert_to_subvolume(
        self,
        hostname: str,
        file_path: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Converte un file/directory in un subvolume BTRFS.
        Necessario per usare btrfs send/receive.
        """
        
        check_cmd = f"btrfs subvolume show '{file_path}' 2>/dev/null"
        check_result = await ssh_service.execute(
            hostname=hostname,
            command=check_cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=30
        )
        
        if check_result.success:
            return True, "Già un subvolume BTRFS"
        
        convert_cmd = f"""
        TEMP_DIR=$(mktemp -d)
        mv '{file_path}' "$TEMP_DIR/"
        btrfs subvolume create '{file_path}'
        BASENAME=$(basename '{file_path}')
        mv "$TEMP_DIR/$BASENAME"/* '{file_path}/' 2>/dev/null || mv "$TEMP_DIR/$BASENAME" '{file_path}/disk.img'
        rmdir "$TEMP_DIR" 2>/dev/null || rm -rf "$TEMP_DIR"
        echo "Converted to subvolume"
        """
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=convert_cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=300
        )
        
        if result.success:
            return True, "Convertito in subvolume BTRFS"
        return False, result.stderr
    
    async def list_snapshots(
        self,
        hostname: str,
        snapshot_dir: str,
        vmid: int,
        disk_name: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[str]:
        """Lista gli snapshot esistenti per un disco di una VM"""
        
        pattern = f"{vmid}_{disk_name}_*"
        cmd = f"find '{snapshot_dir}' -maxdepth 1 -name '{pattern}' -type d | sort -r"
        
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=60
        )
        
        if result.success:
            return [s.strip() for s in result.stdout.strip().split('\n') if s.strip()]
        return []
    
    def build_btrfs_sync_command(
        self,
        snapshot_path: str,
        parent_snapshot: Optional[str],
        dest_host: str,
        dest_snapshot_dir: str,
        dest_user: str = "root",
        dest_port: int = 22,
        dest_key: str = "/root/.ssh/id_rsa"
    ) -> str:
        """
        Costruisce il comando btrfs send/receive.
        Analogo a build_syncoid_command per ZFS.
        """
        
        if parent_snapshot:
            # Sync incrementale
            send_cmd = f"btrfs send -p '{parent_snapshot}' '{snapshot_path}'"
        else:
            # Sync completo
            send_cmd = f"btrfs send '{snapshot_path}'"
        
        receive_cmd = f"mkdir -p '{dest_snapshot_dir}' && btrfs receive '{dest_snapshot_dir}'"
        ssh_cmd = f"ssh -p {dest_port} -i {dest_key} -o StrictHostKeyChecking=no {dest_user}@{dest_host}"
        
        return f"{send_cmd} | {ssh_cmd} \"{receive_cmd}\""
    
    async def run_sync(
        self,
        executor_host: str,
        disk_path: str,
        vmid: int,
        disk_name: str,
        snapshot_dir: str,
        dest_host: str,
        dest_snapshot_dir: str,
        full_sync: bool = False,
        executor_port: int = 22,
        executor_user: str = "root",
        executor_key: str = "/root/.ssh/id_rsa",
        dest_port: int = 22,
        dest_user: str = "root",
        dest_key: str = "/root/.ssh/id_rsa",
        max_snapshots: int = 5,
        timeout: int = 3600
    ) -> Dict:
        """
        Esegue una sincronizzazione BTRFS.
        Analogo a syncoid_service.run_sync per ZFS.
        
        Returns dict con:
            - success: bool
            - output: str
            - error: str
            - duration: int (secondi)
            - transferred: str
            - sync_type: str (full/incremental)
        """
        
        start_time = datetime.utcnow()
        
        try:
            # 1. Verifica che il disco sia un subvolume
            is_subvol_cmd = f"btrfs subvolume show '{disk_path}' 2>/dev/null"
            is_subvol = await ssh_service.execute(
                hostname=executor_host,
                command=is_subvol_cmd,
                port=executor_port,
                username=executor_user,
                key_path=executor_key,
                timeout=30
            )
            
            if not is_subvol.success:
                success, msg = await self.convert_to_subvolume(
                    hostname=executor_host,
                    file_path=disk_path,
                    port=executor_port,
                    username=executor_user,
                    key_path=executor_key
                )
                if not success:
                    return {
                        "success": False,
                        "output": "",
                        "error": f"Impossibile convertire {disk_path} in subvolume: {msg}",
                        "duration": 0,
                        "transferred": None,
                        "sync_type": None
                    }
            
            # 2. Crea snapshot readonly
            timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
            basename = os.path.basename(disk_path)
            snapshot_name = f"{vmid}_{basename}_{timestamp}"
            snapshot_path = f"{snapshot_dir}/{snapshot_name}"
            
            # Crea directory snapshot
            await ssh_service.execute(
                hostname=executor_host,
                command=f"mkdir -p '{snapshot_dir}'",
                port=executor_port,
                username=executor_user,
                key_path=executor_key,
                timeout=30
            )
            
            # Crea snapshot
            snap_result = await self.create_snapshot(
                hostname=executor_host,
                source_path=disk_path,
                snapshot_path=snapshot_path,
                readonly=True,
                port=executor_port,
                username=executor_user,
                key_path=executor_key
            )
            
            if not snap_result.success:
                return {
                    "success": False,
                    "output": snap_result.stdout,
                    "error": f"Errore creazione snapshot: {snap_result.stderr}",
                    "duration": 0,
                    "transferred": None,
                    "sync_type": None
                }
            
            logger.info(f"Snapshot creato: {snapshot_name}")
            
            # 3. Trova l'ultimo snapshot per sync incrementale
            last_snapshot = None
            sync_type = "full"
            
            if not full_sync:
                existing_snaps = await self.list_snapshots(
                    hostname=executor_host,
                    snapshot_dir=snapshot_dir,
                    vmid=vmid,
                    disk_name=basename,
                    port=executor_port,
                    username=executor_user,
                    key_path=executor_key
                )
                
                if len(existing_snaps) > 1:
                    for snap in existing_snaps:
                        if snap != snapshot_path:
                            last_snapshot = snap
                            sync_type = "incremental"
                            break
            
            # 4. Costruisci ed esegui comando sync
            sync_cmd = self.build_btrfs_sync_command(
                snapshot_path=snapshot_path,
                parent_snapshot=last_snapshot,
                dest_host=dest_host,
                dest_snapshot_dir=dest_snapshot_dir,
                dest_user=dest_user,
                dest_port=dest_port,
                dest_key=dest_key
            )
            
            logger.info(f"Esecuzione BTRFS sync ({sync_type}): {disk_name}")
            
            sync_result = await ssh_service.execute(
                hostname=executor_host,
                command=sync_cmd,
                port=executor_port,
                username=executor_user,
                key_path=executor_key,
                timeout=timeout
            )
            
            end_time = datetime.utcnow()
            duration = int((end_time - start_time).total_seconds())
            
            if not sync_result.success:
                return {
                    "success": False,
                    "output": sync_result.stdout,
                    "error": f"Errore sincronizzazione: {sync_result.stderr}",
                    "duration": duration,
                    "transferred": None,
                    "sync_type": sync_type,
                    "command": sync_cmd
                }
            
            # 5. Pulizia vecchi snapshot
            await self._cleanup_old_snapshots(
                hostname=executor_host,
                snapshot_dir=snapshot_dir,
                vmid=vmid,
                disk_name=basename,
                max_snapshots=max_snapshots,
                port=executor_port,
                username=executor_user,
                key_path=executor_key
            )
            
            await self._cleanup_old_snapshots(
                hostname=dest_host,
                snapshot_dir=dest_snapshot_dir,
                vmid=vmid,
                disk_name=basename,
                max_snapshots=max_snapshots,
                port=dest_port,
                username=dest_user,
                key_path=dest_key
            )
            
            transferred = self._parse_transferred(sync_result.stdout + sync_result.stderr)
            
            return {
                "success": True,
                "output": sync_result.stdout,
                "error": "",
                "duration": duration,
                "transferred": transferred,
                "sync_type": sync_type,
                "snapshot_name": snapshot_name,
                "command": sync_cmd
            }
            
        except Exception as e:
            end_time = datetime.utcnow()
            duration = int((end_time - start_time).total_seconds())
            logger.error(f"Errore sync disk BTRFS: {e}")
            return {
                "success": False,
                "output": "",
                "error": str(e),
                "duration": duration,
                "transferred": None,
                "sync_type": None
            }
    
    async def _cleanup_old_snapshots(
        self,
        hostname: str,
        snapshot_dir: str,
        vmid: int,
        disk_name: str,
        max_snapshots: int,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ):
        """Rimuove gli snapshot più vecchi del limite configurato"""
        
        snapshots = await self.list_snapshots(
            hostname=hostname,
            snapshot_dir=snapshot_dir,
            vmid=vmid,
            disk_name=disk_name,
            port=port,
            username=username,
            key_path=key_path
        )
        
        if len(snapshots) > max_snapshots:
            old_snapshots = snapshots[max_snapshots:]
            for snap in old_snapshots:
                logger.info(f"Rimozione vecchio snapshot: {snap}")
                await self.delete_snapshot(
                    hostname=hostname,
                    snapshot_path=snap,
                    port=port,
                    username=username,
                    key_path=key_path
                )
    
    def _parse_transferred(self, output: str) -> Optional[str]:
        """Estrae la quantità di dati trasferiti dall'output"""
        
        patterns = [
            r"(\d+(?:\.\d+)?[KMGT]i?B?)\s+(?:sent|transferred)",
            r"total size:\s*(\d+(?:\.\d+)?[KMGT]i?B?)",
            r"(\d+(?:\.\d+)?[KMGT]i?B?)\s+total",
        ]
        
        for pattern in patterns:
            match = re.search(pattern, output, re.IGNORECASE)
            if match:
                return match.group(1)
        
        return None
    
    async def get_vm_name(
        self,
        hostname: str,
        vmid: int,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> str:
        """Ottiene il nome della VM"""
        
        cmd = f"qm config {vmid} 2>/dev/null | grep '^name:' | cut -d' ' -f2"
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=30
        )
        
        if result.success and result.stdout.strip():
            return result.stdout.strip()
        return f"vm-{vmid}"


# Singleton
btrfs_service = BTRFSService()


