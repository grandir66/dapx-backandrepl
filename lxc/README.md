# 🐳 Container LXC per Proxmox - DAPX-backandrepl

Guida completa per creare, gestire ed esportare un container LXC per Proxmox con DAPX-backandrepl preinstallato.

## 📋 Requisiti

- **Proxmox VE** 7.0+ installato
- **Accesso root** al nodo Proxmox
- **Storage** configurato (local, local-lvm, etc.)
- **Rete** configurata (vmbr0 o altro bridge)

## 🚀 Installazione Rapida

### 1. Copia file sul nodo Proxmox

```bash
# Dalla macchina locale
scp -r lxc/ root@<IP-PROXMOX>:/root/dapx-lxc/
```

### 2. Crea il container

```bash
# Sul nodo Proxmox
cd /root/dapx-lxc
chmod +x *.sh

# Crea container con parametri di default
./create-lxc-container.sh

# Oppure con parametri personalizzati
./create-lxc-container.sh 100 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 dhcp "" "" ""
```

**Parametri:**
- `CTID`: ID del container (default: 100)
- `CT_NAME`: Nome container (default: dapx-backandrepl)
- `STORAGE`: Storage per rootfs (default: local-lvm)
- `ROOTFS_SIZE`: Dimensione rootfs (default: 8G)
- `MEMORY`: Memoria in MB (default: 1024)
- `CORES`: CPU cores (default: 2)
- `NETWORK_BRIDGE`: Bridge di rete (default: vmbr0)
- `IP_ADDRESS`: IP o "dhcp" (default: dhcp)
- `GATEWAY`: Gateway (default: auto)
- `DNS_SERVERS`: DNS servers (default: 8.8.8.8 8.8.4.4)
- `PASSWORD`: Password root (default: nessuna)
- `SSH_PUBLIC_KEY`: Chiave SSH pubblica (default: nessuna)

### 3. Completa l'installazione

```bash
# Entra nel container e installa l'applicazione
pct exec 100 -- /tmp/dapx-install/install.sh
```

Oppure esegui manualmente:

```bash
pct enter 100
# Poi dentro il container:
cd /tmp/dapx-install
./install.sh
```

## 🛠️ Gestione Container

Usa lo script `manage-lxc.sh` per gestire facilmente il container:

```bash
# Stato container e servizio
./manage-lxc.sh 100 status

# Avvia/ferma/riavvia container
./manage-lxc.sh 100 start
./manage-lxc.sh 100 stop
./manage-lxc.sh 100 restart

# Entra nel container
./manage-lxc.sh 100 enter

# Log del servizio
./manage-lxc.sh 100 logs

# Gestione servizio
./manage-lxc.sh 100 service-start
./manage-lxc.sh 100 service-stop
./manage-lxc.sh 100 service-restart
./manage-lxc.sh 100 service-status

# Aggiorna applicazione
./manage-lxc.sh 100 update

# Crea backup
./manage-lxc.sh 100 backup
```

## 📦 Esportazione Template

### Esporta come backup

```bash
# Crea backup del container
./export-lxc-template.sh 100 local /var/lib/vz/dump zstd
```

### Crea template riutilizzabile

```bash
# 1. Crea backup
./export-lxc-template.sh 100

# 2. Trova il file backup
ls -lh /var/lib/vz/dump/vzdump-lxc-100-*.tar.zst

# 3. Copia come template
cp /var/lib/vz/dump/vzdump-lxc-100-*.tar.zst \
   /var/lib/vz/template/cache/dapx-backandrepl-template.tar.zst

# 4. Ora puoi creare nuovi container dal template
pct create 101 /var/lib/vz/template/cache/dapx-backandrepl-template.tar.zst \
    --storage local-lvm \
    --rootfs local-lvm:8G \
    --hostname dapx-backandrepl-2 \
    --memory 1024 \
    --cores 2 \
    --net0 name=eth0,bridge=vmbr0,ip=dhcp \
    --unprivileged 0 \
    --features nesting=1,keyctl=1
```

## 🔧 Configurazione Avanzata

### Configurazione IP statico

```bash
# Modifica configurazione container
pct set 100 --net0 name=eth0,bridge=vmbr0,ip=192.168.1.100/24,gw=192.168.1.1

# Riavvia container
pct restart 100
```

### Aggiungi risorse

```bash
# Aumenta memoria
pct set 100 --memory 2048

# Aumenta CPU
pct set 100 --cores 4

# Aumenta spazio disco
pct resize 100 rootfs +8G
```

### Mount directory host

