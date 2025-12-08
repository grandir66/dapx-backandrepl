"""
Router per gestione snapshot ZFS e configurazione Sanoid
Con autenticazione
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime
from pydantic import BaseModel
import logging

from database import get_db, Node, Dataset, User, JobLog, VMSnapshotConfig, SyncJob
from services.ssh_service import ssh_service
from services.sanoid_service import sanoid_service, DEFAULT_TEMPLATES
from routers.auth import get_current_user, require_operator, log_audit

router = APIRouter()
logger = logging.getLogger(__name__)


# ============== Schemas ==============

class DatasetConfigUpdate(BaseModel):
    sanoid_enabled: bool = False
    sanoid_template: str = "default"
    hourly: int = 24
    daily: int = 30
    weekly: int = 4
    monthly: int = 12
    yearly: int = 0
    autosnap: bool = True
    autoprune: bool = True


class SnapshotCreate(BaseModel):
    name: str
    recursive: bool = False


class SnapshotResponse(BaseModel):
    full_name: str
    dataset: str
    snapshot: str
    used: str
    creation: str


class TemplateResponse(BaseModel):
    name: str
    hourly: int
    daily: int
    weekly: int
    monthly: int
    yearly: int
    autosnap: bool
    autoprune: bool


# ============== Helper Functions ==============

def check_node_access(user: User, node: Node) -> bool:
    """Verifica se l'utente ha accesso al nodo"""
    if user.role == "admin":
        return True
    if user.allowed_nodes is None:
        return True
    return node.id in user.allowed_nodes


# ============== Endpoints ==============

@router.get("/templates", response_model=List[TemplateResponse])
async def get_templates(user: User = Depends(get_current_user)):
    """Ottiene i template Sanoid disponibili"""
    return [
        TemplateResponse(
            name=name,
            hourly=t.hourly,
            daily=t.daily,
            weekly=t.weekly,
            monthly=t.monthly,
            yearly=t.yearly,
            autosnap=t.autosnap,
            autoprune=t.autoprune
        )
        for name, t in DEFAULT_TEMPLATES.items()
    ]


