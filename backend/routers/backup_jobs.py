"""
Router per gestione Backup Jobs verso PBS
Solo backup, senza restore automatico
"""
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, Request
from sqlalchemy.orm import Session
from sqlalchemy import desc
from typing import List, Optional
from pydantic import BaseModel, Field, field_validator
from datetime import datetime
import asyncio
import logging
import re

from database import (
    get_db, Node, BackupJob, BackupJobStatus, JobLog, NodeType
)
from routers.auth import get_current_user, require_operator, User, log_audit
from services import ssh_service

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== SCHEMAS ==============

class BackupJobCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    source_node_id: int
    vm_id: int = Field(..., ge=100, le=999999999)
    vm_type: str = "qemu"
    vm_name: Optional[str] = None
    pbs_node_id: int
    pbs_datastore: Optional[str] = None
    pbs_storage_id: Optional[str] = None
    backup_mode: str = "snapshot"
    backup_compress: str = "zstd"
    include_all_disks: bool = True
    bandwidth_limit: Optional[int] = None
    keep_last: int = 3
    keep_daily: Optional[int] = None
    keep_weekly: Optional[int] = None
    keep_monthly: Optional[int] = None
    schedule: Optional[str] = None
    is_active: bool = True
    notify_on_each_run: bool = False
    notify_on_failure: bool = True
    
    @field_validator('backup_mode')
    @classmethod
    def validate_backup_mode(cls, v):
        if v not in ['snapshot', 'stop', 'suspend']:
            raise ValueError('backup_mode deve essere: snapshot, stop, suspend')
        return v
    
    @field_validator('backup_compress')
    @classmethod
    def validate_compress(cls, v):
        if v not in ['none', 'lzo', 'gzip', 'zstd']:
            raise ValueError('backup_compress deve essere: none, lzo, gzip, zstd')
        return v
    
    @field_validator('schedule')
    @classmethod
    def validate_schedule(cls, v):
        if v is None or v == '':
            return None
        # Valida formato cron base
        cron_pattern = r'^(\*|[0-9,\-\/]+)\s+(\*|[0-9,\-\/]+)\s+(\*|[0-9,\-\/]+)\s+(\*|[0-9,\-\/]+)\s+(\*|[0-9,\-\/]+)$'
        if not re.match(cron_pattern, v):
            raise ValueError('schedule deve essere in formato cron valido')
        return v


class BackupJobUpdate(BaseModel):
    name: Optional[str] = None
    pbs_datastore: Optional[str] = None
    pbs_storage_id: Optional[str] = None
    backup_mode: Optional[str] = None
    backup_compress: Optional[str] = None
    include_all_disks: Optional[bool] = None
    bandwidth_limit: Optional[int] = None
    keep_last: Optional[int] = None
    keep_daily: Optional[int] = None
    keep_weekly: Optional[int] = None
    keep_monthly: Optional[int] = None
    schedule: Optional[str] = None
    is_active: Optional[bool] = None
    notify_on_each_run: Optional[bool] = None
    notify_on_failure: Optional[bool] = None


class BackupJobResponse(BaseModel):
    id: int
    name: str
    source_node_id: int
    source_node_name: Optional[str] = None
    vm_id: int
    vm_type: str
    vm_name: Optional[str] = None
    pbs_node_id: int
    pbs_node_name: Optional[str] = None
    pbs_datastore: Optional[str] = None
    pbs_storage_id: Optional[str] = None
    backup_mode: str
    backup_compress: str
    include_all_disks: bool
    bandwidth_limit: Optional[int] = None
    keep_last: int
    keep_daily: Optional[int] = None
    keep_weekly: Optional[int] = None
    keep_monthly: Optional[int] = None
    schedule: Optional[str] = None
    is_active: bool
    current_status: str
    last_backup_time: Optional[datetime] = None
    last_backup_id: Optional[str] = None
    last_backup_size: Optional[int] = None
    last_run: Optional[datetime] = None
    last_status: Optional[str] = None
    last_duration: Optional[int] = None
    last_error: Optional[str] = None
    run_count: int
    error_count: int
    notify_on_each_run: bool
    notify_on_failure: bool
    created_at: datetime
    
    class Config:
        from_attributes = True


# ============== HELPER FUNCTIONS ==============

