# Implementazione Dashboard Panoramica Nodi Proxmox

## ✅ Completato

### Backend
1. **Servizio Host Info** (`backend/services/host_info_service.py`)
   - ✅ Raccolta dati host via pvesh e SSH
   - ✅ CPU info (modello, core, socket, load average)
   - ✅ Memory info (totale, usata, swap)
   - ✅ Storage details (via pvesm)
   - ✅ Network details (via pvesh)
   - ✅ Temperature readings (via sensors)
   - ✅ License info (via pvesubscription)

2. **Router API** (`backend/routers/host_info.py`)
   - ✅ Endpoint `/api/nodes/{node_id}/host-details`
   - ✅ Endpoint `/api/nodes/{node_id}/vms/{vmid}/full-details`
   - ✅ Endpoint `/api/dashboard/overview`
   - ✅ Endpoint `/api/dashboard/nodes`
   - ✅ Endpoint `/api/dashboard/vms`

3. **Integrazione** (`backend/main.py`)
   - ✅ Router host_info incluso nell'applicazione

## 🔨 Da Completare

### Backend

#### 1. Estendere `proxmox_service.py` con `get_vm_full_details`

Aggiungere metodo per raccogliere dettagli completi VM usando pvesh:

```python
async def get_vm_full_details(
    self,
    hostname: str,
    node_name: str,
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

**Esempio implementazione**:
```python
# Ottieni node name
cmd = f"hostname"
result = await ssh_service.execute(hostname, cmd, port, username, key_path)
node_name = result.stdout.strip() if result.success else hostname

# Config via pvesh
cmd = f"pvesh get /nodes/{node_name}/qemu/{vmid}/config --output-format json 2>/dev/null"
result = await ssh_service.execute(hostname, cmd, port, username, key_path)
config = json.loads(result.stdout) if result.success else {}

# Status via pvesh
cmd = f"pvesh get /nodes/{node_name}/qemu/{vmid}/status/current --output-format json 2>/dev/null"
result = await ssh_service.execute(hostname, cmd, port, username, key_path)
status = json.loads(result.stdout) if result.success else {}

# Agent network (se running)
if status.get("status") == "running":
    cmd = f"pvesh get /nodes/{node_name}/qemu/{vmid}/agent/network-get-interfaces --output-format json 2>/dev/null"
    result = await ssh_service.execute(hostname, cmd, port, username, key_path)
    agent_network = json.loads(result.stdout) if result.success else {}

# Snapshots
cmd = f"pvesh get /nodes/{node_name}/qemu/{vmid}/snapshot --output-format json 2>/dev/null"
result = await ssh_service.execute(hostname, cmd, port, username, key_path)
snapshots = json.loads(result.stdout) if result.success else {}
```

#### 2. Aggiornare `host_info.py` per usare `get_vm_full_details`

Nel metodo `get_vm_full_details` del router, sostituire il TODO con chiamata al servizio:

```python
vm_details = await proxmox_service.get_vm_full_details(
    hostname=node.hostname,
    node_name=node.name,  # o ottenere via hostname
    vmid=vmid,
    vm_type=vm_type,
    port=node.ssh_port,
    username=node.ssh_user,
    key_path=node.ssh_key_path
)
```

### Frontend

#### 1. Aggiungere pagina Dashboard

Nel file `frontend/dist/index.html`, aggiungere:

1. **Nuova sezione nel menu**:
```html
<button @click="currentPage = 'dashboard'" :class="{ active: currentPage === 'dashboard' }">
    📊 Dashboard
