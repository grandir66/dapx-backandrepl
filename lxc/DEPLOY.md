# 🚀 Guida Deploy - Container LXC per Proxmox

Guida passo-passo per il deploy di DAPX-backandrepl come container LXC su Proxmox.

## 📍 Dove trovare i file

I file sono nel repository GitHub:
- **Repository**: `https://github.com/grandir66/dapx-backandrepl`
- **Directory**: `lxc/`
- **File principali**:
  - `create-lxc-container.sh` - Crea il container
  - `install-in-lxc.sh` - Installa l'applicazione
  - `manage-lxc.sh` - Gestisce il container
  - `export-lxc-template.sh` - Esporta template

## 🔽 Opzione 1: Download diretto (Consigliata)

### Sul nodo Proxmox:

```bash
# 1. Crea directory per i file
mkdir -p /root/dapx-lxc
cd /root/dapx-lxc

# 2. Scarica i file direttamente da GitHub
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/create-lxc-container.sh
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/install-in-lxc.sh
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/manage-lxc.sh
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/export-lxc-template.sh

# 3. Rendi eseguibili
chmod +x *.sh

# 4. Verifica che i file siano presenti
ls -lh
```

## 🔽 Opzione 2: Clone repository completo

### Sul nodo Proxmox:

```bash
# 1. Installa git se non presente
apt-get update && apt-get install -y git

# 2. Clona repository
cd /root
git clone https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl/lxc

# 3. Rendi eseguibili
chmod +x *.sh
```

## 🔽 Opzione 3: Trasferimento da macchina locale

### Dalla tua macchina locale:

```bash
# 1. Assicurati di essere nella directory del progetto
cd /Users/riccardo/Progetti/sanoid-manager

# 2. Trasferisci la directory lxc sul server Proxmox
scp -r lxc/ root@<IP-PROXMOX>:/root/dapx-lxc/

# Esempio:
# scp -r lxc/ root@192.168.40.3:/root/dapx-lxc/
```

### Sul nodo Proxmox:

```bash
cd /root/dapx-lxc
chmod +x *.sh
ls -lh
```

## 🚀 Deploy - Passo dopo passo

### Step 1: Verifica prerequisiti

```bash
# Verifica che sei su un nodo Proxmox
which pct
which vzdump

# Verifica storage disponibile
pvesm status

# Verifica bridge di rete
ip addr show | grep vmbr
```

### Step 2: Crea il container

```bash
cd /root/dapx-lxc

# Crea container con parametri di default
./create-lxc-container.sh

# Oppure con parametri personalizzati:
# ./create-lxc-container.sh <CTID> <NOME> <STORAGE> <ROOTFS_SIZE> <MEMORY> <CORES> <BRIDGE> <IP> <GATEWAY> <DNS> <PASSWORD> <SSH_KEY>
./create-lxc-container.sh 100 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 dhcp "" "" ""
```

**Parametri spiegati:**
- `100` - ID container (scegli un ID libero)
- `dapx-backandrepl` - Nome container
- `local-lvm` - Storage (usa quello disponibile sul tuo Proxmox)
- `8G` - Dimensione disco rootfs
- `1024` - Memoria in MB
- `2` - CPU cores
- `vmbr0` - Bridge di rete (verifica con `ip addr`)
- `dhcp` - IP automatico (oppure `192.168.1.100/24` per IP statico)
- `""` - Gateway (auto se DHCP)
- `""` - DNS (default: 8.8.8.8 8.8.4.4)
- `""` - Password root (opzionale)
- `""` - Chiave SSH pubblica (opzionale)

### Step 3: Installa l'applicazione

```bash
# Entra nel container e installa
pct exec 100 -- /tmp/dapx-install/install.sh

# Oppure entra manualmente:
pct enter 100
cd /tmp/dapx-install
./install.sh
exit
```

### Step 4: Verifica installazione

```bash
# Verifica stato container
./manage-lxc.sh 100 status

# Verifica servizio
./manage-lxc.sh 100 service-status

# Verifica log
./manage-lxc.sh 100 logs

# Ottieni IP del container
pct exec 100 -- hostname -I
```

### Step 5: Accedi all'interfaccia web

