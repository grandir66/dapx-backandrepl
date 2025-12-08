"""
Router per Host Backup - Backup configurazione host Proxmox PVE e PBS

Ispirato a ProxSave (https://github.com/tis24dev/proxsave)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from database import get_db, Node, JobLog, HostBackupJob
from routers.auth import get_current_user, User
from services.host_backup_service import host_backup_service

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


# ============== SCHEMAS ==============

class HostBackupJobCreate(BaseModel):
    """Schema per creazione job host backup."""
    name: str
    node_id: int
    dest_path: str = "/var/backups/proxmox-config"
    compress: bool = True
    encrypt: bool = False
    encrypt_password: Optional[str] = None
    keep_last: int = Field(default=7, ge=1, le=100)
    schedule: Optional[str] = None
    is_active: bool = True
    notify_mode: str = "daily"
    notify_subject: Optional[str] = None


class HostBackupJobUpdate(BaseModel):
    """Schema per modifica job host backup."""
    name: Optional[str] = None
    dest_path: Optional[str] = None
    compress: Optional[bool] = None
    encrypt: Optional[bool] = None
    encrypt_password: Optional[str] = None
    keep_last: Optional[int] = Field(default=None, ge=1, le=100)
    schedule: Optional[str] = None
    is_active: Optional[bool] = None
    notify_mode: Optional[str] = None
    notify_subject: Optional[str] = None


class ManualBackupRequest(BaseModel):
    """Schema per backup manuale."""
    compress: bool = True
    encrypt: bool = False
    encrypt_password: Optional[str] = None
    dest_path: str = "/var/backups/proxmox-config"


class RetentionPolicy(BaseModel):
    """Schema per retention policy."""
    keep_last: int = Field(default=7, ge=1, le=100)


# ============== JOB MANAGEMENT ==============

@router.get("/jobs")
async def list_host_backup_jobs(
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Elenca tutti i job di host backup."""
    jobs = db.query(HostBackupJob).all()
    
    result = []
    for job in jobs:
        node = db.query(Node).filter(Node.id == job.node_id).first()
        result.append({
            "id": job.id,
            "name": job.name,
            "node_id": job.node_id,
            "node_name": node.name if node else "N/A",
            "node_type": node.node_type if node else "N/A",
            "dest_path": job.dest_path,
            "compress": job.compress,
            "encrypt": job.encrypt,
            "keep_last": job.keep_last,
            "schedule": job.schedule,
            "is_active": job.is_active,
            "notify_mode": job.notify_mode,
            "notify_subject": job.notify_subject,
            "current_status": job.current_status,
            "last_backup_time": job.last_backup_time.isoformat() if job.last_backup_time else None,
            "last_backup_file": job.last_backup_file,
            "last_backup_size": job.last_backup_size,
            "last_run": job.last_run.isoformat() if job.last_run else None,
            "last_status": job.last_status,
            "last_duration": job.last_duration,
            "last_error": job.last_error,
            "run_count": job.run_count,
            "error_count": job.error_count,
            "created_at": job.created_at.isoformat() if job.created_at else None
        })
    
    return {"jobs": result, "count": len(result)}


