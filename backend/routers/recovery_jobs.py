"""
Router per gestione Recovery Jobs (replica basata su PBS)
Permette di configurare e gestire job di backup/restore automatici
"""

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator, model_validator
import asyncio
import logging
import re
import json

from database import (
    get_db, Node, RecoveryJob, JobLog, User, 
    NodeType, RecoveryJobStatus
)
from services.pbs_service import pbs_service
from services.ssh_service import ssh_service
from routers.auth import get_current_user, require_operator, require_admin, log_audit

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Schemas ==============

class RecoveryJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200, description="Nome identificativo del job")
    source_node_id: int = Field(..., gt=0, description="ID nodo sorgente (PVE)")
    vm_id: int = Field(..., gt=0, le=999999, description="VMID della VM da replicare (1-999999)")
    vm_type: str = Field(default="qemu", pattern="^(qemu|lxc)$", description="Tipo VM: qemu o lxc")
    vm_name: Optional[str] = Field(None, max_length=100, description="Nome VM (opzionale)")
    pbs_node_id: int = Field(..., gt=0, description="ID nodo PBS")
    pbs_datastore: Optional[str] = Field(None, max_length=100, description="Datastore PBS (override)")
    pbs_storage_id: Optional[str] = Field(None, max_length=100, description="Nome storage PBS configurato sul nodo")
    dest_node_id: int = Field(..., gt=0, description="ID nodo destinazione (PVE)")
    dest_vm_id: Optional[int] = Field(None, gt=0, le=999999, description="VMID destinazione (opzionale)")
    dest_vm_name_suffix: Optional[str] = Field(None, max_length=50, description="Suffisso nome VM (es: '-replica')")
    dest_storage: Optional[str] = Field(None, max_length=100, description="Storage destinazione")
    backup_mode: str = Field(default="snapshot", pattern="^(snapshot|stop|suspend)$", description="Modalità backup")
    backup_compress: str = Field(default="zstd", pattern="^(none|lzo|gzip|zstd)$", description="Compressione backup")
    include_all_disks: bool = Field(default=True, description="Includi tutti i dischi")
    restore_start_vm: bool = Field(default=False, description="Avvia VM dopo restore")
    restore_unique: bool = Field(default=True, description="Genera nuovi UUID")
    overwrite_existing: bool = Field(default=True, description="Sovrascrivi se esiste")
    schedule: Optional[str] = Field(None, max_length=100, description="Schedule cron per recovery completo")
    backup_schedule: Optional[str] = Field(None, max_length=100, description="Schedule cron per backup (opzionale)")
    is_active: bool = Field(default=True, description="Job attivo")
    retry_on_failure: bool = Field(default=True, description="Retry automatico su fallimento")
    max_retries: int = Field(default=3, ge=0, le=10, description="Numero massimo retry (0-10)")
    retry_delay_minutes: int = Field(default=15, ge=1, le=1440, description="Ritardo tra retry in minuti (1-1440)")
    notify_on_each_run: bool = Field(default=False, description="Notifica ad ogni esecuzione (altrimenti solo report giornaliero)")
    
    @field_validator('name')
    @classmethod
    def validate_name(cls, v: str) -> str:
        """Valida nome: solo caratteri alfanumerici, spazi, trattini e underscore"""
        if not re.match(r'^[a-zA-Z0-9\s_-]+$', v):
            raise ValueError("Nome può contenere solo lettere, numeri, spazi, trattini e underscore")
        return v.strip()
    
    @field_validator('schedule', 'backup_schedule')
    @classmethod
    def validate_cron(cls, v: Optional[str]) -> Optional[str]:
        """Valida formato cron base (5 campi)"""
        if v is None:
            return v
        v = v.strip()
        if not v:
            return None
        # Verifica formato cron base: 5 campi separati da spazio
        parts = v.split()
        if len(parts) != 5:
            raise ValueError("Schedule deve essere in formato cron (5 campi: minuto ora giorno mese giorno_settimana)")
        # Verifica range valori base
        try:
            minute = parts[0]
            hour = parts[1]
            day = parts[2]
            month = parts[3]
            weekday = parts[4]
            
            # Valori validi per ogni campo (semplificato)
            if minute not in ['*', '*/1', '*/5', '*/10', '*/15', '*/30'] and not minute.isdigit():
                if not (minute.isdigit() and 0 <= int(minute) <= 59):
                    raise ValueError("Minuto non valido (0-59 o */N)")
            if hour != '*' and not hour.startswith('*/') and not (hour.isdigit() and 0 <= int(hour) <= 23):
                raise ValueError("Ora non valida (0-23)")
        except (ValueError, IndexError) as e:
            raise ValueError(f"Formato cron non valido: {str(e)}")
        return v
    
    @field_validator('dest_vm_name_suffix')
    @classmethod
    def validate_suffix(cls, v: Optional[str]) -> Optional[str]:
        """Valida suffisso nome VM"""
        if v is None:
            return v
        v = v.strip()
        if not re.match(r'^[a-zA-Z0-9_-]+$', v):
            raise ValueError("Suffisso può contenere solo lettere, numeri, trattini e underscore")
        return v
    
    @model_validator(mode='after')
    def validate_nodes_different(self):
        """Verifica che i nodi siano diversi"""
        if self.source_node_id == self.dest_node_id:
            raise ValueError("Nodo sorgente e destinazione devono essere diversi")
        return self


