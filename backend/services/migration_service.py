"""
Migration Service - Gestione migrazione/copia VM tra nodi Proxmox
Usa funzionalità native di Proxmox (qm copy / pct copy)
"""

import asyncio
from typing import Optional, Dict, Tuple, List
import logging
import re
import json

from services.ssh_service import ssh_service, SSHResult

logger = logging.getLogger(__name__)


class MigrationService:
    """Servizio per migrazione/copia VM tra nodi Proxmox"""
    
    async def migrate_vm(
        self,
        source_hostname: str,
        dest_hostname: str,
        vm_id: int,
        vm_type: str = "qemu",
        dest_vm_id: Optional[int] = None,
        dest_vm_name_suffix: Optional[str] = None,
        migration_type: str = "copy",  # copy, move
        create_snapshot: bool = True,
        keep_snapshots: int = 1,
        start_after: bool = False,
        hw_config: Optional[Dict] = None,
        source_port: int = 22,
        source_user: str = "root",
        source_key: str = "/root/.ssh/id_rsa",
        dest_port: int = 22,
        dest_user: str = "root",
        dest_key: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """
        Migra/copia una VM tra nodi Proxmox usando funzionalità native.
        
        Args:
            source_hostname: Hostname nodo sorgente
            dest_hostname: Hostname nodo destinazione
            vm_id: VMID sorgente
            vm_type: qemu o lxc
            dest_vm_id: VMID destinazione (None = stesso del sorgente)
            dest_vm_name_suffix: Suffisso per nome VM
            migration_type: "copy" (copia) o "move" (sposta)
            create_snapshot: Crea snapshot prima della migrazione
            keep_snapshots: Numero snapshot da mantenere
            start_after: Avvia VM dopo migrazione
            hw_config: Dict con riconfigurazione hardware (es: {"memory": 4096, "cores": 2, "network": {...}, "storage": {...}})
        
        Returns:
            Dict con success, message, vm_id, duration, transferred
        """
        import time
        start_time = time.time()
        
        cmd = "qm" if vm_type == "qemu" else "pct"
        
        # Determina VMID destinazione
        target_vmid = dest_vm_id if dest_vm_id else vm_id
        
        # Verifica che la VM esista sulla sorgente
        check_cmd = f"{cmd} status {vm_id} 2>/dev/null"
        check_result = await ssh_service.execute(
            hostname=source_hostname,
            command=check_cmd,
            port=source_port,
            username=source_user,
            key_path=source_key,
            timeout=30
        )
        
        if not check_result.success:
            return {
                "success": False,
                "message": f"VM {vm_id} non trovata su {source_hostname}",
                "error": check_result.stderr
            }
        
        # Crea snapshot se richiesto
        snapshot_name = None
        if create_snapshot:
            snapshot_name = f"migration-{int(time.time())}"
            snap_cmd = f"{cmd} snapshot {vm_id} {snapshot_name} --description 'Pre-migration snapshot'"
            snap_result = await ssh_service.execute(
                hostname=source_hostname,
                command=snap_cmd,
                port=source_port,
                username=source_user,
                key_path=source_key,
                timeout=300
            )
            
            if not snap_result.success:
                logger.warning(f"Errore creazione snapshot: {snap_result.stderr}")
                # Continua comunque la migrazione
        
        # Costruisci comando di copia/migrazione
        # qm copy <vmid> <target> [OPTIONS]
        # pct copy <vmid> <target> [OPTIONS]
        
        copy_options = []
        
        # Target: user@hostname
        target = f"{dest_user}@{dest_hostname}"
        if dest_port != 22:
            target = f"{dest_user}@{dest_hostname}:{dest_port}"
        
        # VMID destinazione
        if dest_vm_id and dest_vm_id != vm_id:
            copy_options.append(f"--newid {dest_vm_id}")
        
        # Nome VM (se suffisso specificato, verrà modificato dopo)
        if dest_vm_name_suffix:
            # Non possiamo cambiare il nome durante la copia, lo faremo dopo
            pass
        
        # Storage mapping (se specificato in hw_config)
        storage_map = {}
        if hw_config and "storage" in hw_config:
            storage_map = hw_config["storage"]
            # qm copy supporta --storage per mappare storage
            for disk, new_storage in storage_map.items():
                # Estrai nome storage (es: "local-lvm:vm-100-disk-0" -> "local-lvm")
                if ":" in new_storage:
                    storage_name = new_storage.split(":")[0]
                    copy_options.append(f"--storage {storage_name}")
                    break  # qm copy supporta solo un --storage, useremo modifica post-copia
        
        # Costruisci comando completo
        copy_cmd = f"{cmd} copy {vm_id} {target} {' '.join(copy_options)}"
        
        logger.info(f"Eseguendo: {copy_cmd}")
        
        # Esegui copia
        copy_result = await ssh_service.execute(
            hostname=source_hostname,
            command=copy_cmd,
            port=source_port,
            username=source_user,
            key_path=source_key,
            timeout=3600  # 1 ora per migrazioni grandi
        )
        
        if not copy_result.success:
            return {
                "success": False,
                "message": f"Errore durante copia VM: {copy_result.stderr}",
                "error": copy_result.stderr,
                "stdout": copy_result.stdout
            }
        
        # Estrai dimensione trasferita dall'output
        transferred = "0B"
        if "transferred" in copy_result.stdout.lower() or "MiB" in copy_result.stdout:
            # Cerca pattern tipo "transferred 10.5 GiB"
            match = re.search(r'(\d+\.?\d*)\s*(GiB|MiB|KiB|GB|MB|KB)', copy_result.stdout, re.IGNORECASE)
            if match:
                transferred = f"{match.group(1)} {match.group(2)}"
        
        # Applica riconfigurazione hardware se specificata
        if hw_config:
            hw_result = await self._apply_hw_config(
                hostname=dest_hostname,
                vm_id=target_vmid,
                vm_type=vm_type,
                hw_config=hw_config,
                dest_vm_name_suffix=dest_vm_name_suffix,
                port=dest_port,
                username=dest_user,
                key_path=dest_key
            )
            
            if not hw_result["success"]:
                logger.warning(f"Errore applicazione config hardware: {hw_result.get('message')}")
                # Non fallisce la migrazione, solo warning
        
        # Gestione snapshot
        if snapshot_name and keep_snapshots > 0:
            # Mantieni solo gli ultimi N snapshot
            await self._prune_snapshots(
                hostname=source_hostname,
                vm_id=vm_id,
                vm_type=vm_type,
                keep=keep_snapshots,
                port=source_port,
                username=source_user,
                key_path=source_key
            )
        
        # Avvia VM se richiesto
        if start_after:
            start_cmd = f"{cmd} start {target_vmid}"
            start_result = await ssh_service.execute(
                hostname=dest_hostname,
                command=start_cmd,
                port=dest_port,
                username=dest_user,
                key_path=dest_key,
                timeout=60
            )
            
            if not start_result.success:
                logger.warning(f"Errore avvio VM: {start_result.stderr}")
        
        duration = int(time.time() - start_time)
        
        return {
            "success": True,
            "message": f"VM {vm_id} migrata con successo su {dest_hostname} (VMID: {target_vmid})",
            "vm_id": target_vmid,
            "duration": duration,
            "transferred": transferred,
            "snapshot_created": snapshot_name if create_snapshot else None
        }
    
    async def _apply_hw_config(
        self,
        hostname: str,
        vm_id: int,
        vm_type: str,
        hw_config: Dict,
        dest_vm_name_suffix: Optional[str] = None,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """Applica riconfigurazione hardware alla VM"""
        cmd = "qm" if vm_type == "qemu" else "pct"
        changes = []
        
        # Modifica nome VM
        if dest_vm_name_suffix:
            # Leggi nome attuale
            config_result = await ssh_service.execute(
                hostname=hostname,
                command=f"{cmd} config {vm_id} | grep '^name:'",
                port=port,
                username=username,
                key_path=key_path,
                timeout=30
            )
            
            if config_result.success and config_result.stdout.strip():
                current_name = config_result.stdout.strip().split(":", 1)[1].strip()
                new_name = current_name + dest_vm_name_suffix
                set_name_cmd = f"{cmd} set {vm_id} --name '{new_name}'"
                name_result = await ssh_service.execute(
                    hostname=hostname,
                    command=set_name_cmd,
                    port=port,
                    username=username,
                    key_path=key_path,
                    timeout=30
                )
                if name_result.success:
                    changes.append(f"nome: {new_name}")
        
        # Modifica RAM
        if "memory" in hw_config:
            mem = hw_config["memory"]
            mem_cmd = f"{cmd} set {vm_id} --memory {mem}"
            mem_result = await ssh_service.execute(
                hostname=hostname,
                command=mem_cmd,
                port=port,
                username=username,
                key_path=key_path,
                timeout=30
            )
            if mem_result.success:
                changes.append(f"RAM: {mem}MB")
        
        # Modifica CPU cores
        if "cores" in hw_config:
            cores = hw_config["cores"]
            cores_cmd = f"{cmd} set {vm_id} --cores {cores}"
            cores_result = await ssh_service.execute(
                hostname=hostname,
                command=cores_cmd,
                port=port,
                username=username,
                key_path=key_path,
                timeout=30
            )
            if cores_result.success:
                changes.append(f"cores: {cores}")
        
        # Modifica CPU sockets
        if "sockets" in hw_config:
            sockets = hw_config["sockets"]
            sockets_cmd = f"{cmd} set {vm_id} --sockets {sockets}"
            sockets_result = await ssh_service.execute(
                hostname=hostname,
                command=sockets_cmd,
                port=port,
                username=username,
                key_path=key_path,
                timeout=30
            )
            if sockets_result.success:
                changes.append(f"sockets: {sockets}")
        
        # Modifica CPU type
        if "cpu" in hw_config:
            cpu_type = hw_config["cpu"]
            cpu_cmd = f"{cmd} set {vm_id} --cpu {cpu_type}"
            cpu_result = await ssh_service.execute(
                hostname=hostname,
                command=cpu_cmd,
                port=port,
                username=username,
                key_path=key_path,
                timeout=30
            )
            if cpu_result.success:
                changes.append(f"CPU: {cpu_type}")
        
        # Modifica network (bridge)
        if "network" in hw_config:
            for net_iface, net_config in hw_config["network"].items():
                # net_config può essere stringa tipo "bridge=vmbr1" o dict
                if isinstance(net_config, str):
                    # Estrai bridge
                    bridge_match = re.search(r'bridge=([^,\s]+)', net_config)
                    if bridge_match:
                        bridge = bridge_match.group(1)
                        net_cmd = f"{cmd} set {vm_id} --{net_iface} bridge={bridge}"
                    else:
                        net_cmd = f"{cmd} set {vm_id} --{net_iface} {net_config}"
                else:
                    # Dict con più opzioni
                    net_str = ",".join([f"{k}={v}" for k, v in net_config.items()])
                    net_cmd = f"{cmd} set {vm_id} --{net_iface} {net_str}"
                
                net_result = await ssh_service.execute(
                    hostname=hostname,
                    command=net_cmd,
                    port=port,
                    username=username,
                    key_path=key_path,
                    timeout=30
                )
                if net_result.success:
                    changes.append(f"{net_iface}: {net_config}")
        
        # Modifica storage (sposta dischi)
        if "storage" in hw_config:
            for disk, new_storage in hw_config["storage"].items():
                # new_storage può essere "local-lvm:vm-100-disk-0" o solo "local-lvm"
                if ":" in new_storage:
                    storage_name, volume = new_storage.split(":", 1)
                else:
                    storage_name = new_storage
                    # Leggi volume attuale
                    config_result = await ssh_service.execute(
                        hostname=hostname,
                        command=f"{cmd} config {vm_id} | grep '^{disk}:'",
                        port=port,
                        username=username,
                        key_path=key_path,
                        timeout=30
                    )
                    if config_result.success and config_result.stdout.strip():
                        # Estrai volume attuale
                        current = config_result.stdout.strip().split(":", 1)[1].strip().split(",")[0]
                        volume = current.split("/")[-1] if "/" in current else current
                    else:
                        continue
                
                # Sposta disco
                move_cmd = f"{cmd} disk move {vm_id} {disk} --storage {storage_name}"
                move_result = await ssh_service.execute(
                    hostname=hostname,
                    command=move_cmd,
                    port=port,
                    username=username,
                    key_path=key_path,
                    timeout=600  # 10 minuti per spostamento disco
                )
                if move_result.success:
                    changes.append(f"{disk} -> {storage_name}")
        
        return {
            "success": True,
            "message": f"Config hardware applicata: {', '.join(changes)}",
            "changes": changes
        }
    
    async def _prune_snapshots(
        self,
        hostname: str,
        vm_id: int,
        vm_type: str,
        keep: int,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ):
        """Mantiene solo gli ultimi N snapshot, elimina i più vecchi"""
        cmd = "qm" if vm_type == "qemu" else "pct"
        
        # Lista snapshot
        list_cmd = f"{cmd} listsnapshot {vm_id} 2>/dev/null | grep -E '^\\s+[0-9]' | tail -n +2"
        list_result = await ssh_service.execute(
            hostname=hostname,
            command=list_cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=30
        )
        
        if not list_result.success:
            return
        
        # Estrai nomi snapshot (escludi current)
        snapshots = []
        for line in list_result.stdout.strip().split('\n'):
            if line.strip() and 'current' not in line.lower():
                # Estrai nome snapshot (prima colonna dopo spazi)
                parts = line.strip().split()
                if parts:
                    snap_name = parts[0]
                    snapshots.append(snap_name)
        
        # Ordina per data (assumendo formato snapshot-YYYYMMDD-HHMMSS o simile)
        snapshots.sort(reverse=True)
        
        # Elimina quelli oltre keep
        to_delete = snapshots[keep:]
        for snap_name in to_delete:
            del_cmd = f"{cmd} delsnapshot {vm_id} {snap_name}"
            await ssh_service.execute(
                hostname=hostname,
                command=del_cmd,
                port=port,
                username=username,
                key_path=key_path,
                timeout=300
            )


migration_service = MigrationService()