```bash
# Monta directory host nel container
pct set 100 --mp0 /mnt/backup,mp=/backup

# Monta storage Proxmox
pct set 100 --mp0 local:8,mp=/var/lib/dapx-backandrepl
```

## 📁 Struttura Directory

Nel container:

```
/opt/dapx-backandrepl/     # Applicazione
/var/lib/dapx-backandrepl/  # Database e dati
/var/log/dapx-backandrepl/  # Log
/etc/dapx-backandrepl/      # Configurazione
```

## 🔐 Sicurezza

### Configurazione firewall

```bash
# Nel container
apt-get install -y ufw
ufw allow 8420/tcp
ufw enable
```

### Chiavi SSH

```bash
# Aggiungi chiave SSH durante creazione
./create-lxc-container.sh 100 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 dhcp "" "" "$(cat ~/.ssh/id_rsa.pub)"
```

## 🔄 Backup e Ripristino

### Backup automatico

Configura backup automatico in Proxmox:

1. Vai su **Datacenter** → **Backup**
2. Crea nuovo job backup
3. Seleziona container `100`
4. Configura schedule (giornaliero, settimanale, etc.)

### Backup manuale

```bash
# Backup completo
vzdump 100 --storage local --compress zstd

# Backup senza fermare container
vzdump 100 --storage local --compress zstd --mode snapshot
```

### Ripristino

```bash
# Ripristina da backup
pct restore 102 /var/lib/vz/dump/vzdump-lxc-100-*.tar.zst --storage local-lvm
```

## 🐛 Troubleshooting

### Container non parte

```bash
# Verifica log
pct status 100
journalctl -b | grep lxc

# Verifica configurazione
pct config 100
```

### Servizio non parte

```bash
# Entra nel container
pct enter 100

# Verifica log servizio
journalctl -u dapx-backandrepl -n 50

# Verifica configurazione
systemctl status dapx-backandrepl
cat /etc/dapx-backandrepl/.env
```

### Problemi di rete

```bash
# Verifica configurazione rete
pct config 100 | grep net

# Test connessione
pct exec 100 -- ping -c 3 8.8.8.8
```

### Aggiornamento applicazione

```bash
# Aggiorna codice
./manage-lxc.sh 100 update

# Oppure manualmente
pct exec 100 -- bash -c "
    cd /opt/dapx-backandrepl
    git pull
    cd backend
    pip3 install --no-cache-dir -r requirements.txt
    systemctl restart dapx-backandrepl
"
```

## 📊 Monitoraggio

### Risorse container

```bash
# Utilizzo risorse
pct exec 100 -- top

# Spazio disco
pct exec 100 -- df -h

# Memoria
pct exec 100 -- free -h
```

### Log applicazione

```bash
# Log in tempo reale
pct exec 100 -- journalctl -u dapx-backandrepl -f

# Ultimi 100 log
pct exec 100 -- journalctl -u dapx-backandrepl -n 100
```

## 🔄 Migrazione Container

### Esporta e importa su altro nodo

```bash
# 1. Esporta su nodo sorgente
vzdump 100 --storage local --compress zstd

# 2. Trasferisci file
scp /var/lib/vz/dump/vzdump-lxc-100-*.tar.zst root@<NUOVO-NODO>:/var/lib/vz/dump/

# 3. Ripristina su nuovo nodo
pct restore 100 /var/lib/vz/dump/vzdump-lxc-100-*.tar.zst --storage local-lvm
```

## 📝 Note

- Il container è configurato come **privileged** per supportare SSH e altre funzionalità
- **Nesting** è abilitato per supportare Docker dentro il container (se necessario)
- Il database è salvato in `/var/lib/dapx-backandrepl/` (montato come volume)
- I log sono in `/var/log/dapx-backandrepl/` e anche in `journalctl`

## 🆚 Confronto: LXC vs Docker

| Aspetto | LXC | Docker |
|---------|-----|--------|
| **Integrazione Proxmox** | ✅ Nativa | ⚠️ Richiede VM |
| **Performance** | ✅ Diretta | ⚠️ Overhead |
| **Gestione** | ✅ Proxmox UI | ⚠️ CLI/Compose |
| **Backup** | ✅ Integrato | ⚠️ Manuale |
| **Risorse** | ✅ Condivise | ⚠️ Isolate |
| **Portabilità** | ⚠️ Proxmox only | ✅ Universale |

**Raccomandazione**: Usa LXC se hai Proxmox, Docker per altri ambienti.

---

**© 2025 Domarc S.r.l. - Tutti i diritti riservati**

