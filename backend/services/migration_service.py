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
            logger.error(f"VM {vm_id} non trovata su {source_hostname}: {check_result.stderr}")
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
        
        logger.info(f"Eseguendo: {migrate_cmd}")
        
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
            full_output = migrate_result.stdout + "\n" + migrate_result.stderr
            logger.error(f"Migrazione VM {vm_id} fallita")
            logger.error(f"Exit code: {migrate_result.exit_code}")
            logger.error(f"Output:\n{full_output}")
            
            # Estrai errori specifici
            error_lines = [line for line in full_output.split('\n') if 'ERROR' in line or 'error' in line.lower()]
            specific_error = '\n'.join(error_lines) if error_lines else migrate_result.stderr
            
            return {
                "success": False,
                "message": f"Errore durante migrazione VM: {specific_error}",
                "error": specific_error,
                "stdout": migrate_result.stdout,
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
                logger.error(f"Impossibile eliminare VM esistente {target_vmid} su {dest_hostname}")
                logger.error(f"Exit code: {destroy_result.exit_code}")
                logger.error(f"Stderr: {destroy_result.stderr}")
                return {
                    "success": False,
                    "message": f"Impossibile eliminare VM esistente {target_vmid}: {destroy_result.stderr}",
                    "error": destroy_result.stderr
                }
            
            logger.info(f"VM {target_vmid} eliminata con successo")
        
        # Crea snapshot se richiesto
        snapshot_name = None
        if create_snapshot:
            snapshot_name = f"migration-{int(time.time())}"
            snap_cmd = f"{'qm' if vm_type == 'qemu' else 'pct'} snapshot {vm_id} {snapshot_name} --description 'Pre-migration snapshot'"
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
        for backup_mode in backup_modes:
            logger.info(f"Tentativo backup VM {vm_id} con mode={backup_mode}")
            backup_cmd = f"vzdump {vm_id} --compress zstd --dumpdir {backup_dir} --mode {backup_mode} --remove 0"
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
                logger.info(f"Backup VM {vm_id} completato con mode={backup_mode}")
                break
            
            # Controlla se l'errore è recuperabile (prova prossimo mode)
            full_output = (backup_result.stdout + "\n" + backup_result.stderr).lower()
            is_recoverable = any(err in full_output for err in recoverable_errors)
            
            if is_recoverable:
                logger.warning(f"Mode {backup_mode} fallito per errore recuperabile, provo alternativa...")
                logger.warning(f"Errore: {backup_result.stderr[:200]}")
                last_error = backup_result.stderr
                continue
            else:
                # Errore non recuperabile, fallisci subito
                full_output = backup_result.stdout + "\n" + backup_result.stderr
                logger.error(f"Backup VM {vm_id} fallito (mode={backup_mode}) - errore non recuperabile")
                logger.error(f"Comando: {backup_cmd}")
                logger.error(f"Exit code: {backup_result.exit_code}")
                logger.error(f"Output completo:\n{full_output}")
                
                # Estrai errori specifici dall'output
                error_lines = [line for line in full_output.split('\n') if 'ERROR' in line or 'error' in line.lower()]
                specific_error = '\n'.join(error_lines) if error_lines else backup_result.stderr
                
                return {
                    "success": False,
                    "message": f"Errore creazione backup (mode={backup_mode}): {specific_error}",
                    "error": specific_error,
                    "full_output": full_output
                }
        
        if not backup_result or not backup_result.success:
            logger.error(f"Backup VM {vm_id} fallito con tutti i mode (snapshot, suspend, stop)")
            logger.error(f"Ultimo errore: {last_error}")
            return {
                "success": False,
                "message": f"Errore creazione backup: tutti i mode falliti. Ultimo errore: {last_error}",
                "error": last_error or "Tutti i mode di backup falliti (snapshot, suspend, stop)"
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
            logger.error(f"File di backup non trovato per VM {vm_id}")
            logger.error(f"Comando ricerca: {find_backup_cmd}")
            logger.error(f"Stdout: {find_result.stdout}")
            logger.error(f"Stderr: {find_result.stderr}")
            return {
                "success": False,
                "message": "File di backup non trovato",
                "error": f"Backup creato ma file non trovato in {backup_dir}"
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
        logger.info(f"Inizio trasferimento {backup_size_human} verso {dest_hostname}...")
        
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
            logger.error(f"Trasferimento backup fallito per VM {vm_id}")
            logger.error(f"Comando fallito con exit code: {transfer_result.exit_code}")
            logger.error(f"Stderr: {transfer_result.stderr}")
            logger.error(f"Stdout: {transfer_result.stdout}")
            return {
                "success": False,
                "message": f"Errore trasferimento backup: {scp_result.stderr}",
                "error": scp_result.stderr
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
        
        logger.info(f"Usando storage destinazione: {dest_storage}")
        
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
            full_output = restore_result.stdout + "\n" + restore_result.stderr
            logger.error(f"Restore VM {vm_id} fallito su {dest_hostname}")
            logger.error(f"Comando: {restore_cmd}")
            logger.error(f"Exit code: {restore_result.exit_code}")
            logger.error(f"Output:\n{full_output}")
            
            # Estrai errori specifici
            error_lines = [line for line in full_output.split('\n') if 'ERROR' in line or 'error' in line.lower()]
            specific_error = '\n'.join(error_lines) if error_lines else restore_result.stderr
            
            return {
                "success": False,
                "message": f"Errore restore: {specific_error}",
                "error": specific_error,
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
        
        # Gestione snapshot
        if snapshot_name and keep_snapshots > 0:
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

