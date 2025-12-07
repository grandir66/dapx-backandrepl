"""
PBS Service - Gestione Proxmox Backup Server
Permette backup e restore di VM attraverso PBS per replica di filesystem non supportati
"""

import asyncio
from typing import Optional, Dict, List, Tuple
import logging
import json
import re
from datetime import datetime

from services.ssh_service import ssh_service, SSHResult

logger = logging.getLogger(__name__)


class PBSService:
    """Servizio per integrazione con Proxmox Backup Server"""
    
    async def check_pbs_available(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifica se proxmox-backup-client è installato sul nodo
        Ritorna (disponibile, versione)
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="proxmox-backup-client version 2>/dev/null || echo 'NOT_INSTALLED'",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and "NOT_INSTALLED" not in result.stdout:
            # Parse version from output like "proxmox-backup-client 3.1.2-1"
            version_match = re.search(r'(\d+\.\d+\.\d+)', result.stdout)
            version = version_match.group(1) if version_match else "unknown"
            return True, version
        
        return False, None
    
    async def check_pbs_server(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, Optional[str]]:
        """
        Verifica se il nodo è un PBS server (proxmox-backup-server installato)
        Ritorna (is_pbs_server, versione)
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="proxmox-backup-manager version 2>/dev/null || echo 'NOT_PBS'",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and "NOT_PBS" not in result.stdout:
            version_match = re.search(r'(\d+\.\d+\.\d+)', result.stdout)
            version = version_match.group(1) if version_match else "unknown"
            return True, version
        
        return False, None
    
    async def list_datastores(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """
        Lista i datastore disponibili su un PBS server
        """
        result = await ssh_service.execute(
            hostname=hostname,
            command="proxmox-backup-manager datastore list --output-format json 2>/dev/null",
            port=port,
            username=username,
            key_path=key_path
        )
        
        if result.success and result.stdout.strip():
            try:
                return json.loads(result.stdout)
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse datastore list: {result.stdout}")
        
        return []
    
    async def list_backups(
        self,
        pbs_hostname: str,
        datastore: str,
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        vm_id: Optional[int] = None,
        from_node_hostname: Optional[str] = None,
        from_node_port: int = 22,
        from_node_user: str = "root",
        from_node_key: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """
        Lista i backup disponibili su un PBS datastore.
        Esegue il comando da from_node se specificato, altrimenti direttamente sul PBS.
        """
        
        # Build PBS repository string
        pbs_repo = f"{pbs_user}@{pbs_hostname}:{datastore}"
        
        # Build command
        cmd_parts = ["proxmox-backup-client", "snapshot", "list", "--repository", pbs_repo]
        
        if pbs_fingerprint:
            cmd_parts.extend(["--fingerprint", pbs_fingerprint])
        
        cmd_parts.append("--output-format json")
        
        # Add password via environment if provided
        env_prefix = ""
        if pbs_password:
            env_prefix = f"PBS_PASSWORD='{pbs_password}' "
        
        cmd = env_prefix + " ".join(cmd_parts) + " 2>/dev/null"
        
        # Execute from node or directly
        exec_host = from_node_hostname or pbs_hostname
        exec_port = from_node_port if from_node_hostname else 22
        exec_user = from_node_user if from_node_hostname else "root"
        exec_key = from_node_key if from_node_hostname else "/root/.ssh/id_rsa"
        
        result = await ssh_service.execute(
            hostname=exec_host,
            command=cmd,
            port=exec_port,
            username=exec_user,
            key_path=exec_key
        )
        
        backups = []
        if result.success and result.stdout.strip():
            try:
                all_backups = json.loads(result.stdout)
                # Filter by VM ID if specified
                if vm_id:
                    for backup in all_backups:
                        # Backup format: "vm/100/2024-01-15T10:30:00Z"
                        if f"vm/{vm_id}/" in backup.get("backup-id", ""):
                            backups.append(backup)
                else:
                    backups = all_backups
            except json.JSONDecodeError:
                logger.warning(f"Failed to parse backup list: {result.stdout}")
        
        return backups
    
    async def get_latest_backup(
        self,
        pbs_hostname: str,
        datastore: str,
        vm_id: int,
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        from_node_hostname: Optional[str] = None,
        from_node_port: int = 22,
        from_node_user: str = "root",
        from_node_key: str = "/root/.ssh/id_rsa"
    ) -> Optional[Dict]:
        """
        Ottiene l'ultimo backup disponibile per una VM
        """
        backups = await self.list_backups(
            pbs_hostname=pbs_hostname,
            datastore=datastore,
            pbs_user=pbs_user,
            pbs_password=pbs_password,
            pbs_fingerprint=pbs_fingerprint,
            vm_id=vm_id,
            from_node_hostname=from_node_hostname,
            from_node_port=from_node_port,
            from_node_user=from_node_user,
            from_node_key=from_node_key
        )
        
        if not backups:
            return None
        
        # Sort by backup time and return latest
        sorted_backups = sorted(backups, key=lambda x: x.get("backup-time", ""), reverse=True)
        return sorted_backups[0] if sorted_backups else None
    
    async def _ensure_pbs_storage(
        self,
        node_hostname: str,
        storage_name: str,
        pbs_hostname: str,
        datastore: str,
        pbs_user: str,
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        node_port: int = 22,
        node_user: str = "root",
        node_key: str = "/root/.ssh/id_rsa"
    ) -> Tuple[bool, str]:
        """
        Assicura che lo storage PBS sia configurato sul nodo PVE.
        Crea lo storage se non esiste.
        
        Returns:
            (success, message)
        """
        # Verifica se lo storage esiste già
        check_cmd = f"pvesm status 2>/dev/null | grep -q '^{storage_name} '"
        check_result = await ssh_service.execute(
            hostname=node_hostname,
            command=check_cmd,
            port=node_port,
            username=node_user,
            key_path=node_key
        )
        
        if check_result.exit_code == 0:
            logger.info(f"Storage {storage_name} already exists on {node_hostname}")
            return True, f"Storage {storage_name} già presente"
        
        # Crea lo storage PBS
        logger.info(f"Creating PBS storage {storage_name} on {node_hostname}")
        
        # Build add storage command
        add_cmd_parts = [
            "pvesm", "add", "pbs", storage_name,
            "--server", pbs_hostname,
            "--datastore", datastore,
            "--username", pbs_user,
            "--content", "backup"
        ]
        
        if pbs_fingerprint:
            add_cmd_parts.extend(["--fingerprint", pbs_fingerprint])
        
        if pbs_password:
            add_cmd_parts.extend(["--password", pbs_password])
        
        add_cmd = " ".join(add_cmd_parts)
        
        add_result = await ssh_service.execute(
            hostname=node_hostname,
            command=add_cmd,
            port=node_port,
            username=node_user,
            key_path=node_key,
            timeout=60
        )
        
        if add_result.success or add_result.exit_code == 0:
            logger.info(f"Storage {storage_name} created successfully on {node_hostname}")
            return True, f"Storage {storage_name} creato con successo"
        else:
            logger.error(f"Failed to create storage {storage_name}: {add_result.stderr}")
            return False, f"Errore creazione storage: {add_result.stderr}"
    
    async def run_backup(
        self,
        source_node_hostname: str,
        vm_id: int,
        pbs_hostname: str,
        datastore: str,
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        pbs_storage_id: Optional[str] = None,  # Nome storage PBS già configurato sul nodo
        vm_type: str = "qemu",
        mode: str = "snapshot",  # snapshot, stop, suspend
        compress: str = "zstd",  # none, lzo, gzip, zstd
        source_node_port: int = 22,
        source_node_user: str = "root",
        source_node_key: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """
        Esegue un backup di una VM verso PBS.
        
        Args:
            source_node_hostname: Hostname del nodo Proxmox VE sorgente
            vm_id: VMID della VM da backuppare
            pbs_hostname: Hostname del PBS server
            datastore: Nome del datastore PBS
            pbs_user: Utente PBS (es: root@pam)
            pbs_password: Password PBS
            pbs_fingerprint: Fingerprint SSL del PBS
            pbs_storage_id: Nome dello storage PBS già configurato sul nodo (se None, ne crea uno nuovo)
            vm_type: qemu o lxc
            mode: Modalità backup (snapshot, stop, suspend)
            compress: Algoritmo compressione
        
        Returns:
            Dict con success, backup_id, message, output
        """
        start_time = datetime.utcnow()
        
        # Se è specificato uno storage esistente, usalo; altrimenti crea/usa uno standard
        if pbs_storage_id:
            # Verifica che lo storage esista
            check_result = await ssh_service.execute(
                hostname=source_node_hostname,
                command=f"pvesm status 2>/dev/null | grep -q '^{pbs_storage_id} '",
                port=source_node_port,
                username=source_node_user,
                key_path=source_node_key
            )
            
            if check_result.exit_code != 0:
                return {
                    "success": False,
                    "backup_id": None,
                    "message": f"Storage PBS '{pbs_storage_id}' non trovato sul nodo",
                    "output": "",
                    "error": f"Storage {pbs_storage_id} non esiste",
                    "duration": 0
                }
            
            storage_name = pbs_storage_id
            logger.info(f"Using existing PBS storage: {storage_name}")
        else:
            # Crea storage PBS automaticamente
            storage_name = f"pbs-{datastore}"
            
            storage_ok, storage_msg = await self._ensure_pbs_storage(
                node_hostname=source_node_hostname,
                storage_name=storage_name,
                pbs_hostname=pbs_hostname,
                datastore=datastore,
                pbs_user=pbs_user,
                pbs_password=pbs_password,
                pbs_fingerprint=pbs_fingerprint,
                node_port=source_node_port,
                node_user=source_node_user,
                node_key=source_node_key
            )
            
            if not storage_ok:
                return {
                    "success": False,
                    "backup_id": None,
                    "message": f"Impossibile configurare storage PBS: {storage_msg}",
                    "output": "",
                    "error": storage_msg,
                    "duration": 0
                }
        
        # Setup comando backup vzdump
        vzdump_parts = [
            "vzdump", str(vm_id),
            "--mode", mode,
            "--compress", compress,
            "--storage", storage_name,
            "--remove", "0"  # Non rimuovere backup precedenti
        ]
        
        # Esegui backup
        vzdump_cmd = " ".join(vzdump_parts)
        logger.info(f"Running backup: {vzdump_cmd}")
        
        result = await ssh_service.execute(
            hostname=source_node_hostname,
            command=vzdump_cmd,
            port=source_node_port,
            username=source_node_user,
            key_path=source_node_key,
            timeout=7200  # 2 ore timeout
        )
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        if result.success or "Backup job finished successfully" in result.stdout:
            # Cerca l'ID del backup dall'output
            backup_id = None
            # Pattern: backup started, backup finished, etc.
            backup_match = re.search(r"backup '(.+?)' successful", result.stdout) or \
                          re.search(r"creating vzdump archive '(.+?)'", result.stdout) or \
                          re.search(r"backup-id: '?([^'\n]+)'?", result.stdout)
            
            if backup_match:
                backup_id = backup_match.group(1)
            
            return {
                "success": True,
                "backup_id": backup_id,
                "message": f"Backup VM {vm_id} completato in {int(duration)}s",
                "output": result.stdout,
                "duration": int(duration)
            }
        else:
            return {
                "success": False,
                "backup_id": None,
                "message": f"Backup fallito: {result.stderr}",
                "output": result.stdout,
                "error": result.stderr,
                "duration": int(duration)
            }
    
    async def run_restore(
        self,
        dest_node_hostname: str,
        vm_id: int,
        pbs_hostname: str,
        datastore: str,
        backup_id: Optional[str] = None,  # None = usa l'ultimo
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        pbs_storage_id: Optional[str] = None,  # Nome storage PBS esistente sul nodo dest
        dest_vm_id: Optional[int] = None,  # None = stesso del sorgente
        dest_vm_name_suffix: Optional[str] = None,  # Suffisso nome VM (es: "-replica")
        dest_storage: Optional[str] = None,  # Storage target per i dischi
        vm_type: str = "qemu",
        start_vm: bool = False,
        unique: bool = True,  # Genera nuovi UUID
        overwrite: bool = True,
        dest_node_port: int = 22,
        dest_node_user: str = "root",
        dest_node_key: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """
        Ripristina una VM da PBS su un nodo destinazione.
        
        Args:
            dest_node_hostname: Hostname del nodo Proxmox VE destinazione
            vm_id: VMID della VM originale (per trovare il backup)
            pbs_hostname: Hostname del PBS server
            datastore: Nome del datastore PBS
            backup_id: ID specifico del backup (None = ultimo disponibile)
            dest_vm_id: VMID per la VM ripristinata (None = stesso del sorgente)
            dest_storage: Storage dove ripristinare i dischi
            vm_type: qemu o lxc
            start_vm: Avvia la VM dopo il restore
            unique: Genera nuovi UUID per i dischi
            overwrite: Sovrascrive se la VM esiste già
        
        Returns:
            Dict con success, message, output
        """
        start_time = datetime.utcnow()
        
        target_vmid = dest_vm_id or vm_id
        
        # Se è specificato uno storage esistente, usalo; altrimenti crea/usa uno standard
        if pbs_storage_id:
            # Verifica che lo storage esista sul nodo destinazione
            check_result = await ssh_service.execute(
                hostname=dest_node_hostname,
                command=f"pvesm status 2>/dev/null | grep -q '^{pbs_storage_id} '",
                port=dest_node_port,
                username=dest_node_user,
                key_path=dest_node_key
            )
            
            if check_result.exit_code != 0:
                return {
                    "success": False,
                    "vm_id": target_vmid,
                    "message": f"Storage PBS '{pbs_storage_id}' non trovato sul nodo destinazione",
                    "output": "",
                    "error": f"Storage {pbs_storage_id} non esiste su {dest_node_hostname}",
                    "duration": 0
                }
            
            storage_name = pbs_storage_id
            logger.info(f"Restore: using existing PBS storage: {storage_name}")
        else:
            # Crea storage PBS automaticamente
            storage_name = f"pbs-{datastore}"
            
            # Setup storage PBS sul nodo destinazione
            storage_ok, storage_msg = await self._ensure_pbs_storage(
                node_hostname=dest_node_hostname,
                storage_name=storage_name,
                pbs_hostname=pbs_hostname,
                datastore=datastore,
                pbs_user=pbs_user,
                pbs_password=pbs_password,
                pbs_fingerprint=pbs_fingerprint,
                node_port=dest_node_port,
                node_user=dest_node_user,
                node_key=dest_node_key
            )
            
            if not storage_ok:
                return {
                    "success": False,
                    "vm_id": target_vmid,
                    "message": f"Impossibile configurare storage PBS: {storage_msg}",
                    "output": "",
                    "error": storage_msg,
                    "duration": 0
                }
        
        # Se non abbiamo un backup_id specifico, trova l'ultimo
        if not backup_id:
            # Lista backup disponibili e prendi l'ultimo
            list_cmd = f"pvesm list {storage_name} --vmid {vm_id} 2>/dev/null | tail -n +2 | sort -k5 -r | head -1"
            list_result = await ssh_service.execute(
                hostname=dest_node_hostname,
                command=list_cmd,
                port=dest_node_port,
                username=dest_node_user,
                key_path=dest_node_key
            )
            
            if list_result.success and list_result.stdout.strip():
                # Parse volid dalla prima colonna
                parts = list_result.stdout.strip().split()
                if parts:
                    backup_id = parts[0]
            
            if not backup_id:
                return {
                    "success": False,
                    "message": f"Nessun backup trovato per VM {vm_id}",
                    "output": "",
                    "duration": 0
                }
        
        # Se esiste già la VM e overwrite è True, rimuovila prima
        if overwrite:
            check_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} status {target_vmid} 2>/dev/null"
            check_result = await ssh_service.execute(
                hostname=dest_node_hostname,
                command=check_cmd,
                port=dest_node_port,
                username=dest_node_user,
                key_path=dest_node_key
            )
            
            if check_result.success and ("running" in check_result.stdout or "stopped" in check_result.stdout):
                # Stop e destroy VM esistente
                destroy_cmd = f"""
{'qm' if vm_type == 'qemu' else 'pct'} stop {target_vmid} 2>/dev/null || true
sleep 2
{'qm' if vm_type == 'qemu' else 'pct'} destroy {target_vmid} --purge 2>/dev/null || true
"""
                await ssh_service.execute(
                    hostname=dest_node_hostname,
                    command=destroy_cmd,
                    port=dest_node_port,
                    username=dest_node_user,
                    key_path=dest_node_key,
                    timeout=120
                )
        
        # Build restore command
        restore_cmd = f"qmrestore {backup_id} {target_vmid}"
        
        if dest_storage:
            restore_cmd += f" --storage {dest_storage}"
        
        if unique:
            restore_cmd += " --unique"
        
        if start_vm:
            restore_cmd += " --start"
        
        # Esegui restore
        result = await ssh_service.execute(
            hostname=dest_node_hostname,
            command=restore_cmd,
            port=dest_node_port,
            username=dest_node_user,
            key_path=dest_node_key,
            timeout=7200  # 2 ore
        )
        
        duration = (datetime.utcnow() - start_time).total_seconds()
        
        if result.success or "successfully" in result.stdout.lower():
            # Applica suffisso al nome VM se specificato
            new_vm_name = None
            if dest_vm_name_suffix:
                # Ottieni nome corrente
                get_name_cmd = f"qm config {target_vmid} 2>/dev/null | grep '^name:' | cut -d' ' -f2"
                name_result = await ssh_service.execute(
                    hostname=dest_node_hostname,
                    command=get_name_cmd,
                    port=dest_node_port,
                    username=dest_node_user,
                    key_path=dest_node_key
                )
                
                if name_result.success and name_result.stdout.strip():
                    current_name = name_result.stdout.strip()
                    # Rimuovi eventuale suffisso esistente prima di aggiungerne uno nuovo
                    if dest_vm_name_suffix in current_name:
                        new_vm_name = current_name
                    else:
                        new_vm_name = f"{current_name}{dest_vm_name_suffix}"
                    
                    # Rinomina VM
                    rename_cmd = f"qm set {target_vmid} --name '{new_vm_name}'"
                    await ssh_service.execute(
                        hostname=dest_node_hostname,
                        command=rename_cmd,
                        port=dest_node_port,
                        username=dest_node_user,
                        key_path=dest_node_key
                    )
                    logger.info(f"VM {target_vmid} renamed to {new_vm_name}")
            
            return {
                "success": True,
                "vm_id": target_vmid,
                "vm_name": new_vm_name,
                "backup_id": backup_id,
                "message": f"Restore VM {target_vmid} completato in {int(duration)}s",
                "output": result.stdout,
                "duration": int(duration)
            }
        else:
            return {
                "success": False,
                "vm_id": target_vmid,
                "backup_id": backup_id,
                "message": f"Restore fallito: {result.stderr}",
                "output": result.stdout,
                "error": result.stderr,
                "duration": int(duration)
            }
    
    async def run_full_recovery(
        self,
        source_node_hostname: str,
        vm_id: int,
        pbs_hostname: str,
        datastore: str,
        dest_node_hostname: str,
        pbs_user: str = "root@pam",
        pbs_password: Optional[str] = None,
        pbs_fingerprint: Optional[str] = None,
        pbs_storage_id: Optional[str] = None,  # Nome storage PBS esistente
        dest_vm_id: Optional[int] = None,
        dest_vm_name_suffix: Optional[str] = None,  # Suffisso nome VM
        dest_storage: Optional[str] = None,
        vm_type: str = "qemu",
        backup_mode: str = "snapshot",
        backup_compress: str = "zstd",
        start_vm: bool = False,
        unique: bool = True,
        overwrite: bool = True,
        source_node_port: int = 22,
        source_node_user: str = "root",
        source_node_key: str = "/root/.ssh/id_rsa",
        dest_node_port: int = 22,
        dest_node_user: str = "root",
        dest_node_key: str = "/root/.ssh/id_rsa"
    ) -> Dict:
        """
        Esegue l'intero ciclo di recovery: backup -> restore -> registrazione.
        
        NOTA: Questa funzione è mantenuta per compatibilità, ma ora la sequenza
        dettagliata è gestita direttamente in execute_recovery_job_task con logging
        separato per ogni fase.
        
        Returns:
            Dict con success, phases (backup, restore), message, duration
        """
        start_time = datetime.utcnow()
        result = {
            "success": False,
            "phases": {
                "backup": None,
                "restore": None
            },
            "message": "",
            "duration": 0
        }
        
        # Phase 1: Backup
        logger.info(f"[PBS Service] Fase 1/2: Backup VM {vm_id} da {source_node_hostname} verso PBS {pbs_hostname}")
        backup_result = await self.run_backup(
            source_node_hostname=source_node_hostname,
            vm_id=vm_id,
            pbs_hostname=pbs_hostname,
            datastore=datastore,
            pbs_user=pbs_user,
            pbs_password=pbs_password,
            pbs_fingerprint=pbs_fingerprint,
            pbs_storage_id=pbs_storage_id,
            vm_type=vm_type,
            mode=backup_mode,
            compress=backup_compress,
            source_node_port=source_node_port,
            source_node_user=source_node_user,
            source_node_key=source_node_key
        )
        
        result["phases"]["backup"] = backup_result
        
        if not backup_result["success"]:
            result["message"] = f"Backup fallito: {backup_result.get('error', 'Unknown error')}"
            result["duration"] = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"[PBS Service] Recovery fallita nella fase backup: {backup_result.get('error')}")
            return result
        
        backup_id = backup_result.get("backup_id")
        logger.info(f"[PBS Service] ✓ Backup completato - ID: {backup_id}")
        logger.info(f"[PBS Service] Fase 2/2: Restore VM {vm_id} da PBS {pbs_hostname} verso {dest_node_hostname}")
        
        # Phase 2: Restore (solo se backup riuscito)
        restore_result = await self.run_restore(
            dest_node_hostname=dest_node_hostname,
            vm_id=vm_id,
            pbs_hostname=pbs_hostname,
            datastore=datastore,
            backup_id=backup_id,  # Usa backup_id dal backup appena completato
            pbs_user=pbs_user,
            pbs_password=pbs_password,
            pbs_fingerprint=pbs_fingerprint,
            pbs_storage_id=pbs_storage_id,  # Usa stesso storage del backup
            dest_vm_id=dest_vm_id,
            dest_vm_name_suffix=dest_vm_name_suffix,
            dest_storage=dest_storage,
            vm_type=vm_type,
            start_vm=start_vm,
            unique=unique,
            overwrite=overwrite,
            dest_node_port=dest_node_port,
            dest_node_user=dest_node_user,
            dest_node_key=dest_node_key
        )
        
        result["phases"]["restore"] = restore_result
        
        if not restore_result["success"]:
            result["message"] = f"Restore fallito: {restore_result.get('error', 'Unknown error')}"
            result["duration"] = (datetime.utcnow() - start_time).total_seconds()
            logger.error(f"[PBS Service] Recovery fallita nella fase restore: {restore_result.get('error')}")
            return result
        
        # Success!
        result["success"] = True
        result["message"] = f"Recovery VM {vm_id} completata con successo"
        result["duration"] = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"[PBS Service] ✓ Recovery completata in {result['duration']:.1f}s")
        
        return result


# Singleton
pbs_service = PBSService()