@router.post("/jobs")
async def create_host_backup_job(
    job_data: HostBackupJobCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Crea un nuovo job di host backup schedulato."""
    # Verifica nodo
    node = db.query(Node).filter(Node.id == job_data.node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if node.node_type not in ['pve', 'pbs']:
        raise HTTPException(status_code=400, detail="Il nodo deve essere PVE o PBS")
    
    # Crea job
    job = HostBackupJob(
        name=job_data.name,
        node_id=job_data.node_id,
        dest_path=job_data.dest_path,
        compress=job_data.compress,
        encrypt=job_data.encrypt,
        encrypt_password=job_data.encrypt_password if job_data.encrypt else None,
        keep_last=job_data.keep_last,
        schedule=job_data.schedule if job_data.schedule else None,
        is_active=job_data.is_active,
        notify_mode=job_data.notify_mode,
        notify_subject=job_data.notify_subject,
        created_by=user.id
    )
    
    db.add(job)
    db.commit()
    db.refresh(job)
    
    return {
        "success": True,
        "job_id": job.id,
        "message": f"Job '{job.name}' creato con successo"
    }


@router.get("/jobs/{job_id}")
async def get_host_backup_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Ottiene dettagli di un job."""
    job = db.query(HostBackupJob).filter(HostBackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    node = db.query(Node).filter(Node.id == job.node_id).first()
    
    return {
        "id": job.id,
        "name": job.name,
        "node_id": job.node_id,
        "node_name": node.name if node else "N/A",
        "node_type": node.node_type if node else "N/A",
        "dest_path": job.dest_path,
        "compress": job.compress,
        "encrypt": job.encrypt,
        "keep_last": job.keep_last,
        "schedule": job.schedule,
        "is_active": job.is_active,
        "notify_mode": job.notify_mode,
        "notify_subject": job.notify_subject,
        "current_status": job.current_status,
        "last_backup_time": job.last_backup_time,
        "last_backup_file": job.last_backup_file,
        "last_backup_size": job.last_backup_size,
        "last_run": job.last_run,
        "last_status": job.last_status,
        "last_duration": job.last_duration,
        "last_error": job.last_error,
        "run_count": job.run_count,
        "error_count": job.error_count
    }


@router.put("/jobs/{job_id}")
async def update_host_backup_job(
    job_id: int,
    job_data: HostBackupJobUpdate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Aggiorna un job esistente."""
    job = db.query(HostBackupJob).filter(HostBackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    # Aggiorna solo i campi forniti
    update_data = job_data.dict(exclude_unset=True)
    for key, value in update_data.items():
        if value is not None:
            setattr(job, key, value)
    
    job.updated_at = datetime.utcnow()
    db.commit()
    
    return {"success": True, "message": "Job aggiornato"}


@router.delete("/jobs/{job_id}")
async def delete_host_backup_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Elimina un job."""
    job = db.query(HostBackupJob).filter(HostBackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    db.delete(job)
    db.commit()
    
    return {"success": True, "message": "Job eliminato"}


@router.post("/jobs/{job_id}/run")
async def run_host_backup_job(
    job_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Esegue un job di host backup manualmente."""
    job = db.query(HostBackupJob).filter(HostBackupJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    node = db.query(Node).filter(Node.id == job.node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    # Rileva tipo host
    host_type = await host_backup_service.detect_host_type(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Log inizio
    log = JobLog(
        job_type="host_backup",
        job_id=job.id,
        node_name=node.name,
        dataset=f"config-{host_type}",
        status="running",
        message=f"Avvio backup configurazione {host_type.upper()} su {node.name}",
        triggered_by=user.id
    )
    db.add(log)
    
    job.current_status = "running"
    job.run_count += 1
    db.commit()
    
    start_time = datetime.utcnow()
    
    try:
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
            
            log.status = "success"
            log.message = f"Backup {host_type.upper()} completato: {result['backup_name']} ({result['size_human']})"
            log.completed_at = end_time
            log.duration = duration
            
            db.commit()
            
            return {
                "success": True,
                "job_id": job.id,
                "node_name": node.name,
                "host_type": host_type,
                **result
            }
        else:
            job.current_status = "failed"
            job.last_status = "failed"
            job.last_run = end_time
            job.last_duration = duration
            job.last_error = result.get('error')
            job.error_count += 1
            
            log.status = "failed"
            log.error = result.get('error')
            log.message = f"Backup {host_type.upper()} fallito"
            log.completed_at = end_time
            log.duration = duration
            
            db.commit()
            
            raise HTTPException(status_code=500, detail=result.get('error'))
            
    except Exception as e:
        job.current_status = "failed"
        job.last_status = "failed"
        job.last_error = str(e)
        job.error_count += 1
        
        log.status = "failed"
        log.error = str(e)
        log.completed_at = datetime.utcnow()
        
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


# ============== NODE OPERATIONS (manual/one-time) ==============

@router.get("/nodes/{node_id}/host-type")
async def detect_host_type(
    node_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Rileva il tipo di host (pve/pbs)."""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    host_type = await host_backup_service.detect_host_type(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return {
        "node_id": node_id,
        "node_name": node.name,
        "host_type": host_type,
        "detected": host_type != 'unknown'
    }


@router.get("/nodes/{node_id}/backup-paths")
async def list_backup_paths(
    node_id: int,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Elenca i percorsi di configurazione con dimensioni."""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    host_type = await host_backup_service.detect_host_type(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    paths = await host_backup_service.list_backup_paths(
        hostname=node.hostname,
        host_type=host_type,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    total_size = sum(p['size'] for p in paths if p['exists'])
    existing_count = sum(1 for p in paths if p['exists'])
    
    return {
        "node_id": node_id,
        "node_name": node.name,
        "host_type": host_type,
        "paths": paths,
        "total_size": total_size,
        "total_size_human": host_backup_service._format_size(total_size),
        "existing_paths": existing_count,
        "total_paths": len(paths)
    }


@router.post("/nodes/{node_id}/backup")
async def create_manual_backup(
    node_id: int,
    config: ManualBackupRequest,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Crea un backup manuale (one-time)."""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    host_type = await host_backup_service.detect_host_type(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if host_type == 'unknown':
        raise HTTPException(status_code=400, detail="Tipo host non riconosciuto")
    
    log = JobLog(
        job_type="host_backup",
        node_name=node.name,
        dataset=f"config-{host_type}",
        status="running",
        message=f"Backup manuale configurazione {host_type.upper()} su {node.name}",
        triggered_by=user.id
    )
    db.add(log)
    db.commit()
    
    start_time = datetime.utcnow()
    
    try:
        result = await host_backup_service.create_host_backup(
            hostname=node.hostname,
            host_type=host_type,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path,
            dest_path=config.dest_path,
            compress=config.compress,
            encrypt=config.encrypt,
            encrypt_password=config.encrypt_password
        )
        
        end_time = datetime.utcnow()
        duration = int((end_time - start_time).total_seconds())
        
        if result['success']:
            log.status = "success"
            log.message = f"Backup {host_type.upper()} completato: {result['backup_name']} ({result['size_human']})"
            log.completed_at = end_time
            log.duration = duration
            db.commit()
            
            return {"success": True, "node_name": node.name, "host_type": host_type, **result}
        else:
            log.status = "failed"
            log.error = result.get('error')
            log.completed_at = end_time
            log.duration = duration
            db.commit()
            raise HTTPException(status_code=500, detail=result.get('error'))
            
    except Exception as e:
        log.status = "failed"
        log.error = str(e)
        log.completed_at = datetime.utcnow()
        db.commit()
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/nodes/{node_id}/backups")
async def list_node_backups(
    node_id: int,
    backup_path: str = "/var/backups/proxmox-config",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Elenca i backup esistenti su un nodo."""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    backups = await host_backup_service.list_host_backups(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        backup_path=backup_path
    )
    
    return {
        "node_id": node_id,
        "node_name": node.name,
        "backup_path": backup_path,
        "backups": backups,
        "count": len(backups)
    }


@router.delete("/nodes/{node_id}/backups")
async def delete_node_backup(
    node_id: int,
    backup_file: str,
    backup_path: str = "/var/backups/proxmox-config",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Elimina un backup da un nodo."""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    full_path = f"{backup_path}/{backup_file}"
    
    result = await host_backup_service.delete_host_backup(
        hostname=node.hostname,
        backup_path=full_path,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if not result['success']:
        raise HTTPException(status_code=500, detail=result.get('error'))
    
    return {"success": True, "deleted": backup_file, "node_name": node.name}


@router.post("/nodes/{node_id}/backups/retention")
async def apply_node_retention(
    node_id: int,
    policy: RetentionPolicy,
    backup_path: str = "/var/backups/proxmox-config",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Applica retention policy ai backup di un nodo."""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    result = await host_backup_service.apply_retention(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        backup_path=backup_path,
        keep_last=policy.keep_last
    )
    
    return {"success": True, "node_name": node.name, **result}
