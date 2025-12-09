# Analisi e Proposta: Panoramica Nodi Proxmox

## 📋 Analisi Script Proxreporter

### Dati Raccolti da Proxreporter

Gli script Proxreporter raccolgono informazioni dettagliate su:

#### 1. **Host/Node Information**
- **Hardware**: CPU (modello, core, socket, thread), RAM totale/used, temperatura
- **Sistema**: Versione Proxmox, kernel, uptime, load average
- **Storage**: Lista storage con tipo, dimensione, utilizzo, contenuto
- **Network**: Interfacce di rete con IP, MAC, bridge, VLAN, bond
- **BIOS/Hardware**: Vendor, versione, serial number, board info
- **Licenza**: Status, livello, scadenza, socket

#### 2. **VM Information**
- **Configurazione**: CPU, RAM, dischi, network, BIOS, boot
- **Runtime**: Status, uptime, utilizzo CPU/RAM, I/O dischi/network
- **Storage**: Dettagli dischi con dataset ZFS, dimensioni
- **Network**: IP addresses (IPv4/IPv6), bridge, MAC
- **Snapshot**: Lista snapshot con data, dimensione
- **Agent**: Versione QEMU agent, opzioni

#### 3. **Cluster Information**
- Nodi del cluster, quorum, versione

### Metodi di Raccolta

Proxreporter usa principalmente:
- **pvesh**: Comando CLI Proxmox per API (JSON output)
- **Comandi SSH**: `qm list`, `pct list`, `pvesm status`, `sensors`, `lscpu`, `lshw`, etc.
- **File system**: `/etc/pve/`, `/sys/class/`, `/proc/`

## 🎯 Proposta Implementazione

### Fase 1: Servizio Raccolta Dati Host

Creare `backend/services/host_info_service.py` che raccoglie:

```python
class HostInfoService:
    async def get_host_details(node_id, include_hardware=True, include_storage=True, include_network=True)
    async def get_cluster_info(node_id)
    async def get_storage_details(node_id)
    async def get_network_details(node_id)
    async def get_temperature_readings(node_id)
    async def get_license_info(node_id)
```

**Dati da raccogliere** (ispirati a Proxreporter):
- CPU: modello, core, socket, thread, load average
- RAM: totale, usata, swap
- Storage: lista con tipo, dimensione, utilizzo
- Network: interfacce con IP, MAC, bridge
- Temperatura: letture sensori
- Licenza: status, livello, scadenza
- Versione Proxmox, kernel, uptime

### Fase 2: Estensione VM Details

Estendere `backend/services/proxmox_service.py` per raccogliere dettagli completi VM:

```python
async def get_vm_full_details(node_id, vmid, vm_type="qemu")
```

**Dati aggiuntivi da raccogliere**:
- Utilizzo CPU/RAM in tempo reale
- I/O dischi (read/write)
- I/O network (in/out)
- IP addresses (via QEMU agent se disponibile)
- Snapshot count e dettagli
- Configurazione completa (CPU, RAM, dischi, network)

### Fase 3: Nuovi Endpoint API

Creare `backend/routers/host_info.py`:

```python
@router.get("/nodes/{node_id}/host-details")
async def get_node_host_details(node_id, include_hardware, include_storage, include_network)

@router.get("/nodes/{node_id}/vms/{vmid}/full-details")
async def get_vm_full_details(node_id, vmid, vm_type)

@router.get("/dashboard/overview")
async def get_dashboard_overview()  # Statistiche aggregate

@router.get("/dashboard/nodes")
async def get_dashboard_nodes()  # Lista nodi con summary

@router.get("/dashboard/vms")
async def get_dashboard_vms()  # Lista VM aggregate
```

### Fase 4: Dashboard Frontend

Creare nuova pagina `dashboard` nel frontend con:

#### Sezione 1: Overview Generale
- **Statistiche Aggregate**:
  - Totale nodi (online/offline)
  - Totale VM (running/stopped)
  - Storage totale/used
  - CPU/RAM aggregate

#### Sezione 2: Nodi
- **Tabella Nodi** con:
  - Nome, hostname, stato
  - CPU (core/socket), RAM (totale/used)
  - Storage totale/used
  - Temperatura max
  - Versione Proxmox
  - Licenza status
  - Link a dettagli

#### Sezione 3: VM Aggregate
- **Tabella VM** con:
  - VMID, Nome, Nodo
  - Status, CPU%, RAM%
  - Storage used
  - Uptime
  - IP addresses
  - Link a dettagli