class RecoveryJobUpdate(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    vm_name: Optional[str] = Field(None, max_length=100)
    pbs_datastore: Optional[str] = Field(None, max_length=100)
    pbs_storage_id: Optional[str] = Field(None, max_length=100)
    dest_vm_id: Optional[int] = Field(None, gt=0, le=999999)
    dest_vm_name_suffix: Optional[str] = Field(None, max_length=50)
    dest_storage: Optional[str] = Field(None, max_length=100)
    backup_mode: Optional[str] = Field(None, pattern="^(snapshot|stop|suspend)$")
    backup_compress: Optional[str] = Field(None, pattern="^(none|lzo|gzip|zstd)$")
    include_all_disks: Optional[bool] = None
    restore_start_vm: Optional[bool] = None
    restore_unique: Optional[bool] = None
    overwrite_existing: Optional[bool] = None
    schedule: Optional[str] = Field(None, max_length=100)
    backup_schedule: Optional[str] = Field(None, max_length=100)
    is_active: Optional[bool] = None
    retry_on_failure: Optional[bool] = None
    max_retries: Optional[int] = Field(None, ge=0, le=10)
    retry_delay_minutes: Optional[int] = Field(None, ge=1, le=1440)
    notify_on_each_run: Optional[bool] = None


class RecoveryJobResponse(BaseModel):
    id: int
    name: str
    source_node_id: int
    vm_id: int
    vm_type: str
    vm_name: Optional[str]
    pbs_node_id: int
    pbs_datastore: Optional[str]
    pbs_storage_id: Optional[str]
    dest_node_id: int
    dest_vm_id: Optional[int]
    dest_vm_name_suffix: Optional[str]
    dest_storage: Optional[str]
    backup_mode: str
    backup_compress: str
    include_all_disks: bool
    restore_start_vm: bool
    restore_unique: bool
    overwrite_existing: bool
    schedule: Optional[str]
    backup_schedule: Optional[str]
    is_active: bool
    current_status: str
    last_backup_time: Optional[datetime]
    last_backup_id: Optional[str]
    last_restore_time: Optional[datetime]
    last_run: Optional[datetime]
    last_status: Optional[str]
    last_duration: Optional[int]
    last_error: Optional[str]
    run_count: int
    error_count: int
    consecutive_failures: int
    retry_on_failure: bool
    max_retries: int
    retry_delay_minutes: int
    notify_on_each_run: bool
    created_at: datetime
    # Durate delle ultime fasi (calcolate dai log)
    last_backup_duration: Optional[int] = None
    last_restore_duration: Optional[int] = None
    
    class Config:
        from_attributes = True


class PBSNodeInfo(BaseModel):
    """Info su un nodo PBS"""
    id: int
    name: str
    hostname: str
    pbs_available: bool
    pbs_version: Optional[str]
    pbs_datastore: Optional[str]
    datastores: List[str] = []


class BackupInfo(BaseModel):
    """Info su un backup PBS"""
    backup_id: str
    vm_id: int
    backup_time: datetime
    size: Optional[str]
    datastore: str


# ============== Helper Functions ==============

def check_node_access(user: User, node: Node) -> bool:
    """Verifica se l'utente ha accesso al nodo"""
    if user.role == "admin":
        return True
    if user.allowed_nodes is None:
        return True
    return node.id in user.allowed_nodes


async def execute_recovery_job_task(job_id: int, triggered_by: Optional[int] = None):
    """
    Task asincrono per eseguire un recovery job completo con logging dettagliato.
    Sequenza: Backup -> Attesa completamento -> Restore -> Registrazione VM
    
    Ogni fase viene registrata con log separati per tracciabilità completa.
    """
    from database import SessionLocal
    from services.notification_service import notification_service
    
    db = SessionLocal()
    log_entry_main = None
    log_entry_backup = None
    log_entry_restore = None
    
    try:
        job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
        if not job:
            logger.error(f"Recovery job {job_id} non trovato")
            return
        
        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
        pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
        
        if not source_node or not pbs_node or not dest_node:
            logger.error(f"Nodi non trovati per recovery job {job_id}")
            return
        
        # ========== FASE 0: PREPARAZIONE ==========
        logger.info(f"[Recovery Job {job_id}] === FASE 0: PREPARAZIONE ===")
        logger.info(f"[Recovery Job {job_id}] VM: {job.vm_id} ({job.vm_type})")
        logger.info(f"[Recovery Job {job_id}] Sorgente: {source_node.name} ({source_node.hostname})")
        logger.info(f"[Recovery Job {job_id}] PBS: {pbs_node.name} ({pbs_node.hostname})")
        logger.info(f"[Recovery Job {job_id}] Destinazione: {dest_node.name} ({dest_node.hostname})")
        
        # Log principale (overall)
        log_entry_main = JobLog(
            job_type="recovery",
            job_id=job_id,
            node_name=f"{source_node.name} -> {dest_node.name}",
            status="started",
            message=f"Avvio recovery VM {job.vm_id} ({job.vm_type}) da {source_node.name} a {dest_node.name} via PBS {pbs_node.name}",
            triggered_by=triggered_by
        )
        db.add(log_entry_main)
        job.current_status = RecoveryJobStatus.PENDING.value
        job.last_run = datetime.utcnow()
        db.commit()
        
        start_time = datetime.utcnow()
        datastore = job.pbs_datastore or pbs_node.pbs_datastore or "datastore1"
        
        logger.info(f"[Recovery Job {job_id}] Datastore PBS: {datastore}")
        logger.info(f"[Recovery Job {job_id}] Storage PBS: {job.pbs_storage_id or 'auto-create'}")
        
        # ========== FASE 1: BACKUP ==========
        logger.info(f"[Recovery Job {job_id}] === FASE 1: BACKUP ===")
        logger.info(f"[Recovery Job {job_id}] Avvio backup VM {job.vm_id} su nodo {source_node.name}")
        
        job.current_status = RecoveryJobStatus.BACKING_UP.value
        db.commit()
        
        # Log specifico per fase backup
        log_entry_backup = JobLog(
            job_type="backup",
            job_id=job_id,
            node_name=source_node.name,
            dataset=f"vm/{job.vm_id}",
            status="started",
            message=f"Backup VM {job.vm_id} verso PBS {pbs_node.name} (datastore: {datastore})",
            triggered_by=triggered_by
        )
        db.add(log_entry_backup)
        db.commit()
        
        backup_start = datetime.utcnow()
        
        # Esegui backup
        backup_result = await pbs_service.run_backup(
            source_node_hostname=source_node.hostname,
            vm_id=job.vm_id,
            pbs_hostname=pbs_node.hostname,
            datastore=datastore,
            pbs_user=f"{pbs_node.ssh_user}@pam",
            pbs_password=pbs_node.pbs_password,
            pbs_fingerprint=pbs_node.pbs_fingerprint,
            pbs_storage_id=job.pbs_storage_id,
            vm_type=job.vm_type,
            mode=job.backup_mode,
            compress=job.backup_compress,
            source_node_port=source_node.ssh_port,
            source_node_user=source_node.ssh_user,
            source_node_key=source_node.ssh_key_path
        )
        
        backup_duration = int((datetime.utcnow() - backup_start).total_seconds())
        
        # Aggiorna log backup
        if backup_result["success"]:
            log_entry_backup.status = "success"
            log_entry_backup.message = f"Backup completato: {backup_result.get('backup_id', 'N/A')}"
            log_entry_backup.backup_id = backup_result.get("backup_id")
            log_entry_backup.duration = backup_duration
            log_entry_backup.output = backup_result.get("output", "")[:5000]  # Limita output
            logger.info(f"[Recovery Job {job_id}] ✓ Backup completato in {backup_duration}s - ID: {backup_result.get('backup_id')}")
        else:
            log_entry_backup.status = "failed"
            log_entry_backup.message = f"Backup fallito: {backup_result.get('error', 'Unknown error')}"
            log_entry_backup.error = backup_result.get("error", backup_result.get("message", ""))[:2000]
            log_entry_backup.duration = backup_duration
            log_entry_backup.output = backup_result.get("output", "")[:5000]
            logger.error(f"[Recovery Job {job_id}] ✗ Backup fallito: {backup_result.get('error')}")
        
        log_entry_backup.completed_at = datetime.utcnow()
        db.commit()
        
        if not backup_result["success"]:
            # Backup fallito, termina qui
            job.current_status = RecoveryJobStatus.FAILED.value
            job.last_status = "failed"
            job.last_error = f"Backup fallito: {backup_result.get('error', 'Unknown error')}"
            job.error_count += 1
            job.consecutive_failures += 1
            job.last_duration = backup_duration
            
            log_entry_main.status = "failed"
            log_entry_main.message = f"Recovery fallito nella fase backup: {backup_result.get('error')}"
            log_entry_main.error = backup_result.get("error", "")[:2000]
            log_entry_main.duration = backup_duration
            log_entry_main.completed_at = datetime.utcnow()
            db.commit()
            
            # Notifica fallimento
            if job.notify_on_each_run:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="failed",
                    source=f"{source_node.name}:vm/{job.vm_id}",
                    destination=f"{dest_node.name}:vm/{job.dest_vm_id or job.vm_id}",
                    duration=backup_duration,
                    error=backup_result.get("error"),
                    details=f"Fase: Backup\n{backup_result.get('output', '')[:500]}",
                    job_id=job_id,
                    is_scheduled=bool(job.schedule)
                )
            
            return
        
        # Backup riuscito, aggiorna job
        job.last_backup_time = datetime.utcnow()
        job.last_backup_id = backup_result.get("backup_id")
        backup_id = backup_result.get("backup_id")
        
        # ========== FASE 2: RESTORE ==========
        logger.info(f"[Recovery Job {job_id}] === FASE 2: RESTORE ===")
        logger.info(f"[Recovery Job {job_id}] Backup ID: {backup_id}")
        logger.info(f"[Recovery Job {job_id}] Avvio restore su nodo {dest_node.name}")
        
        job.current_status = RecoveryJobStatus.RESTORING.value
        db.commit()
        
        # Log specifico per fase restore
        log_entry_restore = JobLog(
            job_type="restore",
            job_id=job_id,
            node_name=dest_node.name,
            dataset=f"vm/{job.dest_vm_id or job.vm_id}",
            status="started",
            message=f"Restore VM {job.vm_id} da PBS {pbs_node.name} (backup: {backup_id})",
            backup_id=backup_id,
            triggered_by=triggered_by
        )
        db.add(log_entry_restore)
        db.commit()
        
        restore_start = datetime.utcnow()
        
        # Esegui restore
        restore_result = await pbs_service.run_restore(
            dest_node_hostname=dest_node.hostname,
            vm_id=job.vm_id,
            pbs_hostname=pbs_node.hostname,
            datastore=datastore,
            backup_id=backup_id,
            pbs_user=f"{pbs_node.ssh_user}@pam",
            pbs_password=pbs_node.pbs_password,
            pbs_fingerprint=pbs_node.pbs_fingerprint,
            pbs_storage_id=job.pbs_storage_id,
            dest_vm_id=job.dest_vm_id,
            dest_vm_name_suffix=job.dest_vm_name_suffix,
            dest_storage=job.dest_storage,
            vm_type=job.vm_type,
            start_vm=job.restore_start_vm,
            unique=job.restore_unique,
            overwrite=job.overwrite_existing,
            dest_node_port=dest_node.ssh_port,
            dest_node_user=dest_node.ssh_user,
            dest_node_key=dest_node.ssh_key_path
        )
        
        restore_duration = int((datetime.utcnow() - restore_start).total_seconds())
        
        # Aggiorna log restore
        if restore_result["success"]:
            log_entry_restore.status = "success"
            log_entry_restore.message = f"Restore completato: VM {restore_result.get('vm_id')} registrata"
            log_entry_restore.duration = restore_duration
            log_entry_restore.output = restore_result.get("output", "")[:5000]
            logger.info(f"[Recovery Job {job_id}] ✓ Restore completato in {restore_duration}s - VMID: {restore_result.get('vm_id')}")
        else:
            log_entry_restore.status = "failed"
            log_entry_restore.message = f"Restore fallito: {restore_result.get('error', 'Unknown error')}"
            log_entry_restore.error = restore_result.get("error", restore_result.get("message", ""))[:2000]
            log_entry_restore.duration = restore_duration
            log_entry_restore.output = restore_result.get("output", "")[:5000]
            logger.error(f"[Recovery Job {job_id}] ✗ Restore fallito: {restore_result.get('error')}")
        
        log_entry_restore.completed_at = datetime.utcnow()
        db.commit()
        
        if not restore_result["success"]:
            # Restore fallito
            job.current_status = RecoveryJobStatus.FAILED.value
            job.last_status = "failed"
            job.last_error = f"Restore fallito: {restore_result.get('error', 'Unknown error')}"
            job.error_count += 1
            job.consecutive_failures += 1
            
            total_duration = int((datetime.utcnow() - start_time).total_seconds())
            job.last_duration = total_duration
            
            log_entry_main.status = "failed"
            log_entry_main.message = f"Recovery fallito nella fase restore: {restore_result.get('error')}"
            log_entry_main.error = restore_result.get("error", "")[:2000]
            log_entry_main.duration = total_duration
            log_entry_main.completed_at = datetime.utcnow()
            db.commit()
            
            # Notifica fallimento
            if job.notify_on_each_run:
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="failed",
                    source=f"{source_node.name}:vm/{job.vm_id}",
                    destination=f"{dest_node.name}:vm/{job.dest_vm_id or job.vm_id}",
                    duration=total_duration,
                    error=restore_result.get("error"),
                    details=f"Fase: Restore\nBackup ID: {backup_id}\n{restore_result.get('output', '')[:500]}",
                    job_id=job_id,
                    is_scheduled=bool(job.schedule)
                )
            
            return
        
        # ========== FASE 3: COMPLETAMENTO ==========
        logger.info(f"[Recovery Job {job_id}] === FASE 3: COMPLETAMENTO ===")
        
        job.current_status = RecoveryJobStatus.COMPLETED.value
        job.last_status = "success"
        job.last_error = None
        job.consecutive_failures = 0
        job.last_restore_time = datetime.utcnow()
        job.run_count += 1
        
        total_duration = int((datetime.utcnow() - start_time).total_seconds())
        job.last_duration = total_duration
        
        # Log principale successo
        log_entry_main.status = "success"
        log_entry_main.message = f"Recovery completata: Backup {backup_id} -> Restore VM {restore_result.get('vm_id')}"
        log_entry_main.duration = total_duration
        log_entry_main.backup_id = backup_id
        log_entry_main.completed_at = datetime.utcnow()
        log_entry_main.output = f"Backup: {backup_duration}s | Restore: {restore_duration}s | Totale: {total_duration}s"
        
        db.commit()
        
        logger.info(f"[Recovery Job {job_id}] ✓ Recovery completata in {total_duration}s (Backup: {backup_duration}s, Restore: {restore_duration}s)")
        
        # Notifica successo (solo se configurato)
        if job.notify_on_each_run:
            await notification_service.send_job_notification(
                job_name=job.name,
                status="success",
                source=f"{source_node.name}:vm/{job.vm_id}",
                destination=f"{dest_node.name}:vm/{restore_result.get('vm_id')}",
                duration=total_duration,
                details=f"Backup ID: {backup_id}\nBackup: {backup_duration}s\nRestore: {restore_duration}s",
                job_id=job_id,
                is_scheduled=bool(job.schedule)
            )
        
    except Exception as e:
        logger.exception(f"[Recovery Job {job_id}] Errore critico durante esecuzione: {e}")
        try:
            job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
            if job:
                job.current_status = RecoveryJobStatus.FAILED.value
                job.last_status = "failed"
                job.last_error = f"Errore critico: {str(e)}"
                job.error_count += 1
                job.consecutive_failures += 1
                
                if log_entry_main:
                    log_entry_main.status = "failed"
                    log_entry_main.error = f"Eccezione: {str(e)}"
                    log_entry_main.completed_at = datetime.utcnow()
                
                db.commit()
                
                # Notifica errore critico
                if job.notify_on_each_run:
                    from services.notification_service import notification_service
                    await notification_service.send_job_notification(
                        job_name=job.name,
                        status="failed",
                        source=f"N/A",
                        destination=f"N/A",
                        duration=0,
                        error=f"Errore critico: {str(e)}",
                        job_id=job_id,
                        is_scheduled=bool(job.schedule)
                    )
        except Exception as inner_e:
            logger.error(f"Errore durante cleanup: {inner_e}")
    finally:
        db.close()


