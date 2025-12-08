"""
Scheduler Service - Gestione job schedulati
Con supporto notifiche e riepilogo giornaliero
"""

import asyncio
from datetime import datetime, time
from typing import Dict, Optional, Callable
import logging
from croniter import croniter
from sqlalchemy.orm import Session

from database import SessionLocal, SyncJob, JobLog, Node, NotificationConfig, SystemConfig, HostBackupJob, MigrationJob
from services.syncoid_service import syncoid_service
from services.proxmox_service import proxmox_service
from services.notification_service import notification_service
from services.host_backup_service import host_backup_service

logger = logging.getLogger(__name__)


class SchedulerService:
    """Servizio per scheduling dei job di sincronizzazione"""
    
    def __init__(self):
        self._running = False
        self._task: Optional[asyncio.Task] = None
        self._jobs: Dict[int, datetime] = {}  # job_id -> next_run
        self._last_daily_summary: Optional[datetime] = None
        self._daily_summary_hour: int = 8  # Ora predefinita: 08:00 UTC
        self._daily_summary_enabled: bool = True
    
    async def start(self):
        """Avvia lo scheduler"""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Scheduler avviato")
        
        # Carica configurazione orario riepilogo
        self._load_daily_summary_config()
    
    async def stop(self):
        """Ferma lo scheduler"""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Scheduler fermato")
    
    def _load_daily_summary_config(self):
        """Carica la configurazione dell'orario del riepilogo giornaliero"""
        db = SessionLocal()
        try:
            # Orario
            hour_config = db.query(SystemConfig).filter(
                SystemConfig.key == "daily_summary_hour"
            ).first()
            if hour_config and hour_config.value:
                try:
                    self._daily_summary_hour = int(hour_config.value)
                except ValueError:
                    pass
            
            # Abilitato/Disabilitato
            enabled_config = db.query(SystemConfig).filter(
                SystemConfig.key == "daily_summary_enabled"
            ).first()
            self._daily_summary_enabled = True
            if enabled_config and enabled_config.value:
                self._daily_summary_enabled = enabled_config.value.lower() in ("true", "1", "yes")
            
            if self._daily_summary_enabled:
                logger.info(f"Riepilogo giornaliero schedulato alle ore {self._daily_summary_hour}:00 UTC")
            else:
                logger.info("Riepilogo giornaliero disabilitato")
        finally:
            db.close()
    
    async def _scheduler_loop(self):
        """Loop principale dello scheduler"""
        while self._running:
            try:
                await self._check_and_run_jobs()
                await self._check_daily_summary()
                await asyncio.sleep(60)  # Check ogni minuto
            except Exception as e:
                logger.error(f"Errore nello scheduler: {e}")
                await asyncio.sleep(60)
    
    async def _check_daily_summary(self):
        """Verifica se è ora di inviare il riepilogo giornaliero"""
        # Verifica se abilitato
        if not self._daily_summary_enabled:
            return
        
        now = datetime.utcnow()
        current_hour = now.hour
        
        # Verifica se è l'ora giusta e se non è già stato inviato oggi
        if current_hour == self._daily_summary_hour:
            # Controlla se già inviato oggi
            if self._last_daily_summary:
                if self._last_daily_summary.date() == now.date():
                    return  # Già inviato oggi
            
            # Ricarica configurazione (potrebbe essere cambiata)
            self._load_daily_summary_config()
            if not self._daily_summary_enabled:
                return
            
            # Invia riepilogo
            logger.info("Invio riepilogo giornaliero...")
            try:
                result = await notification_service.send_daily_summary()
                if result.get("sent"):
                    logger.info(f"Riepilogo giornaliero inviato: {result.get('channels', {})}")
                else:
                    logger.debug(f"Riepilogo non inviato: {result.get('reason')}")
                self._last_daily_summary = now
            except Exception as e:
                logger.error(f"Errore invio riepilogo giornaliero: {e}")
    
    async def _check_and_run_jobs(self):
        """Verifica e esegue i job schedulati"""
        db = SessionLocal()
        try:
            now = datetime.utcnow()
            
            # === SYNC JOBS ===
            sync_jobs = db.query(SyncJob).filter(
                SyncJob.is_active == True,
                SyncJob.schedule.isnot(None),
                SyncJob.schedule != ""
            ).all()
            
            for job in sync_jobs:
                try:
                    job_key = f"sync_{job.id}"
                    if job_key not in self._jobs:
                        cron = croniter(job.schedule, job.last_run or now)
                        self._jobs[job_key] = cron.get_next(datetime)
                    
                    next_run = self._jobs[job_key]
                    
                    if now >= next_run:
                        logger.info(f"Esecuzione SyncJob schedulato: {job.name} (ID: {job.id})")
                        asyncio.create_task(self._execute_job(job.id))
                        cron = croniter(job.schedule, now)
                        self._jobs[job_key] = cron.get_next(datetime)
                        
                except Exception as e:
                    logger.error(f"Errore scheduling SyncJob {job.id}: {e}")
            
            # === HOST BACKUP JOBS ===
            host_backup_jobs = db.query(HostBackupJob).filter(
                HostBackupJob.is_active == True,
                HostBackupJob.schedule.isnot(None),
                HostBackupJob.schedule != ""
            ).all()
            
            for job in host_backup_jobs:
                try:
                    job_key = f"host_backup_{job.id}"
                    if job_key not in self._jobs:
                        cron = croniter(job.schedule, job.last_run or now)
                        self._jobs[job_key] = cron.get_next(datetime)
                    
                    next_run = self._jobs[job_key]
                    
                    if now >= next_run:
                        logger.info(f"Esecuzione HostBackupJob schedulato: {job.name} (ID: {job.id})")
                        asyncio.create_task(self._execute_host_backup_job(job.id))
                        cron = croniter(job.schedule, now)
                        self._jobs[job_key] = cron.get_next(datetime)
                        
                except Exception as e:
                    logger.error(f"Errore scheduling HostBackupJob {job.id}: {e}")
            
            # === MIGRATION JOBS ===
            migration_jobs = db.query(MigrationJob).filter(
                MigrationJob.is_active == True,
                MigrationJob.schedule.isnot(None),
                MigrationJob.schedule != ""
            ).all()
            
            for job in migration_jobs:
                try:
                    job_key = f"migration_{job.id}"
                    if job_key not in self._jobs:
                        cron = croniter(job.schedule, job.last_run or now)
                        self._jobs[job_key] = cron.get_next(datetime)
                    
                    next_run = self._jobs[job_key]
                    
                    if now >= next_run:
                        logger.info(f"Esecuzione MigrationJob schedulato: {job.name} (ID: {job.id})")
                        asyncio.create_task(self._execute_migration_job(job.id))
                        cron = croniter(job.schedule, now)
                        self._jobs[job_key] = cron.get_next(datetime)
                        
                except Exception as e:
                    logger.error(f"Errore scheduling MigrationJob {job.id}: {e}")
                    
        finally:
            db.close()
    
    async def _execute_job(self, job_id: int):
        """Esegue un job di sincronizzazione"""
        db = SessionLocal()
        log_entry = None
        
        try:
            job = db.query(SyncJob).filter(SyncJob.id == job_id).first()
            if not job:
                logger.error(f"Job {job_id} non trovato")
                return
            
            source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
            dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
            
            if not source_node or not dest_node:
                logger.error(f"Nodi non trovati per job {job_id}")
                return
            
            # Crea log entry
            log_entry = JobLog(
                job_type="sync",
                job_id=job_id,
                node_name=f"{source_node.name} -> {dest_node.name}",
                dataset=f"{job.source_dataset} -> {job.dest_dataset}",
                status="started",
                message=f"Sincronizzazione avviata"
            )
            db.add(log_entry)
            db.commit()
            
            # Aggiorna stato job
            job.last_status = "running"
            db.commit()
            
            # Determina da dove eseguire (sorgente)
            executor_host = source_node.hostname
            
            # Esegui sync
            result = await syncoid_service.run_sync(
                executor_host=executor_host,
                source_host=None,  # Locale all'executor
                source_dataset=job.source_dataset,
                dest_host=dest_node.hostname,
                dest_dataset=job.dest_dataset,
                dest_user=dest_node.ssh_user,
                dest_port=dest_node.ssh_port,
                dest_key=dest_node.ssh_key_path,
                executor_port=source_node.ssh_port,
                executor_user=source_node.ssh_user,
                executor_key=source_node.ssh_key_path,
                recursive=job.recursive,
                compress=job.compress or "lz4",
                mbuffer_size=job.mbuffer_size or "128M",
                no_sync_snap=job.no_sync_snap,
                force_delete=job.force_delete,
                extra_args=job.extra_args or ""
            )
            
            # Aggiorna job
            job.last_run = datetime.utcnow()
            job.last_duration = result["duration"]
            job.last_transferred = result.get("transferred")
            job.run_count += 1
            
            if result["success"]:
                job.last_status = "success"
                log_entry.status = "success"
                log_entry.message = "Sincronizzazione completata"
                
                # Registra VM se richiesto
                if job.register_vm and job.vm_id:
                    await self._register_vm_after_sync(db, job, source_node, dest_node, log_entry)
            else:
                job.last_status = "failed"
                job.error_count += 1
                log_entry.status = "failed"
                log_entry.message = "Sincronizzazione fallita"
                log_entry.error = result.get("error", "")
            
            log_entry.output = result.get("output", "")
            log_entry.duration = result["duration"]
            log_entry.transferred = result.get("transferred")
            log_entry.completed_at = datetime.utcnow()
            
            db.commit()
            
            # Invia notifica job completato
            # Rispetta notify_mode del job: daily, always, failure, never
            try:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="success" if result["success"] else "failed",
                    source=f"{source_node.name}:{job.source_dataset}",
                    destination=f"{dest_node.name}:{job.dest_dataset}",
                    duration=result["duration"],
                    error=result.get("error") if not result["success"] else None,
                    details=f"Trasferito: {result.get('transferred', 'N/A')}" if result["success"] else None,
                    job_id=job_id,
                    is_scheduled=True,
                    notify_mode=job.notify_mode or "daily"
                )
            except Exception as notify_err:
                logger.warning(f"Errore invio notifica per job {job_id}: {notify_err}")
            
        except Exception as e:
            logger.error(f"Errore esecuzione job {job_id}: {e}")
            if log_entry:
                log_entry.status = "failed"
                log_entry.error = str(e)
                log_entry.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
    
    async def _execute_host_backup_job(self, job_id: int):
        """Esegue un job di host backup schedulato"""
        db = SessionLocal()
        log_entry = None
        
        try:
            job = db.query(HostBackupJob).filter(HostBackupJob.id == job_id).first()
            if not job:
                logger.error(f"HostBackupJob {job_id} non trovato")
                return
            
            node = db.query(Node).filter(Node.id == job.node_id).first()
            if not node:
                logger.error(f"Nodo non trovato per HostBackupJob {job_id}")
                return
            
            # Rileva tipo host
            host_type = await host_backup_service.detect_host_type(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            
            # Crea log entry
            log_entry = JobLog(
                job_type="host_backup",
                job_id=job_id,
                node_name=node.name,
                dataset=f"config-{host_type}",
                status="running",
                message=f"Backup schedulato configurazione {host_type.upper()} su {node.name}"
            )
            db.add(log_entry)
            
            job.current_status = "running"
            job.run_count += 1
            db.commit()
            
            start_time = datetime.utcnow()
            
            # Esegui backup
            result = await host_backup_service.create_host_backup(
                hostname=node.hostname,
                host_type=host_type,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path,
                dest_path=job.dest_path,
                compress=job.compress,
                encrypt=job.encrypt,
                encrypt_password=job.encrypt_password
            )
            
            end_time = datetime.utcnow()
            duration = int((end_time - start_time).total_seconds())
            
            if result['success']:
                # Applica retention
                await host_backup_service.apply_retention(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path,
                    backup_path=job.dest_path,
                    keep_last=job.keep_last
                )
                
                job.current_status = "completed"
                job.last_status = "success"
                job.last_backup_time = end_time
                job.last_backup_file = result.get('backup_file')
                job.last_backup_size = result.get('size', 0)
                job.last_run = end_time
                job.last_duration = duration
                job.last_error = None
                
                log_entry.status = "success"
                log_entry.message = f"Backup {host_type.upper()} completato: {result['backup_name']} ({result['size_human']})"
                log_entry.completed_at = end_time
                log_entry.duration = duration
                
                logger.info(f"HostBackupJob {job_id} completato: {result['backup_name']}")
            else:
                job.current_status = "failed"
                job.last_status = "failed"
                job.last_run = end_time
                job.last_duration = duration
                job.last_error = result.get('error')
                job.error_count += 1
                
                log_entry.status = "failed"
                log_entry.error = result.get('error')
                log_entry.message = f"Backup {host_type.upper()} fallito"
                log_entry.completed_at = end_time
                log_entry.duration = duration
                
                logger.error(f"HostBackupJob {job_id} fallito: {result.get('error')}")
            
            db.commit()
            
            # Invia notifica - il notification_service gestisce notify_mode internamente
            try:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status=job.last_status,
                    source=node.name,
                    destination=job.dest_path,
                    duration=duration,
                    error=job.last_error if job.last_status == 'failed' else None,
                    details=f"File: {result.get('backup_name', 'N/A')}, Size: {result.get('size_human', 'N/A')}",
                    job_id=job_id,
                    is_scheduled=True,
                    notify_mode=job.notify_mode or "daily"
                )
            except Exception as notify_err:
                logger.warning(f"Errore invio notifica per HostBackupJob {job_id}: {notify_err}")
            
        except Exception as e:
            logger.error(f"Errore esecuzione HostBackupJob {job_id}: {e}")
            if log_entry:
                log_entry.status = "failed"
                log_entry.error = str(e)
                log_entry.completed_at = datetime.utcnow()
                db.commit()
        finally:
            db.close()
    
    async def _execute_migration_job(self, job_id: int):
        """Esegue un job di migrazione"""
        from routers.migration_jobs import execute_migration_job_task
        
        # Usa la funzione già definita nel router
        await execute_migration_job_task(job_id, triggered_by=None)
    
    async def _register_vm_after_sync(
        self,
        db: Session,
        job: SyncJob,
        source_node: Node,
        dest_node: Node,
        log_entry: JobLog
    ):
        """Registra una VM sul nodo destinazione dopo la sync"""
        try:
            # Ottieni config dalla sorgente
            success, config = await proxmox_service.get_vm_config_file(
                hostname=source_node.hostname,
                vmid=job.vm_id,
                vm_type=job.vm_type or "qemu",
                port=source_node.ssh_port,
                username=source_node.ssh_user,
                key_path=source_node.ssh_key_path
            )
            
            if not success:
                log_entry.message += f" | Registrazione VM fallita: impossibile ottenere config"
                return
            
            # Modifica config per il nuovo storage se necessario
            # (potrebbe essere necessario adattare i path dei dischi)
            modified_config = self._adapt_vm_config(config, job.source_dataset, job.dest_dataset)
            
            # Registra sul nodo destinazione
            success, msg = await proxmox_service.register_vm(
                hostname=dest_node.hostname,
                vmid=job.vm_id,
                vm_type=job.vm_type or "qemu",
                config_content=modified_config,
                port=dest_node.ssh_port,
                username=dest_node.ssh_user,
                key_path=dest_node.ssh_key_path
            )
            
            if success:
                log_entry.message += f" | VM {job.vm_id} registrata"
            else:
                log_entry.message += f" | Registrazione VM fallita: {msg}"
                
        except Exception as e:
            log_entry.message += f" | Errore registrazione VM: {e}"
    
    def _adapt_vm_config(self, config: str, source_dataset: str, dest_dataset: str) -> str:
        """
        Adatta la configurazione VM per il nodo destinazione
        
        Sostituisce i riferimenti allo storage sorgente con quello destinazione
        """
        # Estrai il nome dello storage dal dataset
        # es: rpool/data -> local-zfs (dipende dalla config Proxmox)
        # Per ora ritorniamo la config così com'è
        # In produzione servirebbe una mappatura storage sorgente -> destinazione
        
        return config
    
    def update_job_schedule(self, job_id: int, schedule: str):
        """Aggiorna lo schedule di un job"""
        if schedule:
            cron = croniter(schedule, datetime.utcnow())
            self._jobs[job_id] = cron.get_next(datetime)
        elif job_id in self._jobs:
            del self._jobs[job_id]
    
    def remove_job(self, job_id: int):
        """Rimuove un job dallo scheduler"""
        if job_id in self._jobs:
            del self._jobs[job_id]


# Singleton
scheduler_service = SchedulerService()