def job_to_response(job: BackupJob, db: Session) -> BackupJobResponse:
    """Converte BackupJob in response con nomi nodi"""
    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    
    return BackupJobResponse(
        id=job.id,
        name=job.name,
        source_node_id=job.source_node_id,
        source_node_name=source_node.name if source_node else None,
        vm_id=job.vm_id,
        vm_type=job.vm_type,
        vm_name=job.vm_name,
        pbs_node_id=job.pbs_node_id,
        pbs_node_name=pbs_node.name if pbs_node else None,
        pbs_datastore=job.pbs_datastore,
        pbs_storage_id=job.pbs_storage_id,
        backup_mode=job.backup_mode,
        backup_compress=job.backup_compress,
        include_all_disks=job.include_all_disks,
        bandwidth_limit=job.bandwidth_limit,
        keep_last=job.keep_last,
        keep_daily=job.keep_daily,
        keep_weekly=job.keep_weekly,
        keep_monthly=job.keep_monthly,
        schedule=job.schedule,
        is_active=job.is_active,
        current_status=job.current_status,
        last_backup_time=job.last_backup_time,
        last_backup_id=job.last_backup_id,
        last_backup_size=job.last_backup_size,
        last_run=job.last_run,
        last_status=job.last_status,
        last_duration=job.last_duration,
        last_error=job.last_error,
        run_count=job.run_count,
        error_count=job.error_count,
        notify_on_each_run=job.notify_on_each_run,
        notify_on_failure=job.notify_on_failure,
        created_at=job.created_at
    )


# ============== CRUD ENDPOINTS ==============

@router.get("/", response_model=List[BackupJobResponse])
async def list_backup_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i backup jobs"""
    jobs = db.query(BackupJob).order_by(desc(BackupJob.created_at)).all()
    return [job_to_response(job, db) for job in jobs]


@router.get("/{job_id}", response_model=BackupJobResponse)
async def get_backup_job(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene dettagli di un backup job"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    return job_to_response(job, db)


@router.post("/", response_model=BackupJobResponse)
async def create_backup_job(
    job_data: BackupJobCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea un nuovo backup job"""
    # Verifica nodi
    source_node = db.query(Node).filter(Node.id == job_data.source_node_id).first()
    if not source_node or source_node.node_type != NodeType.PVE.value:
        raise HTTPException(status_code=400, detail="Nodo sorgente non valido (deve essere PVE)")
    
    pbs_node = db.query(Node).filter(Node.id == job_data.pbs_node_id).first()
    if not pbs_node or pbs_node.node_type != NodeType.PBS.value:
        raise HTTPException(status_code=400, detail="Nodo PBS non valido")
    
    # Crea job
    job = BackupJob(
        name=job_data.name,
        source_node_id=job_data.source_node_id,
        vm_id=job_data.vm_id,
        vm_type=job_data.vm_type,
        vm_name=job_data.vm_name,
        pbs_node_id=job_data.pbs_node_id,
        pbs_datastore=job_data.pbs_datastore or pbs_node.pbs_datastore,
        pbs_storage_id=job_data.pbs_storage_id,
        backup_mode=job_data.backup_mode,
        backup_compress=job_data.backup_compress,
        include_all_disks=job_data.include_all_disks,
        bandwidth_limit=job_data.bandwidth_limit,
        keep_last=job_data.keep_last,
        keep_daily=job_data.keep_daily,
        keep_weekly=job_data.keep_weekly,
        keep_monthly=job_data.keep_monthly,
        schedule=job_data.schedule,
        is_active=job_data.is_active,
        notify_on_each_run=job_data.notify_on_each_run,
        notify_on_failure=job_data.notify_on_failure,
        created_by=user.id
    )
    
    db.add(job)
    db.commit()
    db.refresh(job)
    
    log_audit(db, user.id, "backup_job_created", "backup_job", 
              resource_id=job.id, details=f"Created backup job: {job.name}")
    
    return job_to_response(job, db)