# ============== Endpoints ==============

@router.get("/", response_model=List[RecoveryJobResponse])
async def list_recovery_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i recovery jobs con durate delle ultime fasi"""
    jobs = db.query(RecoveryJob).all()
    
    # Aggiungi durate delle ultime fasi per ogni job
    result = []
    for job in jobs:
        job_dict = {
            **job.__dict__,
            "last_backup_duration": None,
            "last_restore_duration": None
        }
        
        # Recupera ultimo log backup
        last_backup_log = db.query(JobLog).filter(
            JobLog.job_id == job.id,
            JobLog.job_type == "backup"
        ).order_by(JobLog.started_at.desc()).first()
        
        if last_backup_log and last_backup_log.duration:
            job_dict["last_backup_duration"] = last_backup_log.duration
        
        # Recupera ultimo log restore
        last_restore_log = db.query(JobLog).filter(
            JobLog.job_id == job.id,
            JobLog.job_type == "restore"
        ).order_by(JobLog.started_at.desc()).first()
        
        if last_restore_log and last_restore_log.duration:
            job_dict["last_restore_duration"] = last_restore_log.duration
        
        result.append(RecoveryJobResponse(**job_dict))
    
    return result


@router.post("/", response_model=RecoveryJobResponse)
async def create_recovery_job(
    job_data: RecoveryJobCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea un nuovo recovery job"""
    
    # Verifica nodi esistenti
    source_node = db.query(Node).filter(Node.id == job_data.source_node_id).first()
    pbs_node = db.query(Node).filter(Node.id == job_data.pbs_node_id).first()
    dest_node = db.query(Node).filter(Node.id == job_data.dest_node_id).first()
    
    if not source_node:
        raise HTTPException(status_code=404, detail="Nodo sorgente non trovato")
    if not pbs_node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    if not dest_node:
        raise HTTPException(status_code=404, detail="Nodo destinazione non trovato")
    
    # Verifica che il nodo PBS sia effettivamente un PBS
    if pbs_node.node_type != NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Il nodo PBS specificato non è di tipo PBS")
    
    # Verifica accesso ai nodi
    if not check_node_access(user, source_node) or not check_node_access(user, dest_node):
        raise HTTPException(status_code=403, detail="Accesso negato ai nodi specificati")
    
    # Crea il job
    job = RecoveryJob(
        **job_data.dict(),
        created_by=user.id
    )
    db.add(job)
    
    log_audit(
        db, user.id, "recovery_job_created", "recovery_job",
        details=f"Created recovery job: {job_data.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    db.refresh(job)
    return job


@router.get("/{job_id}", response_model=RecoveryJobResponse)
async def get_recovery_job(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene un recovery job specifico"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    return job


@router.put("/{job_id}", response_model=RecoveryJobResponse)
async def update_recovery_job(
    job_id: int,
    job_data: RecoveryJobUpdate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiorna un recovery job"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    
    for key, value in job_data.dict(exclude_unset=True).items():
        setattr(job, key, value)
    
    job.updated_at = datetime.utcnow()
    
    log_audit(
        db, user.id, "recovery_job_updated", "recovery_job",
        resource_id=job_id,
        details=f"Updated recovery job: {job.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    db.refresh(job)
    return job


@router.delete("/{job_id}")
async def delete_recovery_job(
    job_id: int,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Elimina un recovery job"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    
    job_name = job.name
    db.delete(job)
    
    log_audit(
        db, user.id, "recovery_job_deleted", "recovery_job",
        resource_id=job_id,
        details=f"Deleted recovery job: {job_name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    return {"message": "Recovery job eliminato"}


@router.post("/{job_id}/run")
async def run_recovery_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue manualmente un recovery job"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    
    # Verifica che non sia già in esecuzione
    if job.current_status in [
        RecoveryJobStatus.BACKING_UP.value,
        RecoveryJobStatus.RESTORING.value,
        RecoveryJobStatus.REGISTERING.value
    ]:
        raise HTTPException(status_code=400, detail="Job già in esecuzione")
    
    log_audit(
        db, user.id, "recovery_job_manual_run", "recovery_job",
        resource_id=job_id,
        details=f"Manual run: {job.name}",
        ip_address=request.client.host if request.client else None
    )
    
    # Avvia il job in background
    background_tasks.add_task(execute_recovery_job_task, job_id, user.id)
    
    return {
        "message": f"Recovery job {job.name} avviato",
        "job_id": job_id
    }


@router.post("/{job_id}/backup-only")
async def run_backup_only(
    job_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue solo la fase di backup di un recovery job"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    
    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    
    if not source_node or not pbs_node:
        raise HTTPException(status_code=404, detail="Nodi non trovati")
    
    datastore = job.pbs_datastore or pbs_node.pbs_datastore or "datastore1"
    
    # Esegui backup
    result = await pbs_service.run_backup(
        source_node_hostname=source_node.hostname,
        vm_id=job.vm_id,
        pbs_hostname=pbs_node.hostname,
        datastore=datastore,
        pbs_user=f"{pbs_node.ssh_user}@pam",
        pbs_password=pbs_node.pbs_password,
        pbs_fingerprint=pbs_node.pbs_fingerprint,
        pbs_storage_id=job.pbs_storage_id,  # Usa storage esistente se specificato
        vm_type=job.vm_type,
        mode=job.backup_mode,
        compress=job.backup_compress,
        source_node_port=source_node.ssh_port,
        source_node_user=source_node.ssh_user,
        source_node_key=source_node.ssh_key_path
    )
    
    # Aggiorna job
    if result["success"]:
        job.last_backup_time = datetime.utcnow()
        job.last_backup_id = result.get("backup_id")
        db.commit()
    
    return result


@router.post("/{job_id}/restore-only")
async def run_restore_only(
    job_id: int,
    backup_id: Optional[str] = None,
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue solo la fase di restore di un recovery job (usa ultimo backup disponibile o backup_id specifico)"""
    job = db.query(RecoveryJob).filter(RecoveryJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Recovery job non trovato")
    
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    
    if not pbs_node or not dest_node:
        raise HTTPException(status_code=404, detail="Nodi non trovati")
    
    datastore = job.pbs_datastore or pbs_node.pbs_datastore or "datastore1"
    
    # Esegui restore
    result = await pbs_service.run_restore(
        dest_node_hostname=dest_node.hostname,
        vm_id=job.vm_id,
        pbs_hostname=pbs_node.hostname,
        datastore=datastore,
        backup_id=backup_id or job.last_backup_id,
        pbs_user=f"{pbs_node.ssh_user}@pam",
        pbs_password=pbs_node.pbs_password,
        pbs_fingerprint=pbs_node.pbs_fingerprint,
        dest_vm_id=job.dest_vm_id,
        dest_storage=job.dest_storage,
        vm_type=job.vm_type,
        start_vm=job.restore_start_vm,
        unique=job.restore_unique,
        overwrite=job.overwrite_existing,
        dest_node_port=dest_node.ssh_port,
        dest_node_user=dest_node.ssh_user,
        dest_node_key=dest_node.ssh_key_path
    )
    
    # Aggiorna job
    if result["success"]:
        job.last_restore_time = datetime.utcnow()
        db.commit()
    
    return result


# ============== PBS Node Endpoints ==============

@router.get("/pbs-nodes/", response_model=List[PBSNodeInfo])
async def list_pbs_nodes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i nodi PBS configurati"""
    pbs_nodes = db.query(Node).filter(Node.node_type == NodeType.PBS.value).all()
    
    result = []
    for node in pbs_nodes:
        result.append(PBSNodeInfo(
            id=node.id,
            name=node.name,
            hostname=node.hostname,
            pbs_available=node.pbs_available,
            pbs_version=node.pbs_version,
            pbs_datastore=node.pbs_datastore,
            datastores=[]  # TODO: fetch from PBS
        ))
    
    return result


@router.post("/pbs-nodes/{node_id}/test")
async def test_pbs_node(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Testa la connessione a un nodo PBS"""
    node = db.query(Node).filter(
        Node.id == node_id,
        Node.node_type == NodeType.PBS.value
    ).first()
    
    if not node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    
    # Test connessione SSH
    ssh_ok, ssh_msg = await ssh_service.test_connection(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not ssh_ok:
        return {
            "success": False,
            "ssh": {"success": False, "message": ssh_msg},
            "pbs": {"success": False, "message": "SSH non disponibile"}
        }
    
    # Test PBS server
    pbs_ok, pbs_version = await pbs_service.check_pbs_server(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Aggiorna stato nodo
    node.is_online = ssh_ok
    node.pbs_available = pbs_ok
    node.pbs_version = pbs_version
    node.last_check = datetime.utcnow()
    db.commit()
    
    # Lista datastore se disponibile
    datastores = []
    if pbs_ok:
        datastores = await pbs_service.list_datastores(
            hostname=node.hostname,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
    
    return {
        "success": ssh_ok and pbs_ok,
        "ssh": {"success": ssh_ok, "message": ssh_msg},
        "pbs": {
            "success": pbs_ok,
            "version": pbs_version,
            "datastores": [ds.get("name") for ds in datastores] if datastores else []
        }
    }


@router.get("/pbs-nodes/{node_id}/backups")
async def list_pbs_backups(
    node_id: int,
    vm_id: Optional[int] = None,
    datastore: Optional[str] = None,
    pve_node_id: Optional[int] = None,
    pbs_storage: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Lista i backup disponibili su un nodo PBS.
    
    Metodo 1: Se PBS ha password configurata, usa proxmox-backup-client
    Metodo 2: Se specificato pve_node_id e pbs_storage, usa pvesh sul nodo PVE
    Metodo 3: Cerca automaticamente uno storage PBS su un nodo PVE collegato
    """
    node = db.query(Node).filter(
        Node.id == node_id,
        Node.node_type == NodeType.PBS.value
    ).first()
    
    if not node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    
    ds = datastore or node.pbs_datastore or "datastore1"
    backups = []
    
    # Metodo 1: Usa proxmox-backup-client se password disponibile
    if node.pbs_password:
        backups = await pbs_service.list_backups(
            pbs_hostname=node.hostname,
            datastore=ds,
            pbs_user=f"{node.ssh_user}@pam",
            pbs_password=node.pbs_password,
            pbs_fingerprint=node.pbs_fingerprint,
            vm_id=vm_id,
            from_node_hostname=node.hostname,
            from_node_port=node.ssh_port,
            from_node_user=node.ssh_user,
            from_node_key=node.ssh_key_path
        )
    else:
        # Metodo 2/3: Usa pvesh tramite nodo PVE con storage PBS configurato
        pve_node = None
        storage_name = pbs_storage
        
        if pve_node_id:
            pve_node = db.query(Node).filter(
                Node.id == pve_node_id,
                Node.node_type == NodeType.PVE.value
            ).first()
        else:
            # Cerca un nodo PVE qualsiasi
            pve_node = db.query(Node).filter(
                Node.node_type == NodeType.PVE.value
            ).first()
        
        if pve_node:
            # Se non specificato, cerca lo storage PBS sul nodo
            if not storage_name:
                # Lista storage e trova quello PBS
                result = await ssh_service.execute(
                    hostname=pve_node.hostname,
                    command="pvesm status 2>/dev/null",
                    port=pve_node.ssh_port,
                    username=pve_node.ssh_user,
                    key_path=pve_node.ssh_key_path
                )
                if result.success and result.stdout:
                    # Parse output testuale: Name Type Status Total Used Available %
                    lines = result.stdout.strip().split('\n')
                    for line in lines[1:]:  # Skip header
                        parts = line.split()
                        if len(parts) >= 3:
                            st_name = parts[0]
                            st_type = parts[1]
                            st_status = parts[2]
                            if st_type == "pbs" and st_status == "active":
                                storage_name = st_name
                                logger.info(f"Trovato storage PBS: {storage_name}")
                                break
            
            if storage_name:
                # Usa pvesh per listare i backup
                # Il nome del nodo PVE è il nome configurato nel DB (es: DA-PX-03)
                pve_name = pve_node.name
                cmd = f"pvesh get /nodes/{pve_name}/storage/{storage_name}/content --output-format json 2>/dev/null"
                logger.info(f"Esecuzione comando: {cmd}")
                
                result = await ssh_service.execute(
                    hostname=pve_node.hostname,
                    command=cmd,
                    port=pve_node.ssh_port,
                    username=pve_node.ssh_user,
                    key_path=pve_node.ssh_key_path
                )
                
                if result.success and result.stdout.strip():
                    try:
                        all_backups = json.loads(result.stdout)
                        
                        # Recupera i nomi delle VM/CT dal cluster
                        vm_names = {}
                        try:
                            # Ottieni lista VM/CT dal cluster
                            vm_result = await ssh_service.execute(
                                hostname=pve_node.hostname,
                                command="pvesh get /cluster/resources --output-format json 2>/dev/null",
                                port=pve_node.ssh_port,
                                username=pve_node.ssh_user,
                                key_path=pve_node.ssh_key_path
                            )
                            if vm_result.success:
                                vms = json.loads(vm_result.stdout)
                                for vm in vms:
                                    vmid = vm.get("vmid")
                                    name = vm.get("name", "")
                                    vm_type = "lxc" if vm.get("type") == "lxc" else "qemu"
                                    if vmid:
                                        vm_names[str(vmid)] = {"name": name, "type": vm_type}
                        except Exception as e:
                            logger.warning(f"Errore recupero nomi VM: {e}")
                        
                        for backup in all_backups:
                            # Converti formato PVE a formato standard
                            volid = backup.get("volid", "")
                            vmid = backup.get("vmid")
                            ctime = backup.get("ctime", 0)
                            # Converti timestamp Unix (secondi) a millisecondi per JavaScript
                            ctime_ms = ctime * 1000 if ctime else 0
                            size = backup.get("size", 0)
                            
                            # Estrai tipo e backup_id dal volid
                            # Formato: PBS-BACK:backup/ct/101/2025-11-19T22:26:27Z
                            vm_type = "qemu"
                            backup_id = volid
                            if "/ct/" in volid:
                                vm_type = "lxc"
                            
                            # Ottieni nome VM se disponibile
                            vm_name = ""
                            vmid_key = str(vmid) if vmid is not None else ""
                            if vmid_key in vm_names:
                                vm_name = vm_names[vmid_key].get("name", "")
                            
                            # Filtra per VM ID se specificato
                            if vm_id and vmid != vm_id:
                                continue
                            
                            backups.append({
                                "backup-id": backup_id,
                                "backup_id": backup_id,
                                "vmid": vmid,
                                "vm_name": vm_name,
                                "vm_type": vm_type,
                                "backup_time": ctime_ms,
                                "size": size,
                                "volid": volid
                            })
                    except json.JSONDecodeError as e:
                        logger.warning(f"Failed to parse pvesh backup list: {e}")
    
    return {
        "datastore": ds,
        "backups": backups,
        "count": len(backups)
    }


# ============== Direct Restore Endpoint ==============

class DirectRestoreRequest(BaseModel):
    """Richiesta di restore diretto da un backup PBS esistente"""
    pbs_node_id: int = Field(..., gt=0, description="ID nodo PBS sorgente")
    backup_id: str = Field(..., min_length=1, description="ID del backup PBS")
    dest_node_id: int = Field(..., gt=0, description="ID nodo PVE destinazione")
    dest_vmid: Optional[int] = Field(None, gt=0, le=999999, description="VMID destinazione (opzionale)")
    dest_storage: Optional[str] = Field(None, description="Storage destinazione (opzionale)")
    vm_type: str = Field(default="qemu", pattern="^(qemu|lxc)$", description="Tipo VM")


@router.post("/restore")
async def direct_restore(
    request: DirectRestoreRequest,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Esegue un restore diretto da un backup PBS esistente.
    Questo endpoint permette di ripristinare qualsiasi backup presente nel PBS,
    anche quelli non creati da questo applicativo.
    """
    # Verifica nodo PBS
    pbs_node = db.query(Node).filter(
        Node.id == request.pbs_node_id,
        Node.node_type == NodeType.PBS.value
    ).first()
    
    if not pbs_node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    
    # Verifica nodo destinazione
    dest_node = db.query(Node).filter(
        Node.id == request.dest_node_id,
        Node.node_type == NodeType.PVE.value
    ).first()
    
    if not dest_node:
        raise HTTPException(status_code=404, detail="Nodo PVE destinazione non trovato")
    
    # Estrai VMID dal backup_id se non specificato
    vmid = request.dest_vmid
    if not vmid:
        # Prova a estrarre il VMID dal backup_id (formato: vm/100/2024-01-01...)
        import re
        match = re.search(r'(vm|ct)/(\d+)/', request.backup_id)
        if match:
            vmid = int(match.group(2))
        else:
            raise HTTPException(status_code=400, detail="VMID non specificato e non estraibile dal backup_id")
    
    # Log dell'operazione
    log_audit(db, user.id, "restore_started", "restore", 
              resource_id=vmid, details=f"Restore da PBS {pbs_node.name} verso {dest_node.name}")
    
    # Esegui il restore
    datastore = pbs_node.pbs_datastore or "datastore1"
    storage = request.dest_storage
    
    result = await pbs_service.run_restore(
        dest_node_hostname=dest_node.hostname,
        vm_id=vmid,
        pbs_hostname=pbs_node.hostname,
        datastore=datastore,
        backup_id=request.backup_id,
        pbs_user=f"{pbs_node.ssh_user}@pam",
        pbs_password=pbs_node.pbs_password,
        pbs_fingerprint=pbs_node.pbs_fingerprint,
        dest_vm_id=vmid,
        dest_storage=storage,
        vm_type=request.vm_type,
        start_vm=False,
        unique=True,
        overwrite=True,
        dest_node_port=dest_node.ssh_port,
        dest_node_user=dest_node.ssh_user,
        dest_node_key=dest_node.ssh_key_path or "/root/.ssh/id_rsa"
    )
    
    if not result.get("success"):
        log_audit(db, user.id, "restore_failed", "restore",
                  resource_id=vmid, details=result.get("error", "Errore sconosciuto"))
        raise HTTPException(status_code=500, detail=result.get("error", "Errore durante il restore"))
    
    log_audit(db, user.id, "restore_completed", "restore",
              resource_id=vmid, details=f"Restore completato su {dest_node.name} come VM {vmid}")
    
    return {
        "success": True,
        "message": f"Restore completato con successo",
        "vmid": vmid,
        "node": dest_node.name
    }


# ============== Storage & VMID Endpoints ==============

@router.get("/node/{node_id}/storages")
async def get_node_storages(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene la lista degli storage disponibili su un nodo PVE.
    Utile per selezionare lo storage di destinazione per il restore.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    # Esegui comando per ottenere storage
    result = await ssh_service.execute(
        hostname=node.hostname,
        command="pvesm status --output-format json 2>/dev/null || pvesm status",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    storages = []
    
    if result.success:
        import json
        try:
            # Prova a parsare come JSON
            storage_list = json.loads(result.stdout)
            for s in storage_list:
                storages.append({
                    "name": s.get("storage"),
                    "type": s.get("type"),
                    "content": s.get("content", ""),
                    "active": s.get("active", 1) == 1,
                    "enabled": s.get("enabled", 1) == 1,
                    "used": s.get("used", 0),
                    "total": s.get("total", 0),
                    "avail": s.get("avail", 0)
                })
        except json.JSONDecodeError:
            # Fallback: parse output testuale
            lines = result.stdout.strip().split('\n')
            if len(lines) > 1:
                for line in lines[1:]:  # Skip header
                    parts = line.split()
                    if len(parts) >= 2:
                        storages.append({
                            "name": parts[0],
                            "type": parts[1] if len(parts) > 1 else "unknown",
                            "active": parts[2] == "active" if len(parts) > 2 else True,
                            "content": ""
                        })
    
    # Filtra storage che supportano images/rootdir (utili per VM)
    vm_storages = [s for s in storages if 
                   'images' in s.get('content', '') or 
                   'rootdir' in s.get('content', '') or
                   s.get('type') in ['zfspool', 'lvmthin', 'lvm', 'dir', 'nfs', 'cifs', 'btrfs']]
    
    # Filtra storage PBS (tipo pbs, content backup)
    pbs_storages = [s for s in storages if s.get('type') == 'pbs']
    
    return {
        "node": node.name,
        "storages": storages,
        "vm_storages": vm_storages,  # Storage adatti per VM
        "pbs_storages": pbs_storages  # Storage PBS configurati
    }


@router.get("/node/{node_id}/pbs-storages")
async def get_node_pbs_storages(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene la lista degli storage PBS configurati su un nodo PVE.
    Questi sono gli storage che possono essere usati per backup verso PBS.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    # Ottieni configurazione storage PBS
    result = await ssh_service.execute(
        hostname=node.hostname,
        command="""
pvesm status --output-format json 2>/dev/null | python3 -c "
import sys, json
data = json.load(sys.stdin)
pbs = [s for s in data if s.get('type') == 'pbs']
print(json.dumps(pbs))
" 2>/dev/null || pvesm status | grep ' pbs ' | awk '{print $1}'
""",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    pbs_storages = []
    
    if result.success and result.stdout.strip():
        import json
        try:
            pbs_storages = json.loads(result.stdout)
        except json.JSONDecodeError:
            # Fallback: lista semplice di nomi
            for name in result.stdout.strip().split('\n'):
                if name:
                    pbs_storages.append({
                        "name": name.strip(),
                        "type": "pbs",
                        "active": True
                    })
    
    # Per ogni storage PBS, ottieni i dettagli di configurazione
    for storage in pbs_storages:
        storage_name = storage.get("storage") or storage.get("name")
        if storage_name:
            detail_result = await ssh_service.execute(
                hostname=node.hostname,
                command=f"pvesm config {storage_name} 2>/dev/null",
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            if detail_result.success:
                # Parse config
                for line in detail_result.stdout.strip().split('\n'):
                    if ':' in line:
                        key, value = line.split(':', 1)
                        storage[key.strip()] = value.strip()
    
    return {
        "node": node.name,
        "pbs_storages": pbs_storages
    }


@router.get("/node/{node_id}/check-vmid/{vmid}")
async def check_vmid_available(
    node_id: int,
    vmid: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Verifica se un VMID è disponibile su un nodo PVE.
    Ritorna info sulla VM esistente se il VMID è già in uso.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    # Verifica QEMU VM
    qm_result = await ssh_service.execute(
        hostname=node.hostname,
        command=f"qm status {vmid} 2>/dev/null && qm config {vmid} 2>/dev/null | grep -E '^name:'",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if qm_result.success and "status:" in qm_result.stdout:
        # VMID in uso da una VM QEMU
        lines = qm_result.stdout.strip().split('\n')
        status_line = lines[0] if lines else ""
        name_line = next((l for l in lines if l.startswith("name:")), "")
        vm_name = name_line.replace("name:", "").strip() if name_line else f"VM {vmid}"
        
        status = "running" if "running" in status_line else "stopped"
        
        return {
            "available": False,
            "vmid": vmid,
            "in_use_by": {
                "type": "qemu",
                "name": vm_name,
                "status": status
            },
            "message": f"VMID {vmid} già in uso da VM '{vm_name}' ({status})"
        }
    
    # Verifica LXC Container
    pct_result = await ssh_service.execute(
        hostname=node.hostname,
        command=f"pct status {vmid} 2>/dev/null && pct config {vmid} 2>/dev/null | grep -E '^hostname:'",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if pct_result.success and "status:" in pct_result.stdout:
        # VMID in uso da un container LXC
        lines = pct_result.stdout.strip().split('\n')
        status_line = lines[0] if lines else ""
        name_line = next((l for l in lines if l.startswith("hostname:")), "")
        ct_name = name_line.replace("hostname:", "").strip() if name_line else f"CT {vmid}"
        
        status = "running" if "running" in status_line else "stopped"
        
        return {
            "available": False,
            "vmid": vmid,
            "in_use_by": {
                "type": "lxc",
                "name": ct_name,
                "status": status
            },
            "message": f"VMID {vmid} già in uso da Container '{ct_name}' ({status})"
        }
    
    # VMID disponibile
    return {
        "available": True,
        "vmid": vmid,
        "in_use_by": None,
        "message": f"VMID {vmid} disponibile"
    }


@router.get("/node/{node_id}/next-vmid")
async def get_next_available_vmid(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene il prossimo VMID disponibile su un nodo PVE.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    # Usa pvesh per ottenere il prossimo VMID
    result = await ssh_service.execute(
        hostname=node.hostname,
        command="pvesh get /cluster/nextid 2>/dev/null || echo '100'",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    next_vmid = 100
    if result.success:
        try:
            next_vmid = int(result.stdout.strip())
        except ValueError:
            pass
    
    return {
        "node": node.name,
        "next_vmid": next_vmid
    }


@router.get("/node/{node_id}/vms")
async def get_node_vms_for_recovery(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene la lista delle VM/CT su un nodo PVE.
    Include VMID, nome, tipo e stato.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if node.node_type == NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Questo endpoint è solo per nodi PVE, non PBS")
    
    vms = []
    
    # Lista QEMU VMs
    qm_result = await ssh_service.execute(
        hostname=node.hostname,
        command="qm list 2>/dev/null | tail -n +2",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if qm_result.success:
        for line in qm_result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 3:
                    vms.append({
                        "vmid": int(parts[0]),
                        "name": parts[1],
                        "status": parts[2],
                        "type": "qemu"
                    })
    
    # Lista LXC Containers
    pct_result = await ssh_service.execute(
        hostname=node.hostname,
        command="pct list 2>/dev/null | tail -n +2",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if pct_result.success:
        for line in pct_result.stdout.strip().split('\n'):
            if line:
                parts = line.split()
                if len(parts) >= 2:
                    vms.append({
                        "vmid": int(parts[0]),
                        "status": parts[1],
                        "name": parts[3] if len(parts) >= 4 else f"CT{parts[0]}",
                        "type": "lxc"
                    })
    
    # Ordina per VMID
    vms.sort(key=lambda x: x["vmid"])
    
    return {
        "node": node.name,
        "vms": vms,
        "count": len(vms)
    }