#### Sezione 4: Storage Overview
- **Tabella Storage** aggregata:
  - Nome, Nodo, Tipo
  - Dimensione totale/used
  - Percentuale utilizzo
  - Contenuto (images, rootdir, etc.)

#### Sezione 5: Network Overview
- **Interfacce di rete** aggregate:
  - Nodo, Interfaccia, Tipo
  - IP addresses
  - Bridge/VLAN
  - Stato

### Fase 5: Dettaglio Nodo

Pagina dettaglio nodo (`/nodes/{id}/details`) con:

- **Tab Hardware**:
  - CPU, RAM, Storage, Network
  - Temperatura, BIOS info
  - Hardware details (lshw summary)

- **Tab Storage**:
  - Lista storage con dettagli
  - Grafico utilizzo

- **Tab Network**:
  - Interfacce con dettagli
  - IP addresses

- **Tab VM**:
  - Lista VM sul nodo con dettagli
  - Statistiche aggregate

- **Tab Licenza**:
  - Status, livello, scadenza

### Fase 6: Dettaglio VM Esteso

Estendere pagina VM esistente con:

- **Tab Overview**:
  - Status, uptime, CPU%, RAM%
  - Storage used, I/O stats
  - Network I/O

- **Tab Configurazione**:
  - CPU, RAM, dischi, network
  - BIOS, boot, agent

- **Tab Storage**:
  - Lista dischi con dataset
  - Dimensioni, utilizzo

- **Tab Network**:
  - Interfacce con IP
  - Bridge, MAC

- **Tab Snapshot**:
  - Lista snapshot
  - Dettagli (già presente)

## 🔧 Implementazione Tecnica

### Backend: Host Info Service

```python
# backend/services/host_info_service.py

class HostInfoService:
    """Servizio per raccogliere informazioni dettagliate sugli host Proxmox"""
    
    async def get_host_details(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa",
        include_hardware: bool = True,
        include_storage: bool = True,
        include_network: bool = True
    ) -> Dict[str, Any]:
        """
        Raccolta informazioni host usando pvesh e comandi SSH.
        Ispirato a Proxreporter.
        """
        # Usa pvesh per info base
        # Comandi SSH per hardware details
        # Combina i risultati
```

### Backend: Estensione Proxmox Service

```python
# Estendere proxmox_service.py

async def get_vm_full_details(
    self,
    hostname: str,
    vmid: int,
    vm_type: str = "qemu",
    port: int = 22,
    username: str = "root",
    key_path: str = "/root/.ssh/id_rsa"
) -> Dict[str, Any]:
    """
    Raccolta dettagli completi VM usando pvesh.
    Include: config, status, agent data, snapshots.
    """
    # Usa pvesh per:
    # - /nodes/{node}/qemu/{vmid}/config
    # - /nodes/{node}/qemu/{vmid}/status/current
    # - /nodes/{node}/qemu/{vmid}/agent/network-get-interfaces (se running)
    # - /nodes/{node}/qemu/{vmid}/snapshot
```

### Frontend: Nuova Pagina Dashboard

```vue
<!-- Pagina Dashboard -->
<div v-if="currentPage === 'dashboard'">
  <!-- Overview Stats -->
  <!-- Tabella Nodi -->
  <!-- Tabella VM -->
  <!-- Storage Overview -->
  <!-- Network Overview -->
</div>
```

## 📊 Struttura Dati

### Host Details Response

```json
{
  "node_id": 1,
  "hostname": "pve-node-01",
  "proxmox_version": "8.1.4",
  "kernel_version": "6.5.11",
  "uptime_seconds": 1234567,
  "cpu": {
    "model": "Intel Xeon E5-2650",
    "cores": 8,
    "sockets": 2,
    "threads": 16,
    "load_1m": 0.5,
    "load_5m": 0.6,
    "load_15m": 0.7
  },
  "memory": {
    "total_gb": 128,
    "used_gb": 64,
    "available_gb": 64,
    "swap_total_gb": 8,
    "swap_used_gb": 0
  },
  "storage": [
    {
      "name": "local-zfs",
      "type": "zfspool",
      "total_gb": 2000,
      "used_gb": 1000,
      "available_gb": 1000,
      "used_percent": 50,
      "content": "images,rootdir"
    }
  ],
  "network": [
    {
      "name": "eth0",
      "type": "physical",
      "state": "up",
      "mac": "aa:bb:cc:dd:ee:ff",
      "ipv4": ["192.168.1.10"],
      "speed_mbps": 1000
    }
  ],
  "temperature": {
    "highest_c": 45.5,
    "readings": [
      {"chip": "coretemp", "sensor": "Package id 0", "temp_c": 45.5}
    ]
  },
  "license": {
    "status": "active",
    "level": "community",
    "expires": null
  }
}
```