@router.get("/node/{node_id}", response_model=List[SnapshotResponse])
async def get_node_snapshots(
    node_id: int,
    dataset: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene gli snapshot di un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    snapshots = await ssh_service.get_snapshots(
        hostname=node.hostname,
        dataset=dataset,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return [SnapshotResponse(**s) for s in snapshots]


@router.post("/node/{node_id}")
async def create_snapshot(
    node_id: int,
    dataset: str,
    snapshot_data: SnapshotCreate,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Crea uno snapshot manuale"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    result = await ssh_service.create_snapshot(
        hostname=node.hostname,
        dataset=dataset,
        snapshot_name=snapshot_data.name,
        recursive=snapshot_data.recursive,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if result.success:
        log_audit(
            db, user.id, "snapshot_created", "snapshot",
            details=f"Created {dataset}@{snapshot_data.name} on {node.name}",
            ip_address=request.client.host if request.client else None
        )
        return {"success": True, "message": f"Snapshot {dataset}@{snapshot_data.name} creato"}
    else:
        return {"success": False, "message": result.stderr}


@router.delete("/node/{node_id}")
async def delete_snapshot(
    node_id: int,
    full_name: str,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Elimina uno snapshot"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    result = await ssh_service.delete_snapshot(
        hostname=node.hostname,
        full_snapshot_name=full_name,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if result.success:
        log_audit(
            db, user.id, "snapshot_deleted", "snapshot",
            details=f"Deleted {full_name} on {node.name}",
            ip_address=request.client.host if request.client else None
        )
        return {"success": True, "message": f"Snapshot {full_name} eliminato"}
    else:
        return {"success": False, "message": result.stderr}


@router.post("/node/{node_id}/rollback")
async def rollback_snapshot(
    node_id: int,
    full_name: str,
    force: bool = False,
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Rollback di un dataset a uno snapshot.
    ATTENZIONE: Operazione distruttiva! Tutti i dati dopo lo snapshot verranno persi.
    
    Args:
        full_name: Nome completo snapshot (es: pool/dataset@snapshot)
        force: Se True, forza il rollback anche con snapshot più recenti (-r)
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    # Costruisci comando rollback
    force_flag = "-r" if force else ""
    cmd = f"zfs rollback {force_flag} {full_name}"
    
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        timeout=300
    )
    
    if result.success:
        log_audit(
            db, user.id, "snapshot_rollback", "snapshot",
            details=f"Rollback to {full_name} on {node.name}",
            ip_address=request.client.host if request.client else None
        )
        return {"success": True, "message": f"Rollback a {full_name} completato"}
    else:
        return {"success": False, "message": result.stderr or result.stdout}


@router.post("/node/{node_id}/clone")
async def clone_snapshot(
    node_id: int,
    full_name: str,
    clone_name: str,
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """
    Crea un clone da uno snapshot.
    Il clone è una copia scrivibile del dataset allo stato dello snapshot.
    Non distruttivo - l'originale rimane intatto.
    
    Args:
        full_name: Nome completo snapshot (es: pool/dataset@snapshot)
        clone_name: Nome del nuovo dataset clone (es: pool/dataset-clone)
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    # Costruisci comando clone
    cmd = f"zfs clone {full_name} {clone_name}"
    
    result = await ssh_service.execute(
        hostname=node.hostname,
        command=cmd,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        timeout=60
    )
    
    if result.success:
        log_audit(
            db, user.id, "snapshot_clone", "snapshot",
            details=f"Clone {full_name} -> {clone_name} on {node.name}",
            ip_address=request.client.host if request.client else None
        )
        return {"success": True, "message": f"Clone {clone_name} creato da {full_name}"}
    else:
        return {"success": False, "message": result.stderr or result.stdout}


@router.get("/vm/{node_id}/{vm_id}")
async def get_vm_snapshots(
    node_id: int,
    vm_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene tutti gli snapshot relativi a una VM.
    Cerca snapshot di dataset che contengono il VMID nel nome.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    # Ottieni tutti gli snapshot
    all_snapshots = await ssh_service.get_snapshots(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Filtra per VM ID (cerca vm-XXX nel nome del dataset)
    vm_pattern = f"vm-{vm_id}-"
    vm_snapshots = [
        s for s in all_snapshots 
        if vm_pattern in s["dataset"] or f"/{vm_id}/" in s["dataset"]
    ]
    
    # Raggruppa per dataset
    grouped = {}
    for snap in vm_snapshots:
        ds = snap["dataset"]
        if ds not in grouped:
            grouped[ds] = []
        grouped[ds].append(snap)
    
    return {
        "vm_id": vm_id,
        "node_name": node.name,
        "total_snapshots": len(vm_snapshots),
        "datasets": grouped
    }


@router.put("/dataset/{dataset_id}/config")
async def update_dataset_config(
    dataset_id: int,
    config: DatasetConfigUpdate,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiorna la configurazione Sanoid di un dataset"""
    dataset = db.query(Dataset).filter(Dataset.id == dataset_id).first()
    if not dataset:
        raise HTTPException(status_code=404, detail="Dataset non trovato")
    
    node = db.query(Node).filter(Node.id == dataset.node_id).first()
    if node and not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    for key, value in config.model_dump().items():
        setattr(dataset, key, value)
    
    dataset.last_updated = datetime.utcnow()
    db.commit()
    
    return {"message": "Configurazione aggiornata"}


@router.post("/node/{node_id}/apply-config")
async def apply_sanoid_config(
    node_id: int,
    request: Request,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Applica la configurazione Sanoid su un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    # Ottieni dataset configurati
    datasets = db.query(Dataset).filter(Dataset.node_id == node_id).all()
    
    # Genera configurazione
    dataset_configs = [
        {
            "name": ds.name,
            "sanoid_enabled": ds.sanoid_enabled,
            "sanoid_template": ds.sanoid_template,
            "hourly": ds.hourly,
            "daily": ds.daily,
            "weekly": ds.weekly,
            "monthly": ds.monthly,
            "yearly": ds.yearly,
            "autosnap": ds.autosnap,
            "autoprune": ds.autoprune
        }
        for ds in datasets
    ]
    
    config_content = sanoid_service.generate_config(dataset_configs)
    
    # Applica sul nodo
    result = await sanoid_service.set_config(
        hostname=node.hostname,
        config_content=config_content,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    if result.success:
        log_audit(
            db, user.id, "sanoid_config_applied", "node",
            resource_id=node_id,
            details=f"Applied Sanoid config on {node.name}",
            ip_address=request.client.host if request.client else None
        )
        return {"success": True, "message": "Configurazione applicata"}
    else:
        return {"success": False, "message": result.stderr}


@router.post("/node/{node_id}/run-sanoid")
async def run_sanoid(
    node_id: int,
    cron: bool = True,
    prune: bool = False,
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Esegue Sanoid manualmente su un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    result = await sanoid_service.run_sanoid(
        hostname=node.hostname,
        cron=cron,
        prune=prune,
        verbose=True,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Log operazione
    log_entry = JobLog(
        job_type="snapshot",
        node_name=node.name,
        status="success" if result.success else "failed",
        message="Sanoid manual run",
        output=result.stdout,
        error=result.stderr if not result.success else None,
        triggered_by=user.id
    )
    db.add(log_entry)
    db.commit()
    
    return {
        "success": result.success,
        "output": result.stdout,
        "error": result.stderr
    }


@router.get("/node/{node_id}/sanoid-config")
async def get_sanoid_config(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene la configurazione Sanoid attuale di un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    success, config = await sanoid_service.get_config(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    return {
        "success": success,
        "config": config
    }


@router.get("/stats/node/{node_id}")
async def get_node_snapshot_stats(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene statistiche sugli snapshot di un nodo"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    snapshots = await ssh_service.get_snapshots(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    # Conta per tipo (autosnap-hourly, autosnap-daily, etc.)
    type_counts = {}
    for snap in snapshots:
        name = snap["snapshot"]
        if "autosnap" in name:
            if "hourly" in name:
                snap_type = "hourly"
            elif "daily" in name:
                snap_type = "daily"
            elif "weekly" in name:
                snap_type = "weekly"
            elif "monthly" in name:
                snap_type = "monthly"
            elif "yearly" in name:
                snap_type = "yearly"
            else:
                snap_type = "other"
        else:
            snap_type = "manual"
        
        type_counts[snap_type] = type_counts.get(snap_type, 0) + 1
    
    # Dataset con più snapshot
    dataset_counts = {}
    for snap in snapshots:
        ds = snap["dataset"]
        dataset_counts[ds] = dataset_counts.get(ds, 0) + 1
    
    top_datasets = sorted(dataset_counts.items(), key=lambda x: x[1], reverse=True)[:5]
    
    return {
        "total_snapshots": len(snapshots),
        "by_type": type_counts,
        "top_datasets": [{"dataset": d, "count": c} for d, c in top_datasets]
    }


# ============== VM Snapshot Config ==============

class VMSnapshotConfigCreate(BaseModel):
    enabled: bool = False
    schedule: Optional[str] = None
    hourly: int = 0
    daily: int = 7
    weekly: int = 4
    monthly: int = 3
    yearly: int = 0
    template: str = "production"


class VMSnapshotConfigResponse(BaseModel):
    id: int
    node_id: int
    vm_id: int
    vm_type: str
    enabled: bool
    schedule: Optional[str]
    hourly: int
    daily: int
    weekly: int
    monthly: int
    yearly: int
    template: str
    
    class Config:
        from_attributes = True


@router.get("/vm/{node_id}/{vm_id}/config", response_model=VMSnapshotConfigResponse)
async def get_vm_snapshot_config(
    node_id: int,
    vm_id: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene la configurazione snapshot sanoid per una VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    config = db.query(VMSnapshotConfig).filter(
        VMSnapshotConfig.node_id == node_id,
        VMSnapshotConfig.vm_id == vm_id,
        VMSnapshotConfig.vm_type == vm_type
    ).first()
    
    if not config:
        # Crea config di default
        config = VMSnapshotConfig(
            node_id=node_id,
            vm_id=vm_id,
            vm_type=vm_type,
            enabled=False
        )
        db.add(config)
        db.commit()
        db.refresh(config)
    
    return config


@router.put("/vm/{node_id}/{vm_id}/config", response_model=VMSnapshotConfigResponse)
async def update_vm_snapshot_config(
    node_id: int,
    vm_id: int,
    vm_type: str = "qemu",
    config_data: VMSnapshotConfigCreate = None,
    request: Request = None,
    user: User = Depends(require_operator),
    db: Session = Depends(get_db)
):
    """Aggiorna la configurazione snapshot sanoid per una VM"""
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    config = db.query(VMSnapshotConfig).filter(
        VMSnapshotConfig.node_id == node_id,
        VMSnapshotConfig.vm_id == vm_id,
        VMSnapshotConfig.vm_type == vm_type
    ).first()
    
    if not config:
        config = VMSnapshotConfig(
            node_id=node_id,
            vm_id=vm_id,
            vm_type=vm_type
        )
        db.add(config)
    
    # Aggiorna valori
    if config_data:
        config.enabled = config_data.enabled
        config.schedule = config_data.schedule
        config.hourly = config_data.hourly
        config.daily = config_data.daily
        config.weekly = config_data.weekly
        config.monthly = config_data.monthly
        config.yearly = config_data.yearly
        config.template = config_data.template
    
    config.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(config)
    
    # Se abilitato, applica configurazione sanoid ai dataset della VM
    if config.enabled:
        from routers.vms import get_vm_datasets
        from services.sanoid_config_service import sanoid_config_service
        
        try:
            datasets_resp = await get_vm_datasets(node_id, vm_id, vm_type, user, db)
            if datasets_resp and datasets_resp.datasets:
                for dataset in datasets_resp.datasets:
                    await sanoid_config_service.add_dataset_config(
                        hostname=node.hostname,
                        dataset=dataset,
                        autosnap=True,
                        autoprune=True,
                        hourly=config.hourly,
                        daily=config.daily,
                        weekly=config.weekly,
                        monthly=config.monthly,
                        yearly=config.yearly,
                        port=node.ssh_port,
                        username=node.ssh_user,
                        key_path=node.ssh_key_path
                    )
        except Exception as e:
            logger.warning(f"Errore applicazione config sanoid: {e}")
    
    log_audit(
        db, user.id, "vm_snapshot_config_updated", "vm_snapshot_config",
        details=f"Updated snapshot config for VM {vm_id} on {node.name}",
        ip_address=request.client.host if request.client else None
    )
    
    return config


@router.get("/vm/{node_id}/{vm_id}/all")
async def get_vm_all_snapshots(
    node_id: int,
    vm_id: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene tutti gli snapshot di una VM: Proxmox + Sanoid"""
    # Snapshot Proxmox (usa la funzione esistente)
    proxmox_snaps = await get_vm_snapshots(node_id, vm_id, user, db)
    
    # Snapshot Sanoid (ZFS)
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    # Ottieni dataset della VM
    from routers.vms import get_vm_datasets
    datasets_resp = await get_vm_datasets(node_id, vm_id, vm_type, user, db)
    
    logger.info(f"VM {vm_id} on node {node_id}: datasets_resp={datasets_resp}")
    
    sanoid_snapshots = []
    syncoid_snapshots = []
    backup_snapshots = []
    datasets_to_check = set()
    seen_snapshots = set()  # Per evitare duplicati
    
    if datasets_resp and datasets_resp.datasets:
        logger.info(f"Found datasets for VM {vm_id}: {datasets_resp.datasets}")
        for dataset in datasets_resp.datasets:
            datasets_to_check.add((dataset, node_id))  # (dataset, node_id)
            
            # Se il dataset è una replica (es: zfs/replica/vm-667-disk-0), cerca anche sul dataset originale
            if '/replica/' in dataset:
                original_dataset = dataset.replace('/replica/', '/')
                datasets_to_check.add((original_dataset, node_id))
            elif dataset.startswith('replica/'):
                original_dataset = dataset.replace('replica/', '')
                datasets_to_check.add((original_dataset, node_id))
            
            # Cerca job di replica che hanno questo dataset come destinazione (replica verso questo dataset)
            replica_jobs_dest = db.query(SyncJob).filter(
                SyncJob.dest_dataset == dataset
            ).all()
            
            for job in replica_jobs_dest:
                # Aggiungi il dataset di destinazione del job (è quello che stiamo già controllando)
                datasets_to_check.add((job.dest_dataset, job.dest_node_id))
                # Aggiungi anche il dataset sorgente (per vedere snapshot originali)
                datasets_to_check.add((job.source_dataset, job.source_node_id))
            
            # Cerca anche job che replicano DA questo dataset (per trovare la destinazione)
            replica_jobs_source = db.query(SyncJob).filter(
                SyncJob.source_dataset == dataset
            ).all()
            
            for job in replica_jobs_source:
                # Aggiungi il dataset di destinazione (dove sono le snapshot della replica)
                datasets_to_check.add((job.dest_dataset, job.dest_node_id))
                # Aggiungi anche il dataset sorgente (quello che stiamo già controllando)
                datasets_to_check.add((job.source_dataset, job.source_node_id))
    
    # Cerca snapshot su tutti i dataset trovati (inclusi quelli originali se replica)
    for dataset, check_node_id in datasets_to_check:
        # Determina il nodo su cui cercare
        if check_node_id == node_id:
            check_node = node
        else:
            check_node = db.query(Node).filter(Node.id == check_node_id).first()
            if not check_node:
                continue
        
        # Cerca snapshot sul nodo specificato
        snaps = await ssh_service.get_snapshots(
            hostname=check_node.hostname,
            dataset=dataset,
            port=check_node.ssh_port,
            username=check_node.ssh_user,
            key_path=check_node.ssh_key_path
        )
        
        # Filtra snapshot per tipo (include tutte le snapshot del dataset)
        for snap in snaps:
            snap_full_name = snap.get('full_name', '')
            if snap_full_name in seen_snapshots:
                continue  # Evita duplicati
            seen_snapshots.add(snap_full_name)
            
            snap_name = snap.get('snapshot', '')
            if 'autosnap_' in snap_name:
                snap['source'] = 'sanoid'
                sanoid_snapshots.append(snap)
            elif 'syncoid_' in snap_name:
                snap['source'] = 'syncoid'
                syncoid_snapshots.append(snap)
            elif 'backup_' in snap_name:
                snap['source'] = 'backup'
                backup_snapshots.append(snap)
            else:
                # Snapshot senza prefisso specifico: aggiungi a backup (retention generica)
                snap['source'] = 'backup'
                backup_snapshots.append(snap)
    
    # Fallback: se non troviamo dataset, cerca job di replica che potrebbero essere associati
    if not datasets_resp or not datasets_resp.datasets:
        # Cerca job di replica che potrebbero essere associati a questa VM
        # Cerca pattern nel nome del dataset (es: vm-710 o vm-667)
        vm_pattern = f"vm-{vm_id}"
        all_sync_jobs = db.query(SyncJob).filter(
            (SyncJob.source_dataset.like(f"%{vm_pattern}%")) |
            (SyncJob.dest_dataset.like(f"%{vm_pattern}%"))
        ).all()
        
        for job in all_sync_jobs:
            # Aggiungi entrambi i dataset del job
            datasets_to_check.add((job.source_dataset, job.source_node_id))
            datasets_to_check.add((job.dest_dataset, job.dest_node_id))
        
        # Cerca snapshot su tutti i dataset trovati dai job
        for dataset, check_node_id in datasets_to_check:
            if check_node_id == node_id:
                check_node = node
            else:
                check_node = db.query(Node).filter(Node.id == check_node_id).first()
                if not check_node:
                    continue
            
            snaps = await ssh_service.get_snapshots(
                hostname=check_node.hostname,
                dataset=dataset,
                port=check_node.ssh_port,
                username=check_node.ssh_user,
                key_path=check_node.ssh_key_path
            )
            
            for snap in snaps:
                snap_full_name = snap.get('full_name', '')
                if snap_full_name in seen_snapshots:
                    continue
                seen_snapshots.add(snap_full_name)
                
                snap_name = snap.get('snapshot', '')
                if 'autosnap_' in snap_name:
                    snap['source'] = 'sanoid'
                    sanoid_snapshots.append(snap)
                elif 'syncoid_' in snap_name:
                    snap['source'] = 'syncoid'
                    syncoid_snapshots.append(snap)
                elif 'backup_' in snap_name:
                    snap['source'] = 'backup'
                    backup_snapshots.append(snap)
                else:
                    snap['source'] = 'backup'
                    backup_snapshots.append(snap)
        
        # Fallback finale: cerca pattern vm-XXX- direttamente
        all_snapshots = await ssh_service.get_snapshots(
            hostname=node.hostname,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
        
        vm_pattern = f"vm-{vm_id}-"
        for snap in all_snapshots:
            dataset = snap.get('dataset', '')
            if vm_pattern in dataset or f"/{vm_id}/" in dataset:
                snap_full_name = snap.get('full_name', '')
                if snap_full_name in seen_snapshots:
                    continue
                seen_snapshots.add(snap_full_name)
                
                snap_name = snap.get('snapshot', '')
                if 'autosnap_' in snap_name:
                    snap['source'] = 'sanoid'
                    sanoid_snapshots.append(snap)
                elif 'syncoid_' in snap_name:
                    snap['source'] = 'syncoid'
                    syncoid_snapshots.append(snap)
                elif 'backup_' in snap_name:
                    snap['source'] = 'backup'
                    backup_snapshots.append(snap)
    
    return {
        "vm_id": vm_id,
        "node_name": node.name,
        "proxmox_snapshots": proxmox_snaps,
        "sanoid_snapshots": sanoid_snapshots,
        "syncoid_snapshots": syncoid_snapshots,
        "backup_snapshots": backup_snapshots,
        "total": proxmox_snaps.get("total_snapshots", 0) + len(sanoid_snapshots) + len(syncoid_snapshots) + len(backup_snapshots)
    }
