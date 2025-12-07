"""
Router per informazioni dettagliate host Proxmox
Espone dati hardware, storage, network raccolti da host_info_service
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional, Dict, Any
from pydantic import BaseModel

from database import get_db, Node, User
from services.host_info_service import host_info_service
from services.proxmox_service import proxmox_service
from routers.auth import get_current_user
from routers.nodes import check_node_access

router = APIRouter()


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
    
    return VMFullDetailsResponse(**vm_details)


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
            
            # Aggrega storage
            for storage in host_details.get("storage", []):
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
            
            # Summary nodo
            nodes_summary.append({
                "node_id": node.id,
                "node_name": node.name,
                "hostname": node.hostname,
                "is_online": node.is_online,
                "cpu_cores": host_details.get("cpu", {}).get("cores", 0),
                "memory_total_gb": host_details.get("memory", {}).get("total_gb", 0),
                "memory_used_gb": host_details.get("memory", {}).get("used_gb", 0),
                "storage_total_gb": sum(s.get("total_gb", 0) for s in host_details.get("storage", [])),
                "storage_used_gb": sum(s.get("used_gb", 0) for s in host_details.get("storage", [])),
                "vm_count": len(vms),
                "running_vm_count": sum(1 for vm in vms if vm.get("status", "").lower() == "running"),
                "temperature_highest_c": host_details.get("temperature", {}).get("highest_c"),
                "proxmox_version": host_details.get("proxmox_version")
            })
        except Exception as e:
            # Skip nodi con errori
            continue
    
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
        nodes_summary=nodes_summary
    )


@router.get("/dashboard/nodes", response_model=List[Dict[str, Any]])
async def get_dashboard_nodes(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene lista nodi con summary per dashboard.
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
            "last_check": node.last_check.isoformat() if node.last_check else None
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
                
                node_summary.update({
                    "proxmox_version": host_details.get("proxmox_version"),
                    "cpu": host_details.get("cpu", {}),
                    "memory": host_details.get("memory", {}),
                    "storage": host_details.get("storage", []),
                    "temperature": host_details.get("temperature", {})
                })
            except:
                pass
        
        nodes_list.append(node_summary)
    
    return nodes_list


@router.get("/dashboard/vms", response_model=List[Dict[str, Any]])
async def get_dashboard_vms(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """
    Ottiene lista VM aggregate da tutti i nodi per dashboard.
    """
    from routers.nodes import filter_nodes_for_user
    nodes_query = db.query(Node).filter(Node.is_active == True, Node.node_type == "pve")
    nodes = filter_nodes_for_user(db, user, nodes_query).all()
    
    all_vms = []
    for node in nodes:
        if not node.is_online:
            continue
        
        try:
            vms = await proxmox_service.get_all_guests(
                hostname=node.hostname,
                port=node.ssh_port,
                username=node.ssh_user,
                key_path=node.ssh_key_path
            )
            
            for vm in vms:
                vm_info = {
                    "vmid": vm.get("vmid"),
                    "name": vm.get("name", f"VM-{vm.get('vmid')}"),
                    "type": vm.get("type", "qemu"),
                    "status": vm.get("status", "unknown"),
                    "node_id": node.id,
                    "node_name": node.name,
                    "hostname": node.hostname
                }
                all_vms.append(vm_info)
        except:
            continue
    
    return all_vms

