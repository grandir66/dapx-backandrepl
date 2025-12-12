"""
Router per gestione Migration Jobs (migrazione/copia VM tra nodi Proxmox)
Usa funzionalità native di Proxmox (qm copy / pct copy)
"""

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel, Field, field_validator
import asyncio
import logging
import json

from database import (
    get_db, Node, MigrationJob, JobLog, User, 
    NodeType
)
from services.migration_service import migration_service
from services.proxmox_service import proxmox_service
from services.notification_service import notification_service
from routers.auth import get_current_user, require_operator, require_admin, log_audit

logger = logging.getLogger(__name__)
router = APIRouter()


# ============== Schemas ==============

class MigrationJobCreate(BaseModel):
    name: str
    source_node_id: int
    vm_id: int
    vm_type: str = "qemu"  # qemu, lxc
    dest_node_id: int
    dest_vm_id: Optional[int] = None
    dest_vm_name_suffix: Optional[str] = None
    
    migration_type: str = "copy"  # copy, move
    create_snapshot: bool = True
    keep_snapshots: int = 1
    start_after_migration: bool = False
    
    # Riconfigurazione hardware (JSON)
    hw_config: Optional[dict] = None  # {"memory": 4096, "cores": 2, "network": {...}, "storage": {...}}
    
    schedule: Optional[str] = None  # Cron format
    notify_mode: str = "daily"
    notify_subject: Optional[str] = None


class MigrationJobUpdate(BaseModel):
    name: Optional[str] = None
    source_node_id: Optional[int] = None
    vm_id: Optional[int] = None
    vm_type: Optional[str] = None
    dest_node_id: Optional[int] = None
    dest_vm_id: Optional[int] = None
    dest_vm_name_suffix: Optional[str] = None
    
    migration_type: Optional[str] = None
    create_snapshot: Optional[bool] = None
    keep_snapshots: Optional[int] = None
    start_after_migration: Optional[bool] = None
    
    hw_config: Optional[dict] = None
    
    schedule: Optional[str] = None
    is_active: Optional[bool] = None
    notify_mode: Optional[str] = None
    notify_subject: Optional[str] = None


class MigrationJobResponse(BaseModel):
    id: int
    name: str
    source_node_id: int
    vm_id: int
    vm_type: str
    vm_name: Optional[str]
    dest_node_id: int
    dest_vm_id: Optional[int]
    dest_vm_name_suffix: Optional[str]
    
    migration_type: str
    create_snapshot: bool
    keep_snapshots: int
    start_after_migration: bool
    
    hw_config: Optional[dict]
    
    schedule: Optional[str]
    is_active: bool
    notify_mode: str
    notify_subject: Optional[str]
    
    last_run: Optional[datetime]
    last_status: Optional[str]
    last_duration: Optional[int]
    last_transferred: Optional[str]
    last_error: Optional[str]
    run_count: int
    error_count: int
    consecutive_failures: int
    
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class MigrationJobResponseWithNodes(MigrationJobResponse):
    source_node_name: Optional[str] = None
    dest_node_name: Optional[str] = None


# ============== Helper Functions ==============

def check_job_access(user: User, job: MigrationJob, db: Session) -> bool:
    """Verifica se l'utente ha accesso al job"""
    if user.role == "admin":
        return True
    
    if user.allowed_nodes is None:
        return True
    
    return (job.source_node_id in user.allowed_nodes and 
            job.dest_node_id in user.allowed_nodes)


# ============== Background Task ==============