```bash
# Ottieni IP del container
IP=$(pct exec 100 -- hostname -I | awk '{print $1}')

echo "Accesso Web UI: http://${IP}:8420"
```

Apri il browser su: `http://<IP-CONTAINER>:8420`

## 📋 Esempio completo

```bash
# ===== SUL NODO PROXMOX =====

# 1. Download file
mkdir -p /root/dapx-lxc && cd /root/dapx-lxc
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/create-lxc-container.sh
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/install-in-lxc.sh
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/manage-lxc.sh
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/export-lxc-template.sh
chmod +x *.sh

# 2. Verifica storage e bridge
pvesm status
ip addr show | grep vmbr

# 3. Crea container (adatta i parametri al tuo ambiente)
./create-lxc-container.sh 100 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 dhcp

# 4. Installa applicazione
pct exec 100 -- /tmp/dapx-install/install.sh

# 5. Verifica
./manage-lxc.sh 100 status
IP=$(pct exec 100 -- hostname -I | awk '{print $1}')
echo "Accesso: http://${IP}:8420"
```

## 🔧 Configurazione personalizzata

### IP statico

```bash
# Crea container con IP statico
./create-lxc-container.sh 100 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 192.168.1.100/24 192.168.1.1
```

### Storage personalizzato

```bash
# Verifica storage disponibili
pvesm status

# Usa storage diverso (es: local, nfs, ceph)
./create-lxc-container.sh 100 dapx-backandrepl local 8G 1024 2 vmbr0 dhcp
```

### Più risorse

```bash
# Container con più memoria e CPU
./create-lxc-container.sh 100 dapx-backandrepl local-lvm 16G 2048 4 vmbr0 dhcp
```

## 🛠️ Gestione dopo il deploy

```bash
cd /root/dapx-lxc

# Stato
./manage-lxc.sh 100 status

# Log
./manage-lxc.sh 100 logs

# Riavvia
./manage-lxc.sh 100 restart

# Aggiorna applicazione
./manage-lxc.sh 100 update

# Backup
./manage-lxc.sh 100 backup
```

## 🐛 Troubleshooting

### Container non si crea

```bash
# Verifica che l'ID non esista già
pct list

# Verifica template disponibile
ls -lh /var/lib/vz/template/cache/

# Scarica template se mancante
pveam download local debian-12-standard
```

### Installazione fallisce

```bash
# Entra nel container
pct enter 100

# Verifica connessione internet
ping -c 3 8.8.8.8

# Verifica Python
python3 --version

# Esegui installazione manuale
cd /tmp/dapx-install
bash -x install.sh
```

### Servizio non parte

```bash
# Verifica log
./manage-lxc.sh 100 logs

# Entra nel container
pct enter 100

# Verifica servizio
systemctl status dapx-backandrepl
journalctl -u dapx-backandrepl -n 50
```

### Non riesco ad accedere via web

```bash
# Verifica che il servizio sia attivo
./manage-lxc.sh 100 service-status

# Verifica IP
pct exec 100 -- hostname -I

# Verifica porta
pct exec 100 -- netstat -tlnp | grep 8420

# Test da container
pct exec 100 -- curl http://localhost:8420/api/health
```

## 📦 Esporta come template

Dopo aver configurato il container, puoi esportarlo come template:

```bash
cd /root/dapx-lxc

# Esporta
./export-lxc-template.sh 100

# Copia come template
cp /var/lib/vz/dump/vzdump-lxc-100-*.tar.zst \
   /var/lib/vz/template/cache/dapx-backandrepl-template.tar.zst

# Ora puoi creare nuovi container dal template
pct create 101 /var/lib/vz/template/cache/dapx-backandrepl-template.tar.zst \
    --storage local-lvm --rootfs local-lvm:8G --hostname dapx-2 \
    --memory 1024 --cores 2 --net0 name=eth0,bridge=vmbr0,ip=dhcp
```

## 🔗 Link utili

- **Repository GitHub**: https://github.com/grandir66/dapx-backandrepl
- **Documentazione LXC**: `lxc/README.md`
- **Documentazione Docker**: `DOCKER.md`
- **Manuale completo**: `MANUAL.md`

---

**© 2025 Domarc S.r.l. - Tutti i diritti riservati**