### VM Full Details Response

```json
{
  "vmid": 100,
  "name": "VM-Production",
  "node": "pve-node-01",
  "status": "running",
  "config": {
    "cores": 4,
    "sockets": 1,
    "memory": 8192,
    "ostype": "l26",
    "bios": "seabios"
  },
  "runtime": {
    "cpu_percent": 25.5,
    "mem_used_mb": 4096,
    "mem_total_mb": 8192,
    "uptime_seconds": 86400,
    "diskread_bytes": 1000000000,
    "diskwrite_bytes": 500000000,
    "netin_bytes": 2000000000,
    "netout_bytes": 1000000000
  },
  "disks": [
    {
      "disk_name": "scsi0",
      "storage": "local-zfs",
      "volume": "vm-100-disk-0",
      "dataset": "rpool/data/vm-100-disk-0",
      "size_gb": 100,
      "used_gb": 50
    }
  ],
  "networks": [
    {
      "id": "net0",
      "bridge": "vmbr0",
      "model": "virtio",
      "mac": "aa:bb:cc:dd:ee:ff"
    }
  ],
  "ip_addresses": {
    "ipv4": ["192.168.1.100"],
    "ipv6": [],
    "all": ["192.168.1.100"]
  },
  "snapshots": {
    "count": 5,
    "list": [...]
  },
  "agent": {
    "enabled": true,
    "version": "7.2.0"
  }
}
```

## 🚀 Piano di Implementazione

### Step 1: Servizio Host Info (Backend)
- [ ] Creare `host_info_service.py`
- [ ] Implementare raccolta dati via pvesh
- [ ] Implementare raccolta dati hardware via SSH
- [ ] Test su nodo reale

### Step 2: Estensione VM Details (Backend)
- [ ] Estendere `proxmox_service.py` con `get_vm_full_details`
- [ ] Usare pvesh per dati completi
- [ ] Integrare QEMU agent per IP addresses
- [ ] Test su VM reali

### Step 3: Endpoint API (Backend)
- [ ] Creare `routers/host_info.py`
- [ ] Endpoint `/api/nodes/{id}/host-details`
- [ ] Endpoint `/api/nodes/{id}/vms/{vmid}/full-details`
- [ ] Endpoint `/api/dashboard/overview`
- [ ] Endpoint `/api/dashboard/nodes`
- [ ] Endpoint `/api/dashboard/vms`

### Step 4: Dashboard Frontend
- [ ] Aggiungere pagina `dashboard` al router
- [ ] Sezione Overview con statistiche
- [ ] Tabella nodi con dettagli
- [ ] Tabella VM aggregate
- [ ] Sezione Storage overview
- [ ] Sezione Network overview

### Step 5: Dettaglio Nodo (Frontend)
- [ ] Pagina dettaglio nodo
- [ ] Tab Hardware
- [ ] Tab Storage
- [ ] Tab Network
- [ ] Tab VM
- [ ] Tab Licenza

### Step 6: Dettaglio VM Esteso (Frontend)
- [ ] Estendere pagina VM esistente
- [ ] Tab Overview con runtime stats
- [ ] Tab Configurazione completa
- [ ] Tab Storage dettagliato
- [ ] Tab Network dettagliato

## ⚠️ Considerazioni

### Performance
- Raccolta dati può essere lenta (SSH + pvesh)
- Considerare cache in database per dati host
- Aggiornamento asincrono in background
- Rate limiting per evitare sovraccarico nodi

### Permessi
- Richiede accesso SSH root
- Richiede pvesh disponibile
- QEMU agent richiede VM running e agent abilitato

### Compatibilità
- Funziona solo con nodi PVE (non PBS)
- Alcuni comandi richiedono pacchetti specifici (sensors, lshw)
- QEMU agent opzionale per IP addresses

### Fallback
- Se pvesh non disponibile, usare comandi SSH base
- Se agent non disponibile, IP addresses non disponibili
- Se sensors non disponibile, temperatura non disponibile

## 📝 Note Implementative

1. **pvesh vs SSH**: Preferire pvesh quando disponibile (JSON output, più affidabile)
2. **Caching**: Considerare cache dati host in database (tabella `host_info_cache`)
3. **Background Jobs**: Aggiornare dati host periodicamente (ogni 5-15 minuti)
4. **Error Handling**: Gestire gracefully errori SSH/pvesh
5. **Timeout**: Impostare timeout appropriati per comandi SSH




