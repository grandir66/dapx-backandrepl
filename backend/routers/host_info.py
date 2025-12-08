"""
Router per informazioni dettagliate host Proxmox
Espone dati hardware, storage, network raccolti da host_info_service
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import logging
import json
import re

from database import get_db, Node, User
from services.host_info_service import host_info_service
from services.proxmox_service import proxmox_service
from services.ssh_service import ssh_service
from routers.auth import get_current_user
from routers.nodes import check_node_access

router = APIRouter()
logger = logging.getLogger(__name__)


# ============== Schemas ==============

class HostDetailsResponse(BaseModel):
    """Risposta con dettagli host"""
    node_id: int
    node_name: str
    hostname: str
    timestamp: str
    proxmox_version: Optional[str] = None
    kernel_version: Optional[str] = None
    uptime_seconds: Optional[int] = None
    cpu: Dict[str, Any] = {}
    memory: Dict[str, Any] = {}
    storage: List[Dict[str, Any]] = []
    network: List[Dict[str, Any]] = []
    temperature: Dict[str, Any] = {}
    license: Dict[str, Any] = {}


class VMFullDetailsResponse(BaseModel):
    """Risposta con dettagli completi VM"""
    vmid: int
    name: str
    node_id: int
    node_name: str
    vm_type: str
    status: str
    config: Dict[str, Any] = {}
    runtime: Dict[str, Any] = {}
    disks: List[Dict[str, Any]] = []
    networks: List[Dict[str, Any]] = []
    ip_addresses: Dict[str, List[str]] = {}
    snapshots: Dict[str, Any] = {}
    agent: Dict[str, Any] = {}
    # Campi aggiuntivi opzionali
    bios: Optional[str] = None
    ostype: Optional[str] = None
    boot: Optional[str] = None
    agent_enabled: Optional[bool] = None
    primary_bridge: Optional[str] = None
    primary_ip: Optional[str] = None
    tags: Optional[str] = None
    
    class Config:
        extra = "allow"  # Permette campi aggiuntivi


class DashboardOverviewResponse(BaseModel):
    """Risposta overview dashboard"""
    total_nodes: int
    online_nodes: int
    total_vms: int
    running_vms: int
    total_storage_gb: float
    used_storage_gb: float
    total_memory_gb: float
    used_memory_gb: float
    total_cpu_cores: int
    nodes_summary: List[Dict[str, Any]] = []
    job_stats: Dict[str, Any] = {}
    recent_logs: List[Dict[str, Any]] = []


# ============== Endpoints ==============

@router.get("/nodes/{node_id}/host-details", response_model=HostDetailsResponse)
async def get_node_host_details(
    node_id: int,
    include_hardware: bool = True,
    include_storage: bool = True,
    include_network: bool = True,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene dettagli completi dell'host Proxmox.
    Include hardware, storage, network, temperatura, licenza.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    if node.node_type != "pve":
        raise HTTPException(status_code=400, detail="Endpoint disponibile solo per nodi PVE")
    
    # Raccolta dati host
    host_details = await host_info_service.get_host_details(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path,
        include_hardware=include_hardware,
        include_storage=include_storage,
        include_network=include_network
    )
    
    # Aggiungi node_id e node_name
    host_details["node_id"] = node_id
    host_details["node_name"] = node.name
    
    return HostDetailsResponse(**host_details)


@router.get("/nodes/{node_id}/vms/{vmid}/full-details", response_model=VMFullDetailsResponse)
async def get_vm_full_details(
    node_id: int,
    vmid: int,
    vm_type: str = "qemu",
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene dettagli completi di una VM.
    Include config, runtime stats, dischi, network, IP, snapshot, agent.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    if node.node_type != "pve":
        raise HTTPException(status_code=400, detail="Endpoint disponibile solo per nodi PVE")
    
    try:
        # Ottieni dettagli completi VM usando il nuovo metodo
        vm_details = await proxmox_service.get_vm_full_details(
            hostname=node.hostname,
            node_name=node.name,
            vmid=vmid,
            vm_type=vm_type,
            port=node.ssh_port,
            username=node.ssh_user,
            key_path=node.ssh_key_path
        )
        
        # Verifica che la VM esista (se status è unknown e non ci sono dati, probabilmente non esiste)
        if vm_details.get("status") == "unknown" and not vm_details.get("config"):
            # Verifica esistenza con lista VM
            vms = await proxmox_service.get_all_guests(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            
            vm_found = next((vm for vm in vms if vm.get("vmid") == vmid and vm.get("type") == vm_type), None)
            if not vm_found:
                raise HTTPException(status_code=404, detail="VM non trovata")
        
        # Aggiungi node_id e node_name
        vm_details["node_id"] = node_id
        vm_details["node_name"] = node.name
        
        try:
            return VMFullDetailsResponse(**vm_details)
        except Exception as e:
            logger.error(f"Errore serializzazione VM details per VM {vmid}: {e}", exc_info=True)
            logger.error(f"Campi disponibili: {list(vm_details.keys())}")
            # Prova a restituire comunque i dati, anche se non perfettamente validati
            # Converti in dict per evitare problemi di serializzazione
            return vm_details
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Errore recupero dettagli VM {vmid} su nodo {node_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Errore recupero dettagli VM: {str(e)}")


@router.get("/dashboard/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene overview aggregata per dashboard.
    Include statistiche totali e summary nodi.
    """
    # Ottieni nodi accessibili
    from routers.nodes import filter_nodes_for_user
    nodes_query = db.query(Node).filter(Node.is_active == True)
    nodes = filter_nodes_for_user(db, user, nodes_query).all()
    
    total_nodes = len(nodes)
    online_nodes = sum(1 for n in nodes if n.is_online)
    
    # Aggrega dati da tutti i nodi
    total_vms = 0
    running_vms = 0
    total_storage_gb = 0.0
    used_storage_gb = 0.0
    total_memory_gb = 0.0
    used_memory_gb = 0.0
    total_cpu_cores = 0
    nodes_summary = []
    
    # Traccia storage condivisi già contati (per evitare duplicati)
    counted_shared_storage = set()
    
    for node in nodes:
        if not node.is_online or node.node_type != "pve":
            continue
        
        try:
            # Raccolta dati host (solo summary, senza dettagli completi)
            host_details = await host_info_service.get_host_details(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path,
                include_hardware=True,
                include_storage=True,
                include_network=False  # Skip network per performance
            )
            
            # Aggrega storage (deduplicando storage condivisi)
            node_storage_total = 0.0
            node_storage_used = 0.0
            for storage in host_details.get("storage", []):
                storage_name = storage.get("name", "")
                is_shared = storage.get("shared", False)
                
                # Per il singolo nodo, conta tutto
                if storage.get("total_gb"):
                    node_storage_total += storage["total_gb"]
                if storage.get("used_gb"):
                    node_storage_used += storage["used_gb"]
                
                # Per il totale globale, conta shared solo una volta
                if is_shared:
                    if storage_name not in counted_shared_storage:
                        counted_shared_storage.add(storage_name)
                        if storage.get("total_gb"):
                            total_storage_gb += storage["total_gb"]
                        if storage.get("used_gb"):
                            used_storage_gb += storage["used_gb"]
                else:
                    # Storage locale: conta sempre
                    if storage.get("total_gb"):
                        total_storage_gb += storage["total_gb"]
                    if storage.get("used_gb"):
                        used_storage_gb += storage["used_gb"]
            
            # Aggrega memory
            if host_details.get("memory", {}).get("total_gb"):
                total_memory_gb += host_details["memory"]["total_gb"]
            if host_details.get("memory", {}).get("used_gb"):
                used_memory_gb += host_details["memory"]["used_gb"]
            
            # Aggrega CPU
            if host_details.get("cpu", {}).get("cores"):
                total_cpu_cores += host_details["cpu"]["cores"]
            
            # Conta VM
            vms = await proxmox_service.get_all_guests(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            
            total_vms += len(vms)
            running_vms += sum(1 for vm in vms if vm.get("status", "").lower() == "running")
            
            # Summary nodo (mostra tutto lo storage del nodo, non deduplicato)
            nodes_summary.append({
                "node_id": node.id,
                "node_name": node.name,
                "hostname": node.hostname,
                "is_online": node.is_online,
                "cpu_cores": host_details.get("cpu", {}).get("cores", 0),
                "memory_total_gb": host_details.get("memory", {}).get("total_gb", 0),
                "memory_used_gb": host_details.get("memory", {}).get("used_gb", 0),
                "storage_total_gb": round(node_storage_total, 2),
                "storage_used_gb": round(node_storage_used, 2),
                "vm_count": len(vms),
                "running_vm_count": sum(1 for vm in vms if vm.get("status", "").lower() == "running"),
                "temperature_highest_c": host_details.get("temperature", {}).get("highest_c"),
                "proxmox_version": host_details.get("proxmox_version")
            })
        except Exception as e:
            # Skip nodi con errori
            logger.error(f"Errore raccolta dati nodo {node.name}: {e}")
            continue
    
    # Ottieni statistiche job
    from database import SyncJob, BackupJob, RecoveryJob, MigrationJob
    sync_jobs = db.query(SyncJob).filter(SyncJob.is_active == True).all()
    backup_jobs = db.query(BackupJob).filter(BackupJob.is_active == True).all()
    recovery_jobs = db.query(RecoveryJob).filter(RecoveryJob.is_active == True).all()
    migration_jobs = db.query(MigrationJob).filter(MigrationJob.is_active == True).all()
    
    job_stats = {
        "replica_zfs": sum(1 for j in sync_jobs if j.sync_method == "syncoid"),
        "replica_btrfs": sum(1 for j in sync_jobs if j.sync_method == "btrfs_send"),
        "backup_pbs": len(backup_jobs),
        "replica_pbs": len(recovery_jobs),
        "migration": len(migration_jobs),
        "total": len(sync_jobs) + len(backup_jobs) + len(recovery_jobs) + len(migration_jobs)
    }
    
    # Ottieni log recenti
    from database import JobLog
    recent_logs_query = db.query(JobLog).order_by(JobLog.started_at.desc()).limit(10)
    recent_logs = []
    for log in recent_logs_query.all():
        recent_logs.append({
            "id": log.id,
            "job_type": log.job_type,
            "job_name": log.job_name,
            "status": log.status,
            "started_at": log.started_at.isoformat() if log.started_at else None,
            "duration": log.duration,
            "node_name": log.node_name,
            "message": log.message[:200] if log.message else None
        })
    
    return DashboardOverviewResponse(
        total_nodes=total_nodes,
        online_nodes=online_nodes,
        total_vms=total_vms,
        running_vms=running_vms,
        total_storage_gb=round(total_storage_gb, 2),
        used_storage_gb=round(used_storage_gb, 2),
        total_memory_gb=round(total_memory_gb, 2),
        used_memory_gb=round(used_memory_gb, 2),
        total_cpu_cores=total_cpu_cores,
        nodes_summary=nodes_summary,
        job_stats=job_stats,
        recent_logs=recent_logs
    )


@router.get("/dashboard/nodes", response_model=List[Dict[str, Any]])
async def get_dashboard_nodes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene lista nodi con summary per dashboard.
    Restituisce dati nel formato compatibile con il frontend.
    """
    from routers.nodes import filter_nodes_for_user
    nodes_query = db.query(Node).filter(Node.is_active == True)
    nodes = filter_nodes_for_user(db, user, nodes_query).all()
    
    nodes_list = []
    for node in nodes:
        node_summary = {
            "id": node.id,
            "name": node.name,
            "hostname": node.hostname,
            "node_type": node.node_type,
            "is_online": node.is_online,
            "last_check": node.last_check.isoformat() if node.last_check else None,
            # Inizializza campi con valori di default
            "proxmox_version": None,
            "cpu": {},
            "memory": {},
            "storage": [],
            "temperature": {},
            "storage_total_gb": 0,
            "storage_used_gb": 0,
            "vm_count": 0,
            "running_vm_count": 0,
            "temperature_highest_c": None
        }
        
        # Se online, aggiungi summary dati
        if node.is_online and node.node_type == "pve":
            try:
                host_details = await host_info_service.get_host_details(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path,
                    include_hardware=True,
                    include_storage=True,
                    include_network=False
                )
                
                # Conta VM
                vms = await proxmox_service.get_all_guests(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path
                )
                
                # Calcola storage totale e usato
                storage_list = host_details.get("storage", [])
                storage_total_gb = sum((s.get("total_gb") or 0) for s in storage_list)
                storage_used_gb = sum((s.get("used_gb") or 0) for s in storage_list)
                
                # Aggiorna summary con dati raccolti
                cpu_data = host_details.get("cpu", {})
                memory_data = host_details.get("memory", {})
                temperature_data = host_details.get("temperature", {})
                
                node_summary.update({
                    "proxmox_version": host_details.get("proxmox_version"),
                    "cpu": cpu_data,
                    "memory": memory_data,
                    "storage": host_details.get("storage", []),
                    "temperature": temperature_data,
                    # Campi aggiuntivi per compatibilità frontend
                    "storage_total_gb": round(storage_total_gb, 2) if storage_total_gb > 0 else 0,
                    "storage_used_gb": round(storage_used_gb, 2) if storage_used_gb > 0 else 0,
                    "vm_count": len(vms) if vms else 0,
                    "running_vm_count": sum(1 for vm in vms if vm.get("status", "").lower() == "running") if vms else 0,
                    "temperature_highest_c": temperature_data.get("highest_c") if temperature_data else None
                })
                
                logger.debug(f"Nodo {node.name}: {len(vms) if vms else 0} VM totali, {node_summary['running_vm_count']} running, storage: {storage_total_gb}GB")
            except Exception as e:
                # In caso di errore, mantieni i valori di default (None)
                logger.error(f"Errore raccolta dati per nodo {node.id} ({node.name}): {e}", exc_info=True)
        
        nodes_list.append(node_summary)
    
    return nodes_list


@router.get("/nodes/{node_id}/metrics")
async def get_node_metrics(
    node_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene metriche di performance in tempo reale per un nodo.
    Include CPU usage, RAM usage, Network I/O, Disk I/O.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail="Nodo non trovato")
    
    if not check_node_access(user, node):
        raise HTTPException(status_code=403, detail="Accesso negato a questo nodo")
    
    if node.node_type != "pve":
        raise HTTPException(status_code=400, detail="Endpoint disponibile solo per nodi PVE")
    
    if not node.is_online:
        raise HTTPException(status_code=400, detail="Nodo non online")
    
    metrics = await host_info_service.get_node_metrics(
        hostname=node.hostname,
        port=node.ssh_port,
        username=node.ssh_user,
        key_path=node.ssh_key_path
    )
    
    metrics["node_id"] = node_id
    metrics["node_name"] = node.name
    
    return metrics


@router.get("/dashboard/nodes-metrics")
async def get_all_nodes_metrics(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene metriche di performance per tutti i nodi online.
    Ottimizzato per dashboard con chiamate parallele.
    """
    from routers.nodes import filter_nodes_for_user
    nodes_query = db.query(Node).filter(Node.is_active == True, Node.node_type == "pve", Node.is_online == True)
    nodes = filter_nodes_for_user(db, user, nodes_query).all()
    
    import asyncio
    
    async def get_metrics_for_node(node):
        try:
            metrics = await host_info_service.get_node_metrics(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            metrics["node_id"] = node.id
            metrics["node_name"] = node.name
            return metrics
        except Exception as e:
            logger.error(f"Errore metriche nodo {node.name}: {e}")
            return {
                "node_id": node.id,
                "node_name": node.name,
                "error": str(e)
            }
    
    # Raccogli metriche in parallelo
    tasks = [get_metrics_for_node(node) for node in nodes]
    all_metrics = await asyncio.gather(*tasks, return_exceptions=True)
    
    # Filtra errori
    result = []
    for metrics in all_metrics:
        if isinstance(metrics, Exception):
            continue
        if "error" not in metrics:
            result.append(metrics)
    
    return result


@router.get("/dashboard/job-stats")
async def get_dashboard_job_stats(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene statistiche job per tipo (replica ZFS, replica BTRFS, backup PBS, replica PBS, migrazione).
    """
    from database import SyncJob, BackupJob, RecoveryJob, MigrationJob
    
    # Filtra job accessibili all'utente
    sync_jobs = db.query(SyncJob).filter(SyncJob.is_active == True).all()
    backup_jobs = db.query(BackupJob).filter(BackupJob.is_active == True).all()
    recovery_jobs = db.query(RecoveryJob).filter(RecoveryJob.is_active == True).all()
    migration_jobs = db.query(MigrationJob).filter(MigrationJob.is_active == True).all()
    
    # Conta per tipo
    stats = {
        "replica_zfs": 0,
        "replica_btrfs": 0,
        "backup_pbs": len(backup_jobs),
        "replica_pbs": len(recovery_jobs),
        "migration": len(migration_jobs),
        "total": 0
    }
    
    # Conta replica ZFS e BTRFS
    for job in sync_jobs:
        if job.sync_method == "syncoid":
            stats["replica_zfs"] += 1
        elif job.sync_method == "btrfs_send":
            stats["replica_btrfs"] += 1
    
    stats["total"] = stats["replica_zfs"] + stats["replica_btrfs"] + stats["backup_pbs"] + stats["replica_pbs"] + stats["migration"]
    
    # Statistiche per stato
    stats["by_status"] = {
        "success": 0,
        "failed": 0,
        "running": 0,
        "pending": 0
    }
    
    # Conta stati per tipo job
    for job in sync_jobs:
        if job.last_status == "success":
            stats["by_status"]["success"] += 1
        elif job.last_status == "failed":
            stats["by_status"]["failed"] += 1
        elif job.last_status == "running":
            stats["by_status"]["running"] += 1
        else:
            stats["by_status"]["pending"] += 1
    
    for job in backup_jobs + recovery_jobs + migration_jobs:
        status = getattr(job, 'last_status', None) or "pending"
        if status == "success":
            stats["by_status"]["success"] += 1
        elif status == "failed":
            stats["by_status"]["failed"] += 1
        elif status == "running":
            stats["by_status"]["running"] += 1
        else:
            stats["by_status"]["pending"] += 1
    
    return stats


@router.get("/dashboard/vms", response_model=List[Dict[str, Any]])
async def get_dashboard_vms(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene lista VM aggregate da tutti i nodi per dashboard.
    OTTIMIZZATO: usa chiamate batch per nodo con tutti i dati necessari.
    """
    from routers.nodes import filter_nodes_for_user
    nodes_query = db.query(Node).filter(Node.is_active == True, Node.node_type == "pve")
    nodes = filter_nodes_for_user(db, user, nodes_query).all()
    
    all_vms = []
    for node in nodes:
        if not node.is_online:
            continue
        
        try:
            # Ottieni hostname del nodo Proxmox
            node_name_result = await ssh_service.execute(
                hostname=node.hostname,
                command="hostname",
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            pve_node_name = node_name_result.stdout.strip() if node_name_result.success else node.hostname
            
            # Script batch ottimizzato che raccoglie TUTTI i dati in una sola chiamata SSH
            batch_cmd = f'''
NODE="{pve_node_name}"
# QEMU VMs
for vmid in $(qm list 2>/dev/null | tail -n +2 | awk '{{print $1}}'); do
    # Status e uptime via pvesh (JSON)
    status_json=$(pvesh get /nodes/$NODE/qemu/$vmid/status/current --output-format json 2>/dev/null)
    status=$(echo "$status_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
    uptime=$(echo "$status_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('uptime',0))" 2>/dev/null || echo "0")
    maxmem=$(echo "$status_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('maxmem',0))" 2>/dev/null || echo "0")
    agent=$(echo "$status_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('agent',0))" 2>/dev/null || echo "0")
    
    # Config per nome, CPU, dischi
    config=$(qm config $vmid 2>/dev/null)
    name=$(echo "$config" | grep -E "^name:" | cut -d" " -f2-)
    cores=$(echo "$config" | grep -E "^cores:" | awk '{{print $2}}')
    sockets=$(echo "$config" | grep -E "^sockets:" | awk '{{print $2}}')
    
    # Calcola disk size (somma tutti i dischi)
    disk_gb=$(echo "$config" | grep -E "^(scsi|sata|virtio|ide)[0-9]+:" | grep -oE "size=[0-9]+[GMTK]?" | sed "s/size=//" | while read sz; do
        num=$(echo "$sz" | grep -oE "[0-9]+")
        unit=$(echo "$sz" | grep -oE "[GMTK]" || echo "G")
        case $unit in
            T) echo "$num * 1024" | bc ;;
            G) echo "$num" ;;
            M) echo "scale=2; $num / 1024" | bc ;;
            K) echo "scale=2; $num / 1048576" | bc ;;
            *) echo "$num" ;;
        esac
    done | awk '{{sum+=$1}} END {{print sum}}')
    
    # IP via agent (solo se running e agent abilitato)
    ip=""
    if [ "$status" = "running" ] && [ "$agent" != "0" ]; then
        ip=$(pvesh get /nodes/$NODE/qemu/$vmid/agent/network-get-interfaces --output-format json 2>/dev/null | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    for iface in d.get('result',[]):
        for addr in iface.get('ip-addresses',[]):
            ip=addr.get('ip-address','')
            if ip and ip not in ['127.0.0.1','::1'] and ':' not in ip:
                print(ip)
                sys.exit(0)
except: pass
" 2>/dev/null)
    fi
    
    echo "VM|$vmid|qemu|$status|$name|${{cores:-1}}|${{sockets:-1}}|$maxmem|$uptime|${{disk_gb:-0}}|$ip"
done

# LXC Containers
for vmid in $(pct list 2>/dev/null | tail -n +2 | awk '{{print $1}}'); do
    status_json=$(pvesh get /nodes/$NODE/lxc/$vmid/status/current --output-format json 2>/dev/null)
    status=$(echo "$status_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('status','unknown'))" 2>/dev/null || echo "unknown")
    uptime=$(echo "$status_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('uptime',0))" 2>/dev/null || echo "0")
    maxmem=$(echo "$status_json" | python3 -c "import sys,json; d=json.load(sys.stdin); print(d.get('maxmem',0))" 2>/dev/null || echo "0")
    
    config=$(pct config $vmid 2>/dev/null)
    name=$(echo "$config" | grep -E "^hostname:" | cut -d" " -f2-)
    cores=$(echo "$config" | grep -E "^cores:" | awk '{{print $2}}')
    
    # Disk per LXC (rootfs)
    disk_gb=$(echo "$config" | grep -E "^rootfs:" | grep -oE "size=[0-9]+[GMTK]?" | sed "s/size=//" | head -1)
    disk_num=$(echo "$disk_gb" | grep -oE "[0-9]+" || echo "0")
    
    # IP per LXC
    ip=""
    if [ "$status" = "running" ]; then
        ip=$(pct exec $vmid -- ip -4 addr show 2>/dev/null | grep -oE "inet [0-9.]+" | grep -v "127.0.0.1" | head -1 | awk '{{print $2}}')
    fi
    
    echo "VM|$vmid|lxc|$status|$name|${{cores:-1}}|1|$maxmem|$uptime|${{disk_num:-0}}|$ip"
done
'''
            result = await ssh_service.execute(
                hostname=node.hostname,
                command=batch_cmd,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path,
                timeout=120  # Timeout più lungo per cluster grandi
            )
            
            if result.success:
                for line in result.stdout.splitlines():
                    if line.startswith("VM|"):
                        parts = line.split("|")
                        if len(parts) >= 11:
                            vmid = parts[1]
                            vm_type = parts[2]
                            status = parts[3] or "unknown"
                            name = parts[4] or f"VM-{vmid}"
                            cores = int(parts[5] or 1)
                            sockets = int(parts[6] or 1)
                            maxmem = int(parts[7] or 0)
                            uptime = int(parts[8] or 0)
                            disk_gb = float(parts[9] or 0)
                            primary_ip = parts[10] if len(parts) > 10 else ""
                            
                            all_vms.append({
                                "vmid": int(vmid),
                                "name": name,
                                "type": vm_type,
                                "status": status,
                                "node_id": node.id,
                                "node_name": node.name,
                                "hostname": node.hostname,
                                "cpu_cores": cores * sockets,
                                "memory_gb": round(maxmem / (1024**3), 2) if maxmem else None,
                                "disk_size": int(disk_gb * (1024**3)) if disk_gb else None,
                                "uptime_seconds": uptime if uptime else None,
                                "primary_ip": primary_ip if primary_ip else None
                            })
            else:
                # Fallback
                vms = await proxmox_service.get_all_guests(
                    hostname=node.hostname,
                    port=node.ssh_port,
                    username=node.ssh_user,
                    key_path=node.ssh_key_path
                )
                for vm in vms:
                    all_vms.append({
                        "vmid": vm.get("vmid"),
                        "name": vm.get("name", f"VM-{vm.get('vmid')}"),
                        "type": vm.get("type", "qemu"),
                        "status": vm.get("status", "unknown"),
                        "node_id": node.id,
                        "node_name": node.name,
                        "hostname": node.hostname,
                        "cpu_cores": vm.get("cpus"),
                        "memory_gb": round(vm.get("maxmem", 0) / (1024**3), 2) if vm.get("maxmem") else None,
                        "disk_size": None,
                        "uptime_seconds": None,
                        "primary_ip": None
                    })
        except Exception as e:
            logger.error(f"Errore raccolta VM per nodo {node.id} ({node.name}): {e}", exc_info=True)
            continue
    
    return all_vms