</button>
```

2. **Nuova sezione dashboard** (dopo la sezione recovery jobs):
```html
<!-- Dashboard -->
<div v-if="currentPage === 'dashboard'" class="page">
    <h1>📊 Dashboard Panoramica</h1>
    
    <!-- Overview Stats -->
    <div class="stats-grid" v-if="dashboardOverview">
        <div class="stat-card">
            <div class="stat-label">Nodi Totali</div>
            <div class="stat-value">{{ dashboardOverview.total_nodes }}</div>
            <div class="stat-detail">Online: {{ dashboardOverview.online_nodes }}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">VM Totali</div>
            <div class="stat-value">{{ dashboardOverview.total_vms }}</div>
            <div class="stat-detail">Running: {{ dashboardOverview.running_vms }}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">Storage Totale</div>
            <div class="stat-value">{{ formatSize(dashboardOverview.total_storage_gb * 1024 * 1024 * 1024) }}</div>
            <div class="stat-detail">Usato: {{ formatSize(dashboardOverview.used_storage_gb * 1024 * 1024 * 1024) }}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">RAM Totale</div>
            <div class="stat-value">{{ formatSize(dashboardOverview.total_memory_gb * 1024 * 1024 * 1024) }}</div>
            <div class="stat-detail">Usata: {{ formatSize(dashboardOverview.used_memory_gb * 1024 * 1024 * 1024) }}</div>
        </div>
        <div class="stat-card">
            <div class="stat-label">CPU Cores</div>
            <div class="stat-value">{{ dashboardOverview.total_cpu_cores }}</div>
        </div>
    </div>
    
    <!-- Tabella Nodi -->
    <h2>Nodi</h2>
    <table>
        <thead>
            <tr>
                <th>Nome</th>
                <th>Hostname</th>
                <th>Stato</th>
                <th>CPU</th>
                <th>RAM</th>
                <th>Storage</th>
                <th>VM</th>
                <th>Temperatura</th>
                <th>Versione</th>
                <th>Azioni</th>
            </tr>
        </thead>
        <tbody>
            <tr v-for="node in dashboardNodes" :key="node.id">
                <td>{{ node.name }}</td>
                <td>{{ node.hostname }}</td>
                <td>
                    <span :class="node.is_online ? 'status-online' : 'status-offline'">
                        {{ node.is_online ? '🟢 Online' : '🔴 Offline' }}
                    </span>
                </td>
                <td>{{ node.cpu?.cores || 'N/A' }} cores</td>
                <td>
                    <div>{{ formatSize((node.memory?.total_gb || 0) * 1024 * 1024 * 1024) }}</div>
                    <div style="font-size: 0.85em; color: var(--text-secondary);">
                        Usata: {{ formatSize((node.memory?.used_gb || 0) * 1024 * 1024 * 1024) }}
                    </div>
                </td>
                <td>
                    <div>{{ formatSize((node.storage_total_gb || 0) * 1024 * 1024 * 1024) }}</div>
                    <div style="font-size: 0.85em; color: var(--text-secondary);">
                        Usato: {{ formatSize((node.storage_used_gb || 0) * 1024 * 1024 * 1024) }}
                    </div>
                </td>
                <td>{{ node.vm_count || 0 }} ({{ node.running_vm_count || 0 }} running)</td>
                <td>
                    <span v-if="node.temperature_highest_c">
                        {{ node.temperature_highest_c }}°C
                    </span>
                    <span v-else>N/A</span>
                </td>
                <td>{{ node.proxmox_version || 'N/A' }}</td>
                <td>
                    <button @click="viewNodeDetails(node.id)" class="btn-small">Dettagli</button>
                </td>
            </tr>
        </tbody>
    </table>
    
    <!-- Tabella VM Aggregate -->
    <h2>VM Aggregate</h2>
    <table>
        <thead>
            <tr>
                <th>VMID</th>
                <th>Nome</th>
                <th>Nodo</th>
                <th>Tipo</th>
                <th>Stato</th>
                <th>Azioni</th>
            </tr>
        </thead>
        <tbody>
            <tr v-for="vm in dashboardVMs" :key="`${vm.node_id}-${vm.vmid}`">
                <td>{{ vm.vmid }}</td>
                <td>{{ vm.name }}</td>
                <td>{{ vm.node_name }}</td>
                <td>{{ vm.type }}</td>
                <td>
                    <span :class="vm.status === 'running' ? 'status-online' : 'status-offline'">
                        {{ vm.status }}
                    </span>
                </td>
                <td>
                    <button @click="viewVMDetails(vm.node_id, vm.vmid, vm.type)" class="btn-small">Dettagli</button>
                </td>
            </tr>
        </tbody>
    </table>
