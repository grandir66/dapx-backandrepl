"""
Router per Host Backup - Backup configurazione host Proxmox PVE e PBS

Ispirato a ProxSave (https://github.com/tis24dev/proxsave)
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime

from database import get_db, Node, JobLog
from routers.auth import get_current_user, User
from services.host_backup_service import host_backup_service

import logging

logger = logging.getLogger(__name__)

router = APIRouter()


class HostBackupCreate(BaseModel):
    """Schema per creazione backup host."""
    compress: bool = True
    encrypt: bool = False
    encrypt_password: Optional[str] = None
    dest_path: str = "/var/backups/proxmox-config"


class RetentionPolicy(BaseModel):
    """Schema per retention policy."""
    keep_last: int = Field(default=7, ge=1, le=100)


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
    
    # Rileva tipo host
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
    
    # Calcola totale
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
async def create_host_backup(
    node_id: int,
    config: HostBackupCreate,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Crea un backup della configurazione host."""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    # Rileva tipo host
    host_type = await host_backup_service.detect_host_type(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if host_type == 'unknown':
        raise HTTPException(
            status_code=400, 
            detail="Tipo host non riconosciuto. L'host deve essere PVE o PBS."
        )
    
    # Log inizio
    log = JobLog(
        job_type="host_backup",
        node_name=node.name,
        dataset=f"config-{host_type}",
        status="running",
        message=f"Avvio backup configurazione {host_type.upper()} su {node.name}",
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
        duration = (end_time - start_time).total_seconds()
        
        if result['success']:
            log.status = "success"
            log.message = f"Backup {host_type.upper()} completato: {result['backup_name']} ({result['size_human']})"
            log.completed_at = end_time
            log.duration = duration
            db.commit()
            
            return {
                "success": True,
                "node_name": node.name,
                "host_type": host_type,
                **result
            }
        else:
            log.status = "failed"
            log.error = result.get('error', 'Errore sconosciuto')
            log.message = f"Backup {host_type.upper()} fallito"
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
async def list_host_backups(
    node_id: int,
    backup_path: str = "/var/backups/proxmox-config",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Elenca i backup host esistenti."""
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
async def delete_host_backup(
    node_id: int,
    backup_file: str,
    backup_path: str = "/var/backups/proxmox-config",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Elimina un backup host."""
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
    
    return {
        "success": True,
        "deleted": backup_file,
        "node_name": node.name
    }


@router.post("/nodes/{node_id}/backups/retention")
async def apply_retention_policy(
    node_id: int,
    policy: RetentionPolicy,
    backup_path: str = "/var/backups/proxmox-config",
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user)
):
    """Applica retention policy ai backup host."""
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
    
    return {
        "success": True,
        "node_name": node.name,
        **result
    }

