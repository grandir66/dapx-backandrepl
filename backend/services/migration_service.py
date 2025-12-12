"""
Migration Service - Gestione migrazione/copia VM tra nodi Proxmox
Usa funzionalità native di Proxmox (qm copy / pct copy)
"""

import asyncio
from typing import Optional, Dict, Tuple, List
import logging
import re
import json
import time
from datetime import datetime

from services.ssh_service import ssh_service, SSHResult
from services.logging_config import get_logger, get_operation_logger, OperationLogger

logger = get_logger(__name__)


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
        dest_key: str = "/root/.ssh/id_rsa",
        force_overwrite: bool = False  # Se True, elimina VM esistente senza conferma
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
            logger.error(f"[MIGRATION] FASE: VERIFICA VM SORGENTE FALLITA")
            logger.error(f"[MIGRATION] VM: {vm_id} | Host: {source_hostname}")
            logger.error(f"[MIGRATION] Comando: {check_cmd}")
            logger.error(f"[MIGRATION] Exit code: {check_result.exit_code}")
            logger.error(f"[MIGRATION] Stderr: {check_result.stderr}")
            return {
                "success": False,
                "message": f"VM {vm_id} ({vm_type}) non trovata su {source_hostname}. Verifica che la VM esista e sia accessibile.",
                "error": check_result.stderr or f"Comando '{check_cmd}' fallito con exit code {check_result.exit_code}",
                "phase": "check_source_vm",
                "exit_code": check_result.exit_code,
                "command": check_cmd,
                "source_host": source_hostname
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
                logger.warning(f"[MIGRATION] Snapshot pre-migrazione fallito (non bloccante)")
                logger.warning(f"[MIGRATION] Comando: {snap_cmd}")
                logger.warning(f"[MIGRATION] Stderr: {snap_result.stderr}")
                # Continua comunque la migrazione
        
        # Costruisci comando di migrazione
        # qm migrate <vmid> <target> [OPTIONS] - per migrazione tra nodi
        # pct migrate <vmid> <target> [OPTIONS] - per LXC
        
        migrate_options = []
        
        # Target: user@hostname
        target = f"{dest_user}@{dest_hostname}"
        if dest_port != 22:
            target = f"{dest_user}@{dest_hostname}:{dest_port}"
        
        # VMID destinazione
        if dest_vm_id and dest_vm_id != vm_id:
            migrate_options.append(f"--newid {dest_vm_id}")
        
        # Storage mapping (se specificato in hw_config)
        # qm migrate supporta --storage per specificare storage destinazione
        if hw_config and "storage" in hw_config:
            storage_map = hw_config["storage"]
            # Prendi il primo storage specificato (qm migrate supporta un solo --storage)
            for disk, new_storage in storage_map.items():
                if ":" in new_storage:
                    storage_name = new_storage.split(":")[0]
                    migrate_options.append(f"--storage {storage_name}")
                    break
        
        # Per migrazione "copy" (non move), dobbiamo prima clonare, poi migrare
        # Oppure usare vzdump + restore
        if migration_type == "copy":
            # Per copia, usiamo vzdump + restore invece di migrate
            # migrate sposta la VM, non la copia
            return await self._copy_vm_with_backup(
                source_hostname=source_hostname,
                dest_hostname=dest_hostname,
                vm_id=vm_id,
                vm_type=vm_type,
                dest_vm_id=target_vmid,
                dest_vm_name_suffix=dest_vm_name_suffix,
                create_snapshot=create_snapshot,
                keep_snapshots=keep_snapshots,
                start_after=start_after,
                hw_config=hw_config,
                source_port=source_port,
                source_user=source_user,
                source_key=source_key,
                dest_port=dest_port,
                dest_user=dest_user,
                dest_key=dest_key,
                force_overwrite=force_overwrite
            )
        
        # Per move, usa migrate diretto
        # Costruisci comando completo
        migrate_cmd = f"{cmd} migrate {vm_id} {target} {' '.join(migrate_options)}"
        
        logger.info(f"[MIGRATION] FASE: MIGRATE (MOVE)")
        logger.info(f"[MIGRATION] VM: {vm_id} ({vm_type}) | {source_hostname} -> {target}")
        logger.info(f"[MIGRATION] Comando: {migrate_cmd}")
        
        # Esegui migrazione
        migrate_result = await ssh_service.execute(
            hostname=source_hostname,
            command=migrate_cmd,
            port=source_port,
            username=source_user,
            key_path=source_key,
            timeout=3600  # 1 ora per migrazioni grandi
        )
        
        if not migrate_result.success:
            full_output = f"STDOUT:\n{migrate_result.stdout}\n\nSTDERR:\n{migrate_result.stderr}"
            logger.error(f"[MIGRATION] FASE: MIGRATE (MOVE) FALLITA")
            logger.error(f"[MIGRATION] VM: {vm_id} ({vm_type}) | {source_hostname} -> {dest_hostname}")
            logger.error(f"[MIGRATION] Comando: {migrate_cmd}")
            logger.error(f"[MIGRATION] Exit code: {migrate_result.exit_code}")
            logger.error(f"[MIGRATION] Output completo:\n{full_output}")
            
            # Estrai errori specifici
            error_lines = [line for line in full_output.split('\n') if 'ERROR' in line or 'error' in line.lower()]
            specific_error = '\n'.join(error_lines) if error_lines else migrate_result.stderr
            
            return {
                "success": False,
                "message": f"Migrazione (move) VM {vm_id} fallita: {specific_error[:500] if specific_error else 'Nessun dettaglio errore'}",
                "error": specific_error,
                "phase": "migrate_move",
                "exit_code": migrate_result.exit_code,
                "command": migrate_cmd,
                "source_host": source_hostname,
                "dest_host": dest_hostname,
                "full_output": full_output
            }
        
        # Estrai dimensione trasferita dall'output
        transferred = "0B"
        if "transferred" in migrate_result.stdout.lower() or "MiB" in migrate_result.stdout:
            # Cerca pattern tipo "transferred 10.5 GiB"
            match = re.search(r'(\d+\.?\d*)\s*(GiB|MiB|KiB|GB|MB|KB)', migrate_result.stdout, re.IGNORECASE)
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
        
        # Gestione snapshot - esegui sempre il pruning se keep_snapshots > 0
        if keep_snapshots > 0:
            logger.info(f"[MIGRATION] Esecuzione pruning snapshot (keep={keep_snapshots})")
            await self._prune_snapshots(
                hostname=source_hostname,
                vm_id=vm_id,
                vm_type=vm_type,
                keep=keep_snapshots,
                port=source_port,
                username=source_user,
                key_path=source_key
            )
        else:
            logger.info(f"[MIGRATION] Pruning snapshot saltato (keep_snapshots={keep_snapshots})")
        
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
        
        logger.info(f"[MIGRATION] ========== MIGRAZIONE COMPLETATA ==========")
        logger.info(f"[MIGRATION] VM: {vm_id} -> {target_vmid} su {dest_hostname}")
        logger.info(f"[MIGRATION] Durata: {duration}s | Trasferiti: {transferred}")
        
        return {
            "success": True,
            "message": f"VM {vm_id} migrata con successo su {dest_hostname} (VMID: {target_vmid})",
            "vm_id": target_vmid,
            "duration": duration,
            "transferred": transferred,
            "snapshot_created": snapshot_name if create_snapshot else None
        }
    
    async def _copy_vm_with_backup(
        self,
        source_hostname: str,
        dest_hostname: str,
        vm_id: int,
        vm_type: str,
        dest_vm_id: Optional[int] = None,
        dest_vm_name_suffix: Optional[str] = None,
        create_snapshot: bool = True,
        keep_snapshots: int = 1,
        start_after: bool = False,
        hw_config: Optional[Dict] = None,
        source_port: int = 22,
        source_user: str = "root",
        source_key: str = "/root/.ssh/id_rsa",
        dest_port: int = 22,
        dest_user: str = "root",
        dest_key: str = "/root/.ssh/id_rsa",
        force_overwrite: bool = False  # Se True, elimina VM esistente senza conferma
    ) -> Dict:
        """
        Copia VM usando vzdump + restore (per copia tra nodi senza cluster)
        """
        import time
        start_time = time.time()
        
        # vzdump funziona per entrambi qemu e lxc
        restore_cmd = "qmrestore" if vm_type == "qemu" else "pct restore"
        
        target_vmid = dest_vm_id if dest_vm_id else vm_id
        
        # Verifica se la VM destinazione esiste già
        check_vm_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} status {target_vmid} 2>/dev/null"
        check_result = await ssh_service.execute(
            hostname=dest_hostname,
            command=check_vm_cmd,
            port=dest_port,
            username=dest_user,
            key_path=dest_key,
            timeout=30
        )
        
        if check_result.success and check_result.stdout.strip():
            # La VM esiste già
            if not force_overwrite:
                # Richiedi conferma per esecuzioni manuali
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "message": f"La VM {target_vmid} esiste già su {dest_hostname}. Vuoi eliminarla e procedere con la migrazione?",
                    "existing_vm_id": target_vmid,
                    "dest_hostname": dest_hostname
                }
            
            # force_overwrite=True: elimina la VM esistente
            logger.info(f"VM {target_vmid} esiste già su {dest_hostname}, la elimino prima di procedere")
            
            # Prima stoppa la VM se in esecuzione
            stop_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} stop {target_vmid} --skiplock 2>/dev/null || true"
            await ssh_service.execute(
                hostname=dest_hostname,
                command=stop_cmd,
                port=dest_port,
                username=dest_user,
                key_path=dest_key,
                timeout=60
            )
            
            # Attendi che si fermi
            await asyncio.sleep(3)
            
            # Elimina la VM
            destroy_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} destroy {target_vmid} --purge --skiplock"
            destroy_result = await ssh_service.execute(
                hostname=dest_hostname,
                command=destroy_cmd,
                port=dest_port,
                username=dest_user,
                key_path=dest_key,
                timeout=120
            )
            
            if not destroy_result.success:
                full_output = f"STDOUT:\n{destroy_result.stdout}\n\nSTDERR:\n{destroy_result.stderr}"
                logger.error(f"[MIGRATION] FASE: ELIMINAZIONE VM ESISTENTE FALLITA")
                logger.error(f"[MIGRATION] VM: {target_vmid} | Host: {dest_hostname}")
                logger.error(f"[MIGRATION] Comando: {destroy_cmd}")
                logger.error(f"[MIGRATION] Exit code: {destroy_result.exit_code}")
                logger.error(f"[MIGRATION] Output:\n{full_output}")
                return {
                    "success": False,
                    "message": f"Impossibile eliminare VM esistente {target_vmid} su {dest_hostname}: {destroy_result.stderr[:300] if destroy_result.stderr else 'Nessun dettaglio'}",
                    "error": destroy_result.stderr or f"Destroy fallito con exit code {destroy_result.exit_code}",
                    "phase": "destroy_existing_vm",
                    "exit_code": destroy_result.exit_code,
                    "command": destroy_cmd,
                    "dest_host": dest_hostname,
                    "full_output": full_output
                }
            
            logger.info(f"VM {target_vmid} eliminata con successo")
        
        # Crea snapshot se richiesto
        snapshot_name = None
        if create_snapshot:
            snapshot_name = f"migration-{int(time.time())}"
            snap_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} snapshot {vm_id} {snapshot_name} --description 'Pre-migration snapshot'"
            logger.info(f"[MIGRATION] FASE: Creazione snapshot pre-migrazione")
            logger.info(f"[MIGRATION] VM: {vm_id} | Snapshot: {snapshot_name}")
            snap_result = await ssh_service.execute(
                hostname=source_hostname,
                command=snap_cmd,
                port=source_port,
                username=source_user,
                key_path=source_key,
                timeout=300
            )
            if not snap_result.success:
                logger.warning(f"[MIGRATION] Snapshot pre-migrazione fallito (non bloccante)")
                logger.warning(f"[MIGRATION] Comando: {snap_cmd}")
                logger.warning(f"[MIGRATION] Stderr: {snap_result.stderr}")
        
        # Determina directory di backup con spazio sufficiente
        # Priorità: /var/lib/vz/dump (standard Proxmox) > /var/tmp > /tmp
        backup_dir = "/var/lib/vz/dump"
        
        # Stima dimensione VM (somma dischi)
        size_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} config {vm_id} | grep -E '^(scsi|virtio|ide|sata|rootfs|mp)[0-9]*:' | grep -oP '\\d+G' | head -1"
        size_result = await ssh_service.execute(
            hostname=source_hostname,
            command=size_cmd,
            port=source_port,
            username=source_user,
            key_path=source_key,
            timeout=30
        )
        
        estimated_size_gb = 50  # Default 50GB se non riusciamo a stimare
        if size_result.success and size_result.stdout.strip():
            try:
                estimated_size_gb = int(size_result.stdout.strip().replace('G', ''))
            except:
                pass
        
        logger.info(f"Dimensione stimata VM {vm_id}: ~{estimated_size_gb} GB")
        
        # Trova directory con spazio sufficiente
        for test_dir in ["/var/lib/vz/dump", "/var/tmp", "/tmp"]:
            space_cmd = f"df -BG {test_dir} 2>/dev/null | tail -1 | awk '{{print $4}}' | tr -d 'G'"
            space_result = await ssh_service.execute(
                hostname=source_hostname,
                command=space_cmd,
                port=source_port,
                username=source_user,
                key_path=source_key,
                timeout=30
            )
            
            if space_result.success and space_result.stdout.strip().isdigit():
                available_gb = int(space_result.stdout.strip())
                logger.info(f"Spazio disponibile in {test_dir}: {available_gb} GB")
                
                # Serve almeno 1.5x la dimensione stimata (compressione + margine)
                if available_gb >= estimated_size_gb * 1.5:
                    backup_dir = test_dir
                    logger.info(f"Uso {backup_dir} per il backup (spazio sufficiente)")
                    break
                else:
                    logger.warning(f"{test_dir} ha solo {available_gb} GB, serve almeno {int(estimated_size_gb * 1.5)} GB")
        else:
            # Nessuna directory ha spazio sufficiente
            logger.error(f"Nessuna directory ha spazio sufficiente per il backup (~{estimated_size_gb} GB necessari)")
            return {
                "success": False,
                "message": f"Spazio insufficiente per il backup. Servono almeno {int(estimated_size_gb * 1.5)} GB liberi",
                "error": "No space available for backup"
            }
        
        # Crea backup
        # Prova prima con --mode snapshot, poi fallback a --mode suspend/stop
        # Nota: non possiamo usare --storage e --dumpdir insieme
        backup_modes = ["snapshot", "suspend", "stop"]
        backup_result = None
        used_mode = None
        
        # Errori non critici che permettono di provare con un altro mode
        # Questi errori sono tipicamente legati all'avvio della VM (mode snapshot/suspend)
        # ma non impediscono il backup con mode stop
        recoverable_errors = [
            "bridge",
            "does not exist", 
            "not running",
            "snapshot feature is not available",
            "unable to activate",
            "network",
            "vmbr",
            "failed to start",
            "cannot start"
        ]
        
        last_error = None
        last_full_output = None
        for backup_mode in backup_modes:
            logger.info(f"[MIGRATION] FASE: BACKUP VM - Tentativo con mode={backup_mode}")
            logger.info(f"[MIGRATION] VM: {vm_id} ({vm_type}) | Host: {source_hostname}")
            logger.info(f"[MIGRATION] Directory backup: {backup_dir}")
            backup_cmd = f"vzdump {vm_id} --compress zstd --dumpdir {backup_dir} --mode {backup_mode} --remove 0"
            logger.debug(f"[MIGRATION] Comando: {backup_cmd}")
            
            backup_result = await ssh_service.execute(
                hostname=source_hostname,
                command=backup_cmd,
                port=source_port,
                username=source_user,
                key_path=source_key,
                timeout=3600
            )
            
            if backup_result.success:
                used_mode = backup_mode
                logger.info(f"[MIGRATION] Backup VM {vm_id} completato con mode={backup_mode}")
                break
            
            # Controlla se l'errore è recuperabile (prova prossimo mode)
            full_output_lower = (backup_result.stdout + "\n" + backup_result.stderr).lower()
            is_recoverable = any(err in full_output_lower for err in recoverable_errors)
            
            full_output = f"STDOUT:\n{backup_result.stdout}\n\nSTDERR:\n{backup_result.stderr}"
            last_full_output = full_output
            
            if is_recoverable:
                logger.warning(f"[MIGRATION] Mode {backup_mode} fallito - errore recuperabile, provo alternativa")
                logger.warning(f"[MIGRATION] Exit code: {backup_result.exit_code}")
                logger.warning(f"[MIGRATION] Errore: {backup_result.stderr[:300]}")
                last_error = backup_result.stderr
                continue
            else:
                # Errore non recuperabile, fallisci subito
                logger.error(f"[MIGRATION] FASE: BACKUP FALLITO (errore non recuperabile)")
                logger.error(f"[MIGRATION] VM: {vm_id} ({vm_type}) | Host: {source_hostname}")
                logger.error(f"[MIGRATION] Mode: {backup_mode}")
                logger.error(f"[MIGRATION] Comando: {backup_cmd}")
                logger.error(f"[MIGRATION] Exit code: {backup_result.exit_code}")
                logger.error(f"[MIGRATION] Output completo:\n{full_output}")
                
                # Estrai errori specifici dall'output
                error_lines = [line for line in full_output.split('\n') if 'ERROR' in line or 'error' in line.lower()]
                specific_error = '\n'.join(error_lines) if error_lines else backup_result.stderr
                
                return {
                    "success": False,
                    "message": f"Backup VM {vm_id} fallito (mode={backup_mode}): {specific_error[:500] if specific_error else 'Nessun dettaglio'}",
                    "error": specific_error,
                    "phase": "backup",
                    "backup_mode": backup_mode,
                    "exit_code": backup_result.exit_code,
                    "command": backup_cmd,
                    "source_host": source_hostname,
                    "backup_dir": backup_dir,
                    "full_output": full_output
                }
        
        if not backup_result or not backup_result.success:
            logger.error(f"[MIGRATION] FASE: BACKUP FALLITO - Tutti i mode esauriti")
            logger.error(f"[MIGRATION] VM: {vm_id} ({vm_type}) | Host: {source_hostname}")
            logger.error(f"[MIGRATION] Mode provati: {', '.join(backup_modes)}")
            logger.error(f"[MIGRATION] Ultimo errore: {last_error}")
            if last_full_output:
                logger.error(f"[MIGRATION] Ultimo output completo:\n{last_full_output}")
            return {
                "success": False,
                "message": f"Backup VM {vm_id} fallito con tutti i mode (snapshot, suspend, stop). Ultimo errore: {last_error[:300] if last_error else 'Nessun dettaglio'}",
                "error": last_error or "Tutti i mode di backup falliti (snapshot, suspend, stop)",
                "phase": "backup",
                "backup_modes_tried": backup_modes,
                "source_host": source_hostname,
                "backup_dir": backup_dir,
                "full_output": last_full_output
            }
        
        # Trova il file di backup creato
        # vzdump crea file tipo: vzdump-qemu-100-2025_12_08-12_30_00.vma.zst o .tar.zst
        find_backup_cmd = f"ls -t {backup_dir}/vzdump-{vm_type}-{vm_id}-*.vma.zst {backup_dir}/vzdump-{vm_type}-{vm_id}-*.tar.zst 2>/dev/null | head -1"
        find_result = await ssh_service.execute(
            hostname=source_hostname,
            command=find_backup_cmd,
            port=source_port,
            username=source_user,
            key_path=source_key,
            timeout=30
        )
        
        if not find_result.success or not find_result.stdout.strip():
            logger.error(f"[MIGRATION] FASE: RICERCA FILE BACKUP FALLITA")
            logger.error(f"[MIGRATION] VM: {vm_id} ({vm_type}) | Host: {source_hostname}")
            logger.error(f"[MIGRATION] Directory cercata: {backup_dir}")
            logger.error(f"[MIGRATION] Pattern cercato: vzdump-{vm_type}-{vm_id}-*.vma.zst o .tar.zst")
            logger.error(f"[MIGRATION] Comando: {find_backup_cmd}")
            logger.error(f"[MIGRATION] Stdout: {find_result.stdout}")
            logger.error(f"[MIGRATION] Stderr: {find_result.stderr}")
            return {
                "success": False,
                "message": f"File di backup non trovato in {backup_dir}. Il backup potrebbe essere stato creato in una directory diversa o con un nome inatteso.",
                "error": f"Backup creato ma file non trovato in {backup_dir}",
                "phase": "find_backup_file",
                "backup_dir": backup_dir,
                "search_pattern": f"vzdump-{vm_type}-{vm_id}-*.vma.zst",
                "source_host": source_hostname,
                "command": find_backup_cmd
            }
        
        backup_file = find_result.stdout.strip()
        
        # Ottieni dimensione del backup
        size_cmd = f"stat -c%s {backup_file} 2>/dev/null || stat -f%z {backup_file} 2>/dev/null"
        size_result = await ssh_service.execute(
            hostname=source_hostname,
            command=size_cmd,
            port=source_port,
            username=source_user,
            key_path=source_key,
            timeout=30
        )
        
        backup_size_bytes = 0
        backup_size_human = "N/A"
        if size_result.success and size_result.stdout.strip().isdigit():
            backup_size_bytes = int(size_result.stdout.strip())
            # Converti in formato leggibile
            if backup_size_bytes >= 1024**3:
                backup_size_human = f"{backup_size_bytes / (1024**3):.2f} GB"
            elif backup_size_bytes >= 1024**2:
                backup_size_human = f"{backup_size_bytes / (1024**2):.2f} MB"
            elif backup_size_bytes >= 1024:
                backup_size_human = f"{backup_size_bytes / 1024:.2f} KB"
            else:
                backup_size_human = f"{backup_size_bytes} B"
        
        logger.info(f"Backup VM {vm_id} creato: {backup_file} ({backup_size_human})")
        
        # Trasferisci backup sul nodo destinazione usando rsync con progress
        logger.info(f"[MIGRATION] FASE: TRASFERIMENTO BACKUP")
        logger.info(f"[MIGRATION] File: {backup_file} ({backup_size_human})")
        logger.info(f"[MIGRATION] Destinazione: {dest_hostname}:/var/tmp/")
        
        # Usa rsync per avere progress e migliore gestione errori
        # --info=progress2 mostra progresso globale
        rsync_cmd = f"rsync -avz --progress --info=progress2 -e 'ssh -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {source_key} -p {dest_port}' {backup_file} {dest_user}@{dest_hostname}:/var/tmp/"
        
        # Esegui rsync e monitora il progresso
        transfer_start = time.time()
        transfer_result = await ssh_service.execute(
            hostname=source_hostname,
            command=rsync_cmd,
            port=source_port,
            username=source_user,
            key_path=source_key,
            timeout=7200  # 2 ore per file grandi
        )
        transfer_duration = time.time() - transfer_start
        
        # Calcola velocità trasferimento
        if backup_size_bytes > 0 and transfer_duration > 0:
            speed_mbps = (backup_size_bytes / (1024**2)) / transfer_duration
            logger.info(f"Trasferimento completato: {backup_size_human} in {transfer_duration:.1f}s ({speed_mbps:.2f} MB/s)")
        
        # Fallback a scp se rsync fallisce
        if not transfer_result.success:
            logger.warning(f"rsync fallito, provo con scp: {transfer_result.stderr}")
            scp_cmd = f"scp -o StrictHostKeyChecking=no -o UserKnownHostsFile=/dev/null -i {source_key} -P {dest_port} {backup_file} {dest_user}@{dest_hostname}:/var/tmp/"
            transfer_result = await ssh_service.execute(
                hostname=source_hostname,
                command=scp_cmd,
                port=source_port,
                username=source_user,
                key_path=source_key,
                timeout=7200
            )
        
        if not transfer_result.success:
            # Cleanup backup locale
            await ssh_service.execute(
                hostname=source_hostname,
                command=f"rm -f {backup_file}",
                port=source_port,
                username=source_user,
                key_path=source_key
            )
            full_output = f"STDOUT:\n{transfer_result.stdout}\n\nSTDERR:\n{transfer_result.stderr}"
            logger.error(f"[MIGRATION] FASE: TRASFERIMENTO FALLITO")
            logger.error(f"[MIGRATION] VM: {vm_id} | Source: {source_hostname} -> Dest: {dest_hostname}")
            logger.error(f"[MIGRATION] Exit code: {transfer_result.exit_code}")
            logger.error(f"[MIGRATION] Output completo:\n{full_output}")
            return {
                "success": False,
                "message": f"Errore trasferimento backup verso {dest_hostname}: {transfer_result.stderr[:500] if transfer_result.stderr else 'Nessun output stderr'}",
                "error": transfer_result.stderr or "Trasferimento fallito senza dettagli",
                "phase": "transfer",
                "exit_code": transfer_result.exit_code,
                "full_output": full_output,
                "source_host": source_hostname,
                "dest_host": dest_hostname,
                "backup_file": backup_file
            }
        
        remote_backup = f"/var/tmp/{backup_file.split('/')[-1]}"
        
        # Restore sul nodo destinazione
        # Determina storage destinazione (deve supportare 'images')
        dest_storage = None
        if hw_config and "storage" in hw_config:
            for disk, new_storage in hw_config["storage"].items():
                if ":" in new_storage:
                    dest_storage = new_storage.split(":")[0]
                    break
                elif new_storage:
                    dest_storage = new_storage
                    break
        
        # Se non specificato, trova uno storage che supporta 'images'
        if not dest_storage:
            find_storage_cmd = "pvesm status --content images 2>/dev/null | awk 'NR>1 {print $1}' | head -1"
            storage_result = await ssh_service.execute(
                hostname=dest_hostname,
                command=find_storage_cmd,
                port=dest_port,
                username=dest_user,
                key_path=dest_key,
                timeout=30
            )
            if storage_result.success and storage_result.stdout.strip():
                dest_storage = storage_result.stdout.strip()
            else:
                # Fallback comuni
                for fallback in ["local-lvm", "local-zfs", "zfs", "lvm"]:
                    check_cmd = f"pvesm status | grep -q '^{fallback}' && echo 'found'"
                    check_result = await ssh_service.execute(
                        hostname=dest_hostname,
                        command=check_cmd,
                        port=dest_port,
                        username=dest_user,
                        key_path=dest_key,
                        timeout=10
                    )
                    if check_result.success and "found" in check_result.stdout:
                        dest_storage = fallback
                        break
                
                if not dest_storage:
                    return {
                        "success": False,
                        "message": "Nessuno storage trovato che supporta 'images' sul nodo destinazione",
                        "error": "Storage not found"
                    }
        
        logger.info(f"[MIGRATION] FASE: RESTORE")
        logger.info(f"[MIGRATION] VM: {target_vmid} ({vm_type}) | Host: {dest_hostname}")
        logger.info(f"[MIGRATION] Storage destinazione: {dest_storage}")
        logger.info(f"[MIGRATION] File backup: {remote_backup}")
        
        # pct restore ha ordine parametri diverso: pct restore <vmid> <backup> --storage <storage>
        if vm_type == "lxc":
            restore_cmd = f"pct restore {target_vmid} {remote_backup} --storage {dest_storage}"
        else:
            restore_cmd = f"qmrestore {remote_backup} {target_vmid} --storage {dest_storage}"
        restore_result = await ssh_service.execute(
            hostname=dest_hostname,
            command=restore_cmd,
            port=dest_port,
            username=dest_user,
            key_path=dest_key,
            timeout=3600
        )
        
        # Cleanup backup remoto
        await ssh_service.execute(
            hostname=dest_hostname,
            command=f"rm -f {remote_backup}",
            port=dest_port,
            username=dest_user,
            key_path=dest_key
        )
        
        # Cleanup backup locale
        await ssh_service.execute(
            hostname=source_hostname,
            command=f"rm -f {backup_file}",
            port=source_port,
            username=source_user,
            key_path=source_key
        )
        
        if not restore_result.success:
            full_output = f"STDOUT:\n{restore_result.stdout}\n\nSTDERR:\n{restore_result.stderr}"
            logger.error(f"[MIGRATION] FASE: RESTORE FALLITO")
            logger.error(f"[MIGRATION] VM: {target_vmid} ({vm_type}) | Host destinazione: {dest_hostname}")
            logger.error(f"[MIGRATION] Storage: {dest_storage}")
            logger.error(f"[MIGRATION] File backup: {remote_backup}")
            logger.error(f"[MIGRATION] Comando: {restore_cmd}")
            logger.error(f"[MIGRATION] Exit code: {restore_result.exit_code}")
            logger.error(f"[MIGRATION] Output completo:\n{full_output}")
            
            # Estrai errori specifici
            error_lines = [line for line in full_output.split('\n') if 'ERROR' in line or 'error' in line.lower()]
            specific_error = '\n'.join(error_lines) if error_lines else restore_result.stderr
            
            return {
                "success": False,
                "message": f"Restore VM {target_vmid} fallito su {dest_hostname}: {specific_error[:500] if specific_error else 'Nessun dettaglio'}",
                "error": specific_error,
                "phase": "restore",
                "exit_code": restore_result.exit_code,
                "command": restore_cmd,
                "dest_host": dest_hostname,
                "dest_storage": dest_storage,
                "backup_file": remote_backup,
                "full_output": full_output
            }
        
        # Estrai dimensione trasferita
        transferred = "0B"
        if "transferred" in restore_result.stdout.lower() or "MiB" in restore_result.stdout:
            match = re.search(r'(\d+\.?\d*)\s*(GiB|MiB|KiB|GB|MB|KB)', restore_result.stdout, re.IGNORECASE)
            if match:
                transferred = f"{match.group(1)} {match.group(2)}"
        
        # Applica riconfigurazione hardware
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
        
        # Gestione snapshot - esegui sempre il pruning se keep_snapshots > 0
        if keep_snapshots > 0:
            logger.info(f"[MIGRATION] Esecuzione pruning snapshot (keep={keep_snapshots})")
            await self._prune_snapshots(
                hostname=source_hostname,
                vm_id=vm_id,
                vm_type=vm_type,
                keep=keep_snapshots,
                port=source_port,
                username=source_user,
                key_path=source_key
            )
        else:
            logger.info(f"[MIGRATION] Pruning snapshot saltato (keep_snapshots={keep_snapshots})")
        
        # Avvia VM se richiesto
        if start_after:
            start_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} start {target_vmid}"
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
        
        # Usa backup_size_human se transferred non è stato calcolato
        final_transferred = backup_size_human if backup_size_human != "N/A" else transferred
        
        logger.info(f"[MIGRATION] ========== COPIA COMPLETATA ==========")
        logger.info(f"[MIGRATION] VM: {vm_id} -> {target_vmid} su {dest_hostname}")
        logger.info(f"[MIGRATION] Durata: {duration}s | Trasferiti: {final_transferred}")
        logger.info(f"[MIGRATION] Backup mode usato: {used_mode}")
        
        return {
            "success": True,
            "message": f"VM {vm_id} copiata con successo su {dest_hostname} (VMID: {target_vmid}) - Trasferiti: {final_transferred}",
            "vm_id": target_vmid,
            "duration": duration,
            "transferred": final_transferred,
            "backup_size": backup_size_human,
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
        logger.info(f"=== Applicando hw_config a VM {vm_id} su {hostname} ===")
        logger.info(f"hw_config ricevuto: {json.dumps(hw_config, default=str)}")
        
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
                # Prima leggi la configurazione attuale della scheda di rete
                get_net_cmd = f"{cmd} config {vm_id} | grep '^{net_iface}:'"
                get_net_result = await ssh_service.execute(
                    hostname=hostname,
                    command=get_net_cmd,
                    port=port,
                    username=username,
                    key_path=key_path,
                    timeout=30
                )
                
                if not get_net_result.success or not get_net_result.stdout.strip():
                    logger.warning(f"Interfaccia {net_iface} non trovata sulla VM {vm_id}")
                    continue
                
                # Estrai la config attuale (es: "net0: virtio=AA:BB:CC:DD:EE:FF,bridge=vmbr0,firewall=1")
                current_config = get_net_result.stdout.strip().split(":", 1)[1].strip()
                logger.info(f"Config attuale {net_iface}: {current_config}")
                
                # Determina il nuovo bridge
                new_bridge = None
                if isinstance(net_config, str):
                    # Rimuovi eventuali prefissi "bridge=" multipli
                    clean_config = net_config
                    while clean_config.startswith("bridge="):
                        clean_config = clean_config[7:]  # Rimuovi "bridge="
                    
                    # Cerca bridge= nel valore pulito o usa il valore direttamente
                    bridge_match = re.search(r'bridge=([^,\s]+)', clean_config)
                    if bridge_match:
                        new_bridge = bridge_match.group(1)
                    else:
                        # Assume sia solo il nome del bridge
                        new_bridge = clean_config.strip()
                elif isinstance(net_config, dict) and "bridge" in net_config:
                    new_bridge = net_config["bridge"]
                    # Rimuovi eventuali prefissi "bridge=" dal valore dict
                    while new_bridge.startswith("bridge="):
                        new_bridge = new_bridge[7:]
                
                if not new_bridge:
                    logger.warning(f"Bridge non specificato per {net_iface}")
                    continue
                
                # Assicurati che new_bridge sia solo il nome del bridge (senza prefissi)
                new_bridge = new_bridge.strip()
                logger.debug(f"Bridge pulito per {net_iface}: {new_bridge}")
                
                # Sostituisci il bridge nella config esistente
                new_config = re.sub(r'bridge=[^,\s]+', f'bridge={new_bridge}', current_config)
                
                # Se non c'era un bridge nella config, aggiungilo
                if 'bridge=' not in new_config:
                    new_config = f"{new_config},bridge={new_bridge}"
                
                logger.info(f"Nuova config {net_iface}: {new_config}")
                
                # Applica la nuova configurazione
                net_cmd = f"{cmd} set {vm_id} --{net_iface} {new_config}"
                net_result = await ssh_service.execute(
                    hostname=hostname,
                    command=net_cmd,
                    port=port,
                    username=username,
                    key_path=key_path,
                    timeout=30
                )
                
                if net_result.success:
                    changes.append(f"{net_iface}: bridge={new_bridge}")
                    logger.info(f"Bridge {net_iface} cambiato a {new_bridge}")
                else:
                    logger.error(f"Errore cambio bridge {net_iface}: {net_result.stderr}")
        
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
        """Mantiene solo gli ultimi N snapshot di migrazione, elimina i più vecchi"""
        cmd = "qm" if vm_type == "qemu" else "pct"
        
        logger.info(f"[MIGRATION] FASE: PRUNING SNAPSHOT")
        logger.info(f"[MIGRATION] VM: {vm_id} ({vm_type}) | Host: {hostname} | Keep: {keep}")
        
        # Lista snapshot - usa comando raw senza grep per parsare correttamente
        list_cmd = f"{cmd} listsnapshot {vm_id} 2>/dev/null"
        list_result = await ssh_service.execute(
            hostname=hostname,
            command=list_cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=30
        )
        
        if not list_result.success:
            logger.warning(f"[MIGRATION] Impossibile listare snapshot VM {vm_id}: {list_result.stderr}")
            return
        
        logger.debug(f"[MIGRATION] Output listsnapshot:\n{list_result.stdout}")
        
        # Estrai nomi snapshot (escludi 'current')
        # Formato output: "`-> snap_name   description" oppure "    `-> snap_name   description"
        # oppure semplicemente "snap_name   description"
        snapshots = []
        migration_snapshots = []  # Solo snapshot di migrazione (migration-*)
        
        for line in list_result.stdout.strip().split('\n'):
            line = line.strip()
            if not line:
                continue
            
            # Salta la riga 'current'
            if line.lower().startswith('current'):
                continue
            
            # Rimuovi prefisso `-> se presente
            if '`->' in line:
                line = line.split('`->')[-1].strip()
            
            # Estrai nome snapshot (prima parola)
            parts = line.split()
            if parts:
                snap_name = parts[0]
                # Salta 'current' ovunque appaia
                if snap_name.lower() == 'current':
                    continue
                snapshots.append(snap_name)
                # Identifica snapshot di migrazione
                if snap_name.startswith('migration-'):
                    migration_snapshots.append(snap_name)
        
        logger.info(f"[MIGRATION] Trovati {len(snapshots)} snapshot totali, {len(migration_snapshots)} di migrazione")
        logger.debug(f"[MIGRATION] Tutti gli snapshot: {snapshots}")
        logger.debug(f"[MIGRATION] Snapshot migrazione: {migration_snapshots}")
        
        # Ordina snapshot di migrazione per timestamp (formato: migration-TIMESTAMP)
        # Gli snapshot più recenti hanno timestamp maggiore
        def get_timestamp(snap_name):
            try:
                # Estrai timestamp da "migration-1234567890"
                if snap_name.startswith('migration-'):
                    ts = snap_name.replace('migration-', '')
                    return int(ts)
            except (ValueError, IndexError):
                pass
            return 0
        
        migration_snapshots.sort(key=get_timestamp, reverse=True)  # Più recenti prima
        
        # Elimina snapshot di migrazione oltre il limite
        to_delete = migration_snapshots[keep:]
        
        if not to_delete:
            logger.info(f"[MIGRATION] Nessuno snapshot da eliminare (trovati {len(migration_snapshots)}, keep {keep})")
            return
        
        logger.info(f"[MIGRATION] Eliminazione {len(to_delete)} snapshot: {to_delete}")
        
        deleted_count = 0
        failed_count = 0
        
        for snap_name in to_delete:
            del_cmd = f"{cmd} delsnapshot {vm_id} {snap_name}"
            logger.info(f"[MIGRATION] Eliminazione snapshot: {snap_name}")
            
            del_result = await ssh_service.execute(
                hostname=hostname,
                command=del_cmd,
                port=port,
                username=username,
                key_path=key_path,
                timeout=300
            )
            
            if del_result.success:
                deleted_count += 1
                logger.info(f"[MIGRATION] ✓ Snapshot {snap_name} eliminato")
            else:
                failed_count += 1
                logger.error(f"[MIGRATION] ✗ Errore eliminazione snapshot {snap_name}")
                logger.error(f"[MIGRATION] Comando: {del_cmd}")
                logger.error(f"[MIGRATION] Exit code: {del_result.exit_code}")
                logger.error(f"[MIGRATION] Stderr: {del_result.stderr}")
        
        logger.info(f"[MIGRATION] Pruning completato: {deleted_count} eliminati, {failed_count} falliti")


migration_service = MigrationService()