</div>
```

3. **Aggiungere dati e metodi in Vue**:
```javascript
data() {
    return {
        // ... existing data ...
        dashboardOverview: null,
        dashboardNodes: [],
        dashboardVMs: [],
    }
},
methods: {
    // ... existing methods ...
    
    async loadDashboard() {
        try {
            // Load overview
            const overviewRes = await fetch('/api/dashboard/overview', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            this.dashboardOverview = await overviewRes.json();
            
            // Load nodes
            const nodesRes = await fetch('/api/dashboard/nodes', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            this.dashboardNodes = await nodesRes.json();
            
            // Load VMs
            const vmsRes = await fetch('/api/dashboard/vms', {
                headers: { 'Authorization': `Bearer ${this.token}` }
            });
            this.dashboardVMs = await vmsRes.json();
        } catch (error) {
            console.error('Errore caricamento dashboard:', error);
            this.showError('Errore caricamento dashboard');
        }
    },
    
    viewNodeDetails(nodeId) {
        // Navigate to node details page
        this.currentPage = 'nodes';
        // Scroll to node or highlight
    },
    
    viewVMDetails(nodeId, vmid, vmType) {
        // Navigate to VM details
        this.currentPage = 'vms';
        // Scroll to VM or highlight
    }
},
mounted() {
    // ... existing mounted code ...
    
    // Load dashboard if on dashboard page
    if (this.currentPage === 'dashboard') {
        this.loadDashboard();
    }
},
watch: {
    currentPage(newPage) {
        if (newPage === 'dashboard') {
            this.loadDashboard();
        }
    }
}
```

4. **Aggiungere CSS per stats-grid**:
```css
.stats-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
    gap: 16px;
    margin-bottom: 32px;
}

.stat-card {
    background: var(--card-bg);
    border: 1px solid var(--border-color);
    border-radius: 8px;
    padding: 16px;
    text-align: center;
}

.stat-label {
    font-size: 0.9em;
    color: var(--text-secondary);
    margin-bottom: 8px;
}

.stat-value {
    font-size: 2em;
    font-weight: bold;
    color: var(--primary-color);
    margin-bottom: 4px;
}

.stat-detail {
    font-size: 0.85em;
    color: var(--text-secondary);
}
```

#### 2. Aggiungere pagina Dettaglio Nodo

Creare nuova sezione per dettaglio nodo con tab:

```html
<!-- Node Details -->
<div v-if="currentPage === 'node-details' && selectedNode" class="page">
    <h1>🔧 Dettagli Nodo: {{ selectedNode.name }}</h1>
    
    <div class="tabs">
        <button @click="nodeDetailsTab = 'hardware'" :class="{ active: nodeDetailsTab === 'hardware' }">
            Hardware
        </button>
        <button @click="nodeDetailsTab = 'storage'" :class="{ active: nodeDetailsTab === 'storage' }">
            Storage
        </button>
        <button @click="nodeDetailsTab = 'network'" :class="{ active: nodeDetailsTab === 'network' }">
            Network
        </button>
        <button @click="nodeDetailsTab = 'vms'" :class="{ active: nodeDetailsTab === 'vms' }">
            VM
        </button>
        <button @click="nodeDetailsTab = 'license'" :class="{ active: nodeDetailsTab === 'license' }">
            Licenza
        </button>
    </div>
    
    <!-- Tab content -->
    <div v-if="nodeDetailsTab === 'hardware'">
        <!-- CPU, RAM, Temperature -->
    </div>
    <div v-if="nodeDetailsTab === 'storage'">
        <!-- Storage list -->
    </div>
    <!-- ... altri tab ... -->
</div>
```

## 🧪 Testing

### Test Backend

1. **Test host_info_service**:
```bash
cd backend
python -c "
import asyncio
from services.host_info_service import host_info_service

async def test():
    details = await host_info_service.get_host_details(
        hostname='your-proxmox-host',
        port=22,
        username='root',
        key_path='/root/.ssh/id_rsa'
    )
    print(details)

asyncio.run(test())
"
```

2. **Test API endpoints**:
```bash
# Test host details
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8420/api/nodes/1/host-details

# Test dashboard overview
curl -H "Authorization: Bearer YOUR_TOKEN" \
  http://localhost:8420/api/dashboard/overview
```

### Test Frontend

1. Aprire browser su `http://localhost:8420`
2. Navigare a Dashboard
3. Verificare caricamento dati
4. Verificare tabella nodi
5. Verificare tabella VM
6. Testare dettaglio nodo

## 📝 Note

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

## 🚀 Prossimi Passi

1. ✅ Completare `get_vm_full_details` in `proxmox_service.py`
2. ✅ Aggiornare router `host_info.py` per usare nuovo metodo
3. ✅ Implementare frontend dashboard
4. ✅ Implementare pagina dettaglio nodo
5. ✅ Estendere pagina dettaglio VM
6. ⚠️ Aggiungere cache database per performance
7. ⚠️ Aggiungere background job per aggiornamento dati
8. ⚠️ Aggiungere grafici (Chart.js o simile) per visualizzazioni