async def execute_migration_job_task(job_id: int, triggered_by: Optional[int] = None, force_overwrite: bool = True):
    """Esegue un job di migrazione in background
    
    Args:
        job_id: ID del job
        triggered_by: ID utente che ha avviato il job (None per schedulati)
        force_overwrite: Se True, elimina VM esistente senza conferma (default True per schedulati)
    """
    from database import SessionLocal
    
    db = SessionLocal()
    try:
        job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
        if not job:
            logger.error(f"[MIGRATION JOB] Job {job_id} non trovato nel database")
            return {"success": False, "message": f"Job {job_id} non trovato nel database"}
        
        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
        
        if not source_node or not dest_node:
            missing = []
            if not source_node:
                missing.append(f"source_node_id={job.source_node_id}")
            if not dest_node:
                missing.append(f"dest_node_id={job.dest_node_id}")
            logger.error(f"[MIGRATION JOB] Nodi non trovati per job {job_id}: {', '.join(missing)}")
            logger.error(f"[MIGRATION JOB] Job: {job.name}, VM: {job.vm_id}")
            return {"success": False, "message": f"Nodi non trovati: {', '.join(missing)}"}
        
        # Log dettagliato inizio job
        logger.info(f"[MIGRATION JOB] ========== INIZIO JOB {job_id} ==========")
        logger.info(f"[MIGRATION JOB] Nome: {job.name}")
        logger.info(f"[MIGRATION JOB] VM: {job.vm_id} ({job.vm_type}) - {job.vm_name or 'nome non disponibile'}")
        logger.info(f"[MIGRATION JOB] Sorgente: {source_node.name} ({source_node.hostname}:{source_node.ssh_port})")
        logger.info(f"[MIGRATION JOB] Destinazione: {dest_node.name} ({dest_node.hostname}:{dest_node.ssh_port})")
        logger.info(f"[MIGRATION JOB] Tipo migrazione: {job.migration_type}")
        logger.info(f"[MIGRATION JOB] VMID destinazione: {job.dest_vm_id or job.vm_id}")
        logger.info(f"[MIGRATION JOB] Avviato da: {'scheduler' if triggered_by is None else f'utente ID {triggered_by}'}")
        logger.info(f"[MIGRATION JOB] Force overwrite: {force_overwrite}")
        if job.hw_config:
            logger.info(f"[MIGRATION JOB] HW Config: {json.dumps(job.hw_config)}")
        
        # Crea log entry con dettagli
        log_entry = JobLog(
            job_type="migration",
            job_id=job_id,
            node_name=f"{source_node.name} → {dest_node.name}",
            status="started",
            message=f"Migrazione VM {job.vm_id} ({job.vm_name or 'N/A'}) da {source_node.name} a {dest_node.name} [{job.migration_type}]",
            started_at=datetime.utcnow(),
            triggered_by=triggered_by
        )
        db.add(log_entry)
        db.commit()
        
        start_time = datetime.utcnow()
        
        try:
            # Esegui migrazione
            result = await migration_service.migrate_vm(
                source_hostname=source_node.hostname,
                dest_hostname=dest_node.hostname,
                vm_id=job.vm_id,
                vm_type=job.vm_type,
                dest_vm_id=job.dest_vm_id,
                dest_vm_name_suffix=job.dest_vm_name_suffix,
                migration_type=job.migration_type,
                create_snapshot=job.create_snapshot,
                keep_snapshots=job.keep_snapshots,
                start_after=job.start_after_migration,
                hw_config=job.hw_config,
                source_port=source_node.ssh_port,
                source_user=source_node.ssh_user,
                source_key=source_node.ssh_key_path,
                dest_port=dest_node.ssh_port,
                dest_user=dest_node.ssh_user,
                dest_key=dest_node.ssh_key_path,
                force_overwrite=force_overwrite
            )
            
            # Se richiede conferma, ritorna senza aggiornare il job
            if result.get("requires_confirmation"):
                log_entry.status = "pending_confirmation"
                log_entry.message = result["message"]
                log_entry.completed_at = datetime.utcnow()
                db.commit()
                return result
            
            duration = int((datetime.utcnow() - start_time).total_seconds())
            
            if result["success"]:
                job.last_status = "success"
                job.last_duration = duration
                job.last_transferred = result.get("transferred", "0B")
                job.last_run = datetime.utcnow()
                job.run_count += 1
                job.consecutive_failures = 0
                job.last_error = None
                
                log_entry.status = "success"
                log_entry.message = result["message"]
                log_entry.duration = duration
                log_entry.transferred = result.get("transferred", "0B")
                log_entry.completed_at = datetime.utcnow()
                
                logger.info(f"[MIGRATION JOB] ========== JOB {job_id} COMPLETATO ==========")
                logger.info(f"[MIGRATION JOB] VM: {job.vm_id} -> {result.get('vm_id', job.dest_vm_id or job.vm_id)}")
                logger.info(f"[MIGRATION JOB] Durata: {duration}s")
                logger.info(f"[MIGRATION JOB] Trasferiti: {result.get('transferred', 'N/A')}")
                
                # Notifica
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="success",
                    source=f"{source_node.name}:vm/{job.vm_id}",
                    destination=f"{dest_node.name}:vm/{result.get('vm_id', job.dest_vm_id or job.vm_id)}",
                    duration=duration,
                    transferred=result.get("transferred", "0B"),
                    details=f"Migrazione completata: {result['message']}",
                    job_id=job_id,
                    notify_mode=job.notify_mode,
                    is_scheduled=bool(job.schedule),
                    job_type="migration",
                    source_node_name=source_node.name,
                    dest_node_name=dest_node.name,
                    vm_name=job.vm_name,
                    vm_id=job.vm_id
                )
            else:
                job.last_status = "failed"
                job.last_duration = duration
                
                # Costruisci messaggio di errore dettagliato
                error_details = []
                if result.get("phase"):
                    error_details.append(f"Fase: {result.get('phase')}")
                if result.get("exit_code"):
                    error_details.append(f"Exit code: {result.get('exit_code')}")
                if result.get("command"):
                    error_details.append(f"Comando: {result.get('command')[:200]}")
                if result.get("source_host"):
                    error_details.append(f"Source host: {result.get('source_host')}")
                if result.get("dest_host"):
                    error_details.append(f"Dest host: {result.get('dest_host')}")
                
                error_summary = result.get("error", result.get("message", "Errore sconosciuto"))
                if error_details:
                    error_summary = f"{error_summary}\n\nDettagli:\n" + "\n".join(error_details)
                
                job.last_error = error_summary[:1000]
                job.last_run = datetime.utcnow()
                job.run_count += 1
                job.error_count += 1
                job.consecutive_failures += 1
                
                # Log entry con output completo
                log_entry.status = "failed"
                log_entry.message = result.get("message", "Errore durante migrazione")
                
                # Includi full_output se disponibile
                full_error = result.get("error", "")
                if result.get("full_output"):
                    full_error = f"{full_error}\n\n=== OUTPUT COMPLETO ===\n{result.get('full_output')}"
                log_entry.error = full_error[:4000]  # Aumentato limite per più dettagli
                
                # Salva output separatamente se disponibile
                if result.get("full_output"):
                    log_entry.output = result.get("full_output")[:4000]
                
                log_entry.duration = duration
                log_entry.completed_at = datetime.utcnow()
                
                # Log più dettagliato
                logger.error(f"[MIGRATION JOB] Job {job_id} ({job.name}) FALLITO")
                logger.error(f"[MIGRATION JOB] VM: {job.vm_id} ({job.vm_type}) | {source_node.name} -> {dest_node.name}")
                if result.get("phase"):
                    logger.error(f"[MIGRATION JOB] Fase fallita: {result.get('phase')}")
                if result.get("command"):
                    logger.error(f"[MIGRATION JOB] Comando: {result.get('command')}")
                if result.get("exit_code"):
                    logger.error(f"[MIGRATION JOB] Exit code: {result.get('exit_code')}")
                logger.error(f"[MIGRATION JOB] Errore: {result.get('error', 'N/A')[:500]}")
                
                # Notifica errore
                await notification_service.send_job_notification(
                    job_name=job.name,
                    status="failed",
                    source=f"{source_node.name}:vm/{job.vm_id}",
                    destination=f"{dest_node.name}",
                    duration=duration,
                    error=result.get("error", result.get("message", "Errore sconosciuto")),
                    details="Migrazione fallita",
                    job_id=job_id,
                    notify_mode=job.notify_mode,
                    is_scheduled=bool(job.schedule),
                    job_type="migration",
                    source_node_name=source_node.name,
                    dest_node_name=dest_node.name,
                    vm_name=job.vm_name,
                    vm_id=job.vm_id
                )
            
            db.commit()
            
        except Exception as e:
            import traceback
            stack_trace = traceback.format_exc()
            
            logger.error(f"[MIGRATION JOB] ECCEZIONE durante job {job_id}")
            logger.error(f"[MIGRATION JOB] Job: {job.name}")
            logger.error(f"[MIGRATION JOB] VM: {job.vm_id} ({job.vm_type})")
            logger.error(f"[MIGRATION JOB] Source: {source_node.name} ({source_node.hostname})")
            logger.error(f"[MIGRATION JOB] Dest: {dest_node.name} ({dest_node.hostname})")
            logger.error(f"[MIGRATION JOB] Eccezione: {type(e).__name__}: {str(e)}")
            logger.error(f"[MIGRATION JOB] Stack trace:\n{stack_trace}")
            
            job.last_status = "failed"
            job.last_error = f"Eccezione {type(e).__name__}: {str(e)}"[:1000]
            job.error_count += 1
            job.consecutive_failures += 1
            
            log_entry.status = "failed"
            log_entry.message = f"Eccezione durante migrazione: {type(e).__name__}"
            log_entry.error = f"Errore: {str(e)}\n\nStack trace:\n{stack_trace}"[:4000]
            log_entry.completed_at = datetime.utcnow()
            
            db.commit()
            
    finally:
        db.close()


