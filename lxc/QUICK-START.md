# ⚡ Quick Start - Deploy Automatico

Deploy completo in un solo comando!

## 🚀 Deploy Automatico (Consigliato)

### Sul nodo Proxmox, esegui:

```bash
# Download e esecuzione diretta
bash <(curl -s https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/auto-deploy.sh)
```

Oppure:

```bash
# 1. Scarica lo script
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/auto-deploy.sh

# 2. Esegui
chmod +x auto-deploy.sh
./auto-deploy.sh
```

## 📋 Con parametri personalizzati

```bash
./auto-deploy.sh <CTID> <NOME> <STORAGE> <ROOTFS> <MEMORY> <CORES> <BRIDGE> <IP>

# Esempio:
./auto-deploy.sh 100 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 dhcp

# Con IP statico:
./auto-deploy.sh 100 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 192.168.1.100/24
```

## 🎯 Cosa fa lo script

1. ✅ **Scarica** tutti i file da GitHub
2. ✅ **Verifica** prerequisiti (storage, bridge, template)
3. ✅ **Crea** il container LXC
4. ✅ **Installa** l'applicazione
5. ✅ **Configura** il servizio systemd
6. ✅ **Verifica** che tutto funzioni

## 📝 Esempio completo

```bash
# Sul nodo Proxmox
cd /root

# Download script
wget https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/auto-deploy.sh
chmod +x auto-deploy.sh

# Esegui deploy (con parametri di default)
./auto-deploy.sh

# Oppure con parametri personalizzati
./auto-deploy.sh 100 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 dhcp

# Attendi completamento (5-10 minuti)

# Accedi all'interfaccia web
# L'IP verrà mostrato alla fine dello script
```

## 🔧 Parametri disponibili

| Parametro | Default | Descrizione |
|-----------|---------|-------------|
| CTID | 100 | ID del container |
| NOME | dapx-backandrepl | Nome container |
| STORAGE | local-lvm | Storage Proxmox |
| ROOTFS | 8G | Dimensione disco |
| MEMORY | 1024 | Memoria in MB |
| CORES | 2 | CPU cores |
| BRIDGE | vmbr0 | Bridge di rete |
| IP | dhcp | IP o "dhcp" |

## ✅ Verifica dopo il deploy

```bash
# Stato container
pct status 100

# Log servizio
pct exec 100 -- journalctl -u dapx-backandrepl -n 50

# Test API
pct exec 100 -- curl http://localhost:8420/api/health
```

## 🐛 Problemi?

Se lo script fallisce:

1. **Verifica prerequisiti:**
   ```bash
   which pct
   pvesm status
   ip addr show | grep vmbr
   ```

2. **Verifica connessione internet:**
   ```bash
   ping -c 3 8.8.8.8
   ```

3. **Esegui manualmente:**
   ```bash
   # Vedi DEPLOY.md per istruzioni dettagliate
   ```

## 📚 Documentazione completa

- **DEPLOY.md** - Guida deploy dettagliata
- **README.md** - Documentazione completa LXC
- **MANUAL.md** - Manuale progetto completo

---

**© 2025 Domarc S.r.l. - Tutti i diritti riservati**