@router.put("/{job_id}", response_model=BackupJobResponse)
async def update_backup_job(
    job_id: int,
    job_data: BackupJobUpdate,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiorna un backup job"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    update_data = job_data.model_dump(exclude_unset=True)
    for key, value in update_data.items():
        setattr(job, key, value)
    
    job.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(job)
    
    log_audit(db, user.id, "backup_job_updated", "backup_job",
              resource_id=job.id, details=f"Updated backup job: {job.name}")
    
    return job_to_response(job, db)


@router.delete("/{job_id}")
async def delete_backup_job(
    job_id: int,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina un backup job"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    job_name = job.name
    db.delete(job)
    db.commit()
    
    log_audit(db, user.id, "backup_job_deleted", "backup_job",
              resource_id=job_id, details=f"Deleted backup job: {job_name}")
    
    return {"status": "success", "message": f"Backup job '{job_name}' eliminato"}


# ============== EXECUTION ==============

async def execute_backup_task(job_id: int, db_path: str):
    """Task asincrono per eseguire il backup"""
    from database import SessionLocal
    db = SessionLocal()
    
    try:
        job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
        if not job:
            logger.error(f"Backup job {job_id} non trovato")
            return
        
        start_time = datetime.utcnow()
        job.current_status = BackupJobStatus.RUNNING.value
        job.last_run = start_time
        db.commit()
        
        # Ottieni nodi
        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
        pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
        
        if not source_node or not pbs_node:
            raise Exception("Nodi non trovati")
        
        # Log inizio
        log = JobLog(
            job_type="backup",
            job_id=job.id,
            node_name=source_node.name,
            status="running",
            message=f"Avvio backup VM {job.vm_id} ({job.name}) verso PBS {pbs_node.name}",
            started_at=start_time
        )
        db.add(log)
        db.commit()
        
        # Costruisci comando backup
        vm_cmd = "qm" if job.vm_type == "qemu" else "pct"
        storage_id = await _resolve_backup_storage(source_node, job.pbs_storage_id)
        
        backup_cmd = f"vzdump {job.vm_id} --storage {storage_id} --mode {job.backup_mode} --compress {job.backup_compress}"
        
        if job.bandwidth_limit:
            backup_cmd += f" --bwlimit {job.bandwidth_limit}"
        
        if not job.include_all_disks:
            backup_cmd += " --exclude-path /tmp"
        
        logger.info(f"Esecuzione backup: {backup_cmd}")
        
        # Esegui backup via SSH
        result = await ssh_service.execute(
            hostname=source_node.hostname,
            command=backup_cmd,
            port=source_node.ssh_port,
            username=source_node.ssh_user,
            key_path=source_node.ssh_key_path or "/root/.ssh/id_rsa",
            timeout=7200  # 2 ore timeout per backup grandi
        )
        
        end_time = datetime.utcnow()
        duration = int((end_time - start_time).total_seconds())
        
        success = result.success
        output = result.stdout
        error = result.stderr
        
        if success:
            # Estrai info backup dall'output
            backup_id = None
            backup_size = None
            
            # Cerca ID backup nell'output
            import re
            id_match = re.search(r'creating vzdump archive.*?(\S+\.vma)', output or "")
            if id_match:
                backup_id = id_match.group(1)
            
            size_match = re.search(r'transferred (\d+(?:\.\d+)?)\s*([KMGT]?B)', output or "")
            if size_match:
                size_val = float(size_match.group(1))
                size_unit = size_match.group(2)
                multipliers = {'B': 1, 'KB': 1024, 'MB': 1024**2, 'GB': 1024**3, 'TB': 1024**4}
                backup_size = int(size_val * multipliers.get(size_unit, 1))
            
            job.current_status = BackupJobStatus.COMPLETED.value
            job.last_status = "success"
            job.last_backup_time = end_time
            job.last_backup_id = backup_id
            job.last_backup_size = backup_size
            job.run_count += 1
            job.consecutive_failures = 0
            job.last_error = None
            
            log.status = "success"
            log.message = f"Backup completato in {duration}s"
            log.output = output[:5000] if output else None
            
            logger.info(f"Backup job {job.id} completato con successo")
        else:
            job.current_status = BackupJobStatus.FAILED.value
            job.last_status = "failed"
            job.error_count += 1
            job.consecutive_failures += 1
            job.last_error = error[:1000] if error else "Errore sconosciuto"
            
            log.status = "failed"
            log.message = f"Backup fallito: {error[:500] if error else 'Errore'}"
            log.error = error[:5000] if error else None
            
            logger.error(f"Backup job {job.id} fallito: {error}")
        
        job.last_duration = duration
        log.completed_at = end_time
        log.duration = duration
        
        db.commit()
        
        # Notifica se richiesto
        if job.notify_on_each_run or (job.notify_on_failure and job.last_status == "failed"):
            try:
                from services.notification_service import notification_service
                await notification_service.send_job_notification(
                    job_type="backup",
                    job_name=job.name,
                    status=job.last_status,
                    source=f"{source_node.name}:vm/{job.vm_id}",
                    destination=f"{pbs_node.name}:{job.pbs_storage_id}",
                    duration=duration,
                    error=error if job.last_status == "failed" else None,
                    details=f"VM {job.vm_id} - Durata: {duration}s",
                    job_id=job_id,
                    is_scheduled=bool(job.schedule),
                    notify_mode=job.notify_mode or "daily",
                    source_node_name=source_node.name,
                    dest_node_name=pbs_node.name,
                    vm_name=job.vm_name,
                    vm_id=job.vm_id
                )
            except Exception as e:
                logger.warning(f"Errore invio notifica: {e}")
        
    except Exception as e:
        logger.exception(f"Errore esecuzione backup job {job_id}")
        if job:
            job.current_status = BackupJobStatus.FAILED.value
            job.last_status = "failed"
            job.last_error = str(e)[:1000]
            job.error_count += 1
            job.consecutive_failures += 1
            db.commit()
    finally:
        db.close()


@router.post("/{job_id}/run")
async def run_backup_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue manualmente un backup job"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    if job.current_status == BackupJobStatus.RUNNING.value:
        raise HTTPException(status_code=400, detail="Backup già in esecuzione")
    
    log_audit(db, user.id, "backup_job_manual_run", "backup_job",
              resource_id=job.id, details=f"Manual run: {job.name}")
    
    # Avvia in background
    background_tasks.add_task(execute_backup_task, job_id, "")
    
    return {
        "status": "started",
        "message": f"Backup job '{job.name}' avviato",
        "job_id": job.id
    }


# ============== BACKUP LIST FROM PBS ==============

@router.get("/{job_id}/backups")
async def list_job_backups(
    job_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista i backup disponibili per questo job su PBS"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    if not pbs_node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    
    try:
        from services.pbs_service import pbs_service
        backups = await pbs_service.list_vm_backups(
            pbs_node=pbs_node,
            vm_id=job.vm_id,
            vm_type=job.vm_type,
            datastore=job.pbs_datastore
        )
        return {"backups": backups}
    except Exception as e:
        logger.error(f"Errore listing backups: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{job_id}/backups/{backup_id}")
async def delete_backup(
    job_id: int,
    backup_id: str,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina un backup specifico da PBS"""
    job = db.query(BackupJob).filter(BackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Backup job non trovato")
    
    pbs_node = db.query(Node).filter(Node.id == job.pbs_node_id).first()
    if not pbs_node:
        raise HTTPException(status_code=404, detail="Nodo PBS non trovato")
    
    try:
        from services.pbs_service import pbs_service
        success = await pbs_service.delete_backup(
            pbs_node=pbs_node,
            backup_id=backup_id,
            datastore=job.pbs_datastore
        )
        
        if success:
            log_audit(db, user.id, "backup_deleted", "backup_job",
                      resource_id=job.id, details=f"Deleted backup: {backup_id}")
            return {"status": "success", "message": "Backup eliminato"}
        else:
            raise HTTPException(status_code=500, detail="Errore eliminazione backup")
    except Exception as e:
        logger.error(f"Errore delete backup: {e}")
        raise HTTPException(status_code=500, detail=str(e))


async def _resolve_backup_storage(node: Node, preferred: Optional[str]) -> str:
    """Determina lo storage PBS da usare per il backup."""
    if preferred:
        return preferred

    result = await ssh_service.execute(
        hostname=node.hostname,
        command="pvesm status 2>/dev/null",
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )

    if result.success and result.stdout:
        lines = result.stdout.strip().splitlines()
        for line in lines[1:]:
            parts = line.split()
            if len(parts) >= 3:
                st_name, st_type, st_status = parts[0], parts[1], parts[2]
                if st_type == "pbs" and st_status == "active":
                    return st_name

    return "pbs-backup"