# ============== Endpoints ==============

@router.get("/", response_model=List[MigrationJobResponseWithNodes])
async def list_migration_jobs(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutti i job di migrazione"""
    jobs = db.query(MigrationJob).all()
    
    result = []
    for job in jobs:
        if not check_job_access(user, job, db):
            continue
        
        job_dict = MigrationJobResponse.model_validate(job).model_dump()
        
        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
        
        job_dict["source_node_name"] = source_node.name if source_node else None
        job_dict["dest_node_name"] = dest_node.name if dest_node else None
        
        result.append(MigrationJobResponseWithNodes(**job_dict))
    
    return result


@router.post("/", response_model=MigrationJobResponse)
async def create_migration_job(
    job: MigrationJobCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea un nuovo job di migrazione"""
    
    source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
    dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
    
    if not source_node or not dest_node:
        raise HTTPException(status_code=400, detail="Nodi non trovati")
    
    # Verifica accesso
    if user.allowed_nodes is not None:
        if job.source_node_id not in user.allowed_nodes:
            raise HTTPException(status_code=403, detail="Accesso negato al nodo sorgente")
        if job.dest_node_id not in user.allowed_nodes:
            raise HTTPException(status_code=403, detail="Accesso negato al nodo destinazione")
    
    # Ottieni nome VM
    vm_name = None
    try:
        guests = await proxmox_service.get_all_guests(
            hostname=source_node.hostname,
            port=source_node.ssh_port,
            username=source_node.ssh_user,
            key_path=source_node.ssh_key_path
        )
        for vm in guests:
            if vm.get("vmid") == job.vm_id:
                vm_name = vm.get("name")
                break
    except:
        pass
    
    # Crea job
    db_job = MigrationJob(
        name=job.name,
        source_node_id=job.source_node_id,
        vm_id=job.vm_id,
        vm_type=job.vm_type,
        vm_name=vm_name,
        dest_node_id=job.dest_node_id,
        dest_vm_id=job.dest_vm_id,
        dest_vm_name_suffix=job.dest_vm_name_suffix,
        migration_type=job.migration_type,
        create_snapshot=job.create_snapshot,
        keep_snapshots=job.keep_snapshots,
        start_after_migration=job.start_after_migration,
        hw_config=job.hw_config,
        schedule=job.schedule,
        notify_mode=job.notify_mode,
        notify_subject=job.notify_subject,
        created_by=user.id
    )
    
    db.add(db_job)
    
    log_audit(
        db, user.id, "migration_job_created", "migration_job",
        resource_id=db_job.id,
        details=f"Created migration job: {job.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    db.refresh(db_job)
    
    return db_job


@router.put("/{job_id}", response_model=MigrationJobResponse)
async def update_migration_job(
    job_id: int,
    update: MigrationJobUpdate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiorna un job di migrazione"""
    
    job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(job, key, value)
    
    job.updated_at = datetime.utcnow()
    
    log_audit(
        db, user.id, "migration_job_updated", "migration_job",
        resource_id=job_id,
        details=f"Updated migration job: {job.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    db.refresh(job)
    
    return job


@router.delete("/{job_id}")
async def delete_migration_job(
    job_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina un job di migrazione"""
    
    job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    log_audit(
        db, user.id, "migration_job_deleted", "migration_job",
        resource_id=job_id,
        details=f"Deleted migration job: {job.name}",
        ip_address=request.client.host if request.client else None
    )
    
    db.delete(job)
    db.commit()
    
    return {"success": True, "message": "Job eliminato"}


@router.post("/{job_id}/run")
async def run_migration_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    request: Request,
    force: bool = False,  # Se True, sovrascrive VM esistente senza conferma
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue manualmente un job di migrazione
    
    Args:
        force: Se True, elimina VM esistente senza chiedere conferma
    """
    
    job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    if job.last_status == "running":
        raise HTTPException(status_code=400, detail="Job già in esecuzione")
    
    # Per esecuzione manuale senza force, prima verifichiamo se serve conferma
    if not force:
        source_node = db.query(Node).filter(Node.id == job.source_node_id).first()
        dest_node = db.query(Node).filter(Node.id == job.dest_node_id).first()
        
        if source_node and dest_node:
            # Verifica se la VM destinazione esiste
            target_vmid = job.dest_vm_id if job.dest_vm_id else job.vm_id
            check_cmd = f"{'qm' if job.vm_type == 'qemu' else 'pct'} status {target_vmid} 2>/dev/null"
            
            from services.ssh_service import ssh_service
            check_result = await ssh_service.execute(
                hostname=dest_node.hostname,
                command=check_cmd,
                port=dest_node.ssh_port,
                username=dest_node.ssh_user,
                key_path=dest_node.ssh_key_path,
                timeout=30
            )
            
            if check_result.success and check_result.stdout.strip():
                # La VM esiste già - chiedi conferma
                return {
                    "success": False,
                    "requires_confirmation": True,
                    "message": f"La VM {target_vmid} esiste già su {dest_node.name}. Vuoi eliminarla e procedere con la migrazione?",
                    "existing_vm_id": target_vmid,
                    "dest_node": dest_node.name
                }
    
    job.last_status = "running"
    db.commit()
    
    # Esegui con force_overwrite=True (conferma già data o force=True)
    background_tasks.add_task(execute_migration_job_task, job_id, user.id, True)
    
    log_audit(
        db, user.id, "migration_job_run", "migration_job",
        resource_id=job_id,
        details=f"Manually triggered migration job: {job.name}" + (" (force overwrite)" if force else ""),
        ip_address=request.client.host if request.client else None
    )
    
    return {"success": True, "message": "Migrazione avviata"}


@router.post("/{job_id}/toggle")
async def toggle_migration_job(
    job_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Attiva/disattiva un job di migrazione"""
    
    job = db.query(MigrationJob).filter(MigrationJob.id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job non trovato")
    
    if not check_job_access(user, job, db):
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    job.is_active = not job.is_active
    db.commit()
    
    return {"success": True, "is_active": job.is_active}


