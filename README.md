# 🗃️ DAPX-backandrepl

**Sistema centralizzato di backup e replica per infrastrutture Proxmox VE**

![Version](https://img.shields.io/badge/version-3.5.0-blue)
![Python](https://img.shields.io/badge/python-3.9+-green)
![License](https://img.shields.io/badge/license-Proprietary-red)

> **© 2025 Domarc S.r.l.** - Tutti i diritti riservati  
> [www.domarc.it](https://www.domarc.it)

---

## 📑 Indice

- [Caratteristiche](#-caratteristiche)
- [Requisiti](#-requisiti)
- [Installazione](#-installazione)
  - [Opzione 1: Container LXC Proxmox (Consigliata)](#opzione-1-container-lxc-proxmox-consigliata)
  - [Opzione 2: Docker Container](#opzione-2-docker-container)
  - [Opzione 3: Installazione Standard](#opzione-3-installazione-standard)
- [Setup Iniziale](#-setup-iniziale)
- [Funzionalità Principali](#-funzionalità-principali)
- [Guida all'Uso](#-guida-alluso)
- [Configurazione](#️-configurazione)
- [Amministrazione](#-amministrazione)
- [Sicurezza](#-sicurezza)
- [Troubleshooting](#-troubleshooting)
- [API Reference](#-api-reference)

---

## ✨ Caratteristiche

### 🔐 Autenticazione e Sicurezza
- **Autenticazione Integrata** - Login con credenziali Proxmox VE (PAM, PVE, LDAP, AD)
- **Gestione Utenti** - Ruoli (Admin, Operator, Viewer) con permessi granulari
- **Restrizione Nodi** - Limita gli utenti a specifici nodi
- **HTTPS/SSL** - Configurazione certificati SSL con generazione auto-firmata o upload personalizzato
- **Configurazione Porta** - Personalizza la porta del web server (default: 8420)
- **Audit Log** - Tracciamento completo di tutte le operazioni

### 🖥️ Dashboard e Monitoraggio
- **Dashboard Centralizzata** - Monitora tutti i tuoi nodi Proxmox da un'unica interfaccia
- **Vista Dettagliata Nodi** - Informazioni complete su risorse, storage, network
- **Vista Dettagliata VM** - Stato, configurazione, snapshot, backup
- **Log Centralizzati** - Visualizzazione e ricerca log di tutti i job
- **Statistiche in Tempo Reale** - Overview di job, nodi, VM

### 📸 Gestione Snapshot
- **Snapshot Sanoid** - Configura Sanoid per snapshot automatici con policy personalizzabili
- **Snapshot per VM** - Gestione snapshot individuale per ogni VM (non solo per disco)
- **Template Retention** - Policy predefinite (production, default, minimal, backup, vm)
- **Snapshot Proxmox** - Visualizzazione snapshot nativi Proxmox
- **Snapshot Syncoid** - Visualizzazione snapshot creati durante la replica
- **Rollback Snapshot** - Ripristino rapido da snapshot
- **Clone Snapshot** - Creazione dataset da snapshot

### 🔄 Replica e Backup
- **Replica ZFS (Syncoid)** - Replica incrementale tra nodi ZFS
- **Replica BTRFS** - Supporto btrfs send/receive
- **Replica Jobs (PBS)** - Backup e restore automatici tramite Proxmox Backup Server
- **Backup Jobs (PBS)** - Backup incrementali verso Proxmox Backup Server
- **Registrazione VM** - Registra automaticamente le VM replicate sul nodo di destinazione
- **Compatibilità Hardware** - Verifica automatica CPU, network bridges, storage
- **Scheduling Flessibile** - Cron jobs personalizzabili o preset comuni

### 🚀 Migrazione VM
- **Migrazione/Copia VM** - Trasferimento VM tra nodi usando strumenti nativi Proxmox
- **Supporto Multi-Disco** - Gestione VM con più dischi
- **Supporto Multi-Network** - Configurazione di più interfacce di rete
- **Riconfigurazione Hardware** - Modifica CPU, RAM, storage, network durante migrazione
- **Snapshot Mirati** - Mantenimento snapshot selettivi durante migrazione
- **Conferma Sovrascrittura** - Protezione contro sovrascritture accidentali

### 🔑 Gestione SSH
- **Generazione Chiavi SSH** - Creazione automatica chiavi RSA/Ed25519
- **Distribuzione Chiavi** - Copia automatica su tutti i nodi
- **Test Connessioni** - Verifica connettività SSH
- **Mesh SSH** - Configurazione mesh per replica diretta tra nodi

### 💾 Backup Configurazione Host
- **Backup Config Proxmox** - Backup automatico configurazione nodi Proxmox
- **Retention Policy** - Gestione retention per backup configurazione
- **Restore Config** - Ripristino configurazione da backup

### 🔔 Notifiche
- **Email (SMTP)** - Notifiche via email con supporto TLS
- **Webhook** - Integrazione con servizi esterni (Slack, Discord, etc.)
- **Telegram** - Notifiche tramite bot Telegram
- **Riepilogo Giornaliero** - Report automatici delle attività
- **Trigger Personalizzabili** - Notifica su successo, errore, warning

### 🔄 Aggiornamenti
- **Sistema di Aggiornamento Web** - Aggiornamento diretto dall'interfaccia web
- **Controllo Versioni** - Verifica automatica nuove versioni da GitHub
- **Changelog Integrato** - Visualizzazione note di rilascio
- **Backup Automatico** - Backup database prima di ogni aggiornamento
- **Versioning Centralizzato** - Sistema di versioning con file VERSION

### 🎨 Interfaccia
- **Web UI Responsive** - Interfaccia moderna e intuitiva
- **Tema Chiaro/Scuro** - Personalizzazione tema
- **Multi-Lingua** - Supporto italiano/inglese
- **Real-time Updates** - Aggiornamenti in tempo reale senza refresh

---

## 📋 Requisiti

### Nodo Manager (dove installi DAPX-backandrepl)
- **Proxmox VE 7.x / 8.x** (o Debian 11/12, Ubuntu 20.04+)
- **Python 3.9+** (testato fino a Python 3.13)
- **ZFS o BTRFS** installato e configurato (per funzionalità snapshot/replica)
- **Accesso root o sudo**
- **Git** (per aggiornamenti)

### Nodi Gestiti
- **Proxmox VE**: Con ZFS o BTRFS per replica diretta
- **Proxmox Backup Server**: Per recovery/backup jobs
- **SSH accessibile** (porta 22 di default)
- **Chiave SSH del nodo manager autorizzata**

---

## 🚀 Installazione

### Opzione 1: Container LXC Proxmox (Consigliata per produzione)

**Installazione automatica con un singolo comando:**

```bash
# Esegui sul nodo Proxmox (non nel container)
bash <(curl -s https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/auto-deploy.sh)
```

Lo script interattivo ti guiderà nella:
- ✅ Selezione dell'ID container (con suggerimento automatico)
- ✅ Scelta dello storage disponibile
- ✅ Selezione del bridge di rete
- ✅ Scelta del template Debian/Ubuntu (con download automatico se necessario)
- ✅ Installazione automatica dell'applicazione
- ✅ Configurazione del servizio systemd

**Al termine, accedi a:** `http://IP-CONTAINER:8420`

> 📘 **Vedi [lxc/README.md](lxc/README.md) per documentazione completa**

#### Installazione Manuale LXC

Se preferisci un controllo più granulare:

```bash
# 1. Scarica gli script
cd /root
git clone https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl/lxc

# 2. Crea il container (personalizza i parametri)
# Sintassi: create-lxc-container.sh <ID> <nome> <storage> <rootfs> <memoria> <cpu> <bridge> <ip>
./create-lxc-container.sh 200 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 dhcp

# 3. Installa l'applicazione nel container
pct exec 200 -- bash < install-in-lxc.sh

# 4. Gestisci il container
./manage-lxc.sh 200 status    # Stato container
./manage-lxc.sh 200 logs      # Log applicazione
./manage-lxc.sh 200 update    # Aggiorna applicazione
./manage-lxc.sh 200 backup    # Crea backup container
```

#### Gestione Container LXC

```bash
# Entra nel container
pct enter <ID>

# Stato servizio
pct exec <ID> -- systemctl status dapx-backandrepl

# Log in tempo reale
pct exec <ID> -- journalctl -u dapx-backandrepl -f

# Aggiorna applicazione
pct exec <ID> -- bash -c "cd /opt/dapx-backandrepl && git pull && systemctl restart dapx-backandrepl"
```

---

### Opzione 2: Docker Container

**Installazione rapida con Docker:**

```bash
# Clona il repository
git clone https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl

# Esegui installazione Docker
chmod +x docker-install.sh
./docker-install.sh
```

Il container sarà disponibile su `http://localhost:8421` (porta mappata 8421→8420)

**Oppure con Docker Compose:**

```bash
# Avvia con docker-compose
docker-compose up -d

# Verifica stato
docker-compose ps

# Log
docker-compose logs -f dapx-backandrepl
```

> 📘 **Vedi [DOCKER.md](DOCKER.md) per documentazione completa**

---

### Opzione 3: Installazione Standard

**Installazione diretta sul sistema:**

```bash
# Clona il repository
cd /opt
git clone https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl

# Rendi eseguibile e avvia l'installer
chmod +x install.sh
./install.sh
```

L'installer:
- ✅ Crea virtual environment Python
- ✅ Installa dipendenze
- ✅ Crea servizio systemd
- ✅ Configura database
- ✅ Genera chiavi SSH

**Oppure scarica l'ultima release:**

```bash
cd /tmp
wget https://github.com/grandir66/dapx-backandrepl/archive/refs/tags/v3.5.0.tar.gz
tar xzf v3.5.0.tar.gz
cd dapx-backandrepl-3.5.0
chmod +x install.sh
./install.sh
```

---

## 🎯 Setup Iniziale

### 1. Primo Accesso

1. Apri il browser su: `http://<IP-NODO-MANAGER>:8420`
2. Completa il wizard di setup:
   - **Crea l'account amministratore** (username, password, nome completo)
   - **Configura il metodo di autenticazione** (Proxmox o locale)
   - **Imposta le preferenze di base**

### 2. Configura Accesso SSH ai Nodi

L'installer mostra la chiave pubblica SSH. Copiala su ogni nodo:

```bash
# Per ogni nodo Proxmox da gestire:
ssh-copy-id -i /root/.ssh/id_rsa.pub root@192.168.1.10
ssh-copy-id -i /root/.ssh/id_rsa.pub root@192.168.1.11
# ... etc
```

**Oppure usa l'interfaccia web:**
1. Vai su **🔑 Chiavi SSH**
2. Clicca **Distribuisci Chiave**
3. Seleziona i nodi e inserisci la password root

### 3. Aggiungi Nodi

1. Vai su **Nodi** → **➕ Aggiungi Nodo**
2. Inserisci:
   - **Nome**: identificativo (es. `pve-node-01`)
   - **Hostname/IP**: indirizzo del nodo
   - **Porta SSH**: default 22
   - **Utente SSH**: default root
   - **Chiave SSH**: `/root/.ssh/id_rsa`
   - **Tipo**: PVE (Proxmox VE) o PBS (Proxmox Backup Server)
3. Clicca **Aggiungi** e poi **Test** per verificare la connessione

### 4. Verifica Installazione

```bash
# Esegui lo script di test
./test-installation.sh

# Per test completi (include pytest)
./test-installation.sh --full
```

---

## 🎨 Funzionalità Principali

### 📊 Dashboard
- **Overview Nodi** - Stato, risorse, storage di tutti i nodi
- **Overview VM** - Lista VM con stato, risorse, ultimo backup
- **Statistiche Job** - Conteggio job per tipo e stato
- **Log Recenti** - Ultime attività del sistema
- **Quick Actions** - Accesso rapido alle funzioni principali

### 🖥️ Gestione Nodi
- **Aggiunta Nodi** - Supporto PVE e PBS
- **Test Connessione** - Verifica SSH e accesso Proxmox API
- **Informazioni Dettagliate** - Storage, network, risorse
- **Installazione Sanoid** - Installazione automatica su nodi remoti
- **Gestione Dataset** - Visualizzazione e gestione dataset ZFS/BTRFS

### 🖥️ Gestione VM
- **Lista VM** - Visualizzazione VM per nodo
- **Dettagli VM** - Configurazione completa, dischi, network
- **Snapshot VM** - Visualizzazione snapshot Proxmox, Sanoid, Syncoid
- **Configurazione Snapshot** - Policy snapshot per singola VM
- **Backup VM** - Visualizzazione backup PBS per VM
- **Azioni Rapide** - Creazione job replica/backup/migrazione da VM

### 📸 Snapshot Management
- **Snapshot per Dataset** - Gestione snapshot ZFS/BTRFS
- **Snapshot per VM** - Gestione snapshot individuale per VM
- **Template Retention** - Policy predefinite:
  - **production**: 48h, 90d, 12w, 24m, 5y
  - **default**: 24h, 30d, 4w, 12m
  - **minimal**: 12h, 7d
  - **backup**: 30d, 8w, 12m, 2y
  - **vm**: 24h, 14d, 4w, 6m
- **Rollback** - Ripristino da snapshot
- **Clone** - Creazione dataset da snapshot

### 🔄 Replica ZFS/BTRFS
- **Job di Replica** - Creazione job replica tra nodi
- **Scheduling** - Cron jobs o preset comuni
- **Registrazione VM** - Registrazione automatica VM replicate
- **Compatibilità Hardware** - Verifica CPU, network, storage
- **Snapshot Mirati** - Gestione snapshot durante replica
- **Compressione** - Supporto lz4, gzip, zstd

### 💾 Backup Jobs (PBS)
- **Backup Incrementali** - Backup VM verso Proxmox Backup Server
- **Scheduling Flessibile** - Backup programmati
- **Retention Policy** - Gestione retention backup
- **Multi-Storage** - Supporto storage non-ZFS (LVM, local, etc.)

### 🔄 Replica Jobs (PBS)
- **Backup → Restore** - Workflow completo backup e restore
- **Registrazione VM** - Registrazione automatica VM ripristinate
- **Scheduling** - Replica programmata
- **Multi-Storage** - Supporto qualsiasi storage

### 🚀 Migrazione VM
- **Migrazione/Copia** - Trasferimento VM tra nodi
- **Supporto Multi-Disco** - Gestione VM con più dischi
- **Supporto Multi-Network** - Configurazione multiple interfacce
- **Riconfigurazione Hardware** - Modifica CPU, RAM, storage, network
- **Snapshot Mirati** - Mantenimento snapshot selettivi
- **Conferma Sovrascrittura** - Protezione dati

### 🔑 Gestione SSH
- **Generazione Chiavi** - Creazione automatica RSA/Ed25519
- **Distribuzione Automatica** - Copia chiavi su tutti i nodi
- **Test Connessioni** - Verifica connettività
- **Mesh SSH** - Configurazione per replica diretta

### 💾 Backup Configurazione Host
- **Backup Config Proxmox** - Backup automatico configurazione nodi
- **Retention Policy** - Gestione retention
- **Restore Config** - Ripristino configurazione

### 🔔 Notifiche
- **Email (SMTP)** - Notifiche via email
- **Webhook** - Integrazione servizi esterni
- **Telegram** - Notifiche bot Telegram
- **Riepilogo Giornaliero** - Report automatici
- **Trigger Personalizzabili** - Notifica su successo/errore/warning

### ⚙️ Impostazioni
- **Generale** - Configurazioni di base
- **Autenticazione** - Metodo login (Proxmox/Locale)
- **Notifiche** - Configurazione canali notifica
- **SSL/HTTPS** - Configurazione certificati e porta
- **Aggiornamenti** - Sistema aggiornamento web
- **Database** - Reset database (con backup)

---

## 📖 Guida all'Uso

> 💡 **Guida Rapida**: [GUIDA_RAPIDA.md](GUIDA_RAPIDA.md)  
> 📘 **Guida Completa**: [GUIDA_UTENTE.md](GUIDA_UTENTE.md)

### Configurare Snapshot (Sanoid)

#### Per Dataset
1. Vai su **Snapshot**
2. Seleziona un nodo dal dropdown
3. Per ogni dataset:
   - Abilita checkbox **Sanoid**
   - Scegli **Template** retention
   - Clicca **Applica Config**

#### Per VM
1. Vai su **VM** → Seleziona VM
2. Tab **Snapshot**
3. Clicca **⚙️ Configura Snapshot**
4. Abilita e configura policy
5. Salva

### Creare Job di Replica ZFS/BTRFS

1. Vai su **Replica** → **➕ Nuova Replica**
2. **Step 1**: Seleziona nodo sorgente e VM
3. **Step 2**: Seleziona nodo destinazione e pool
4. **Step 3**: Configura:
   - **Nome job**
   - **Schedule** (cron o preset)
   - **Compressione**
   - **Registra VM** (opzionale)
   - **Forza CPU host** (opzionale)
5. Verifica **Compatibilità** (CPU, network, storage)
6. Salva

### Creare Backup Job (PBS)

1. Vai su **Backup (PBS)** → **➕ Nuovo Backup**
2. Configura:
   - **Nome**: identificativo
   - **Nodo Sorgente**: nodo PVE con VM
   - **VM**: seleziona VM
   - **PBS Node**: nodo Proxmox Backup Server
   - **Schedule**: frequenza backup
3. Salva

### Creare Replica Job (PBS)

1. Vai su **Replica Jobs (PBS)** → **➕ Nuovo Job**
2. Configura:
   - **Nome**: identificativo
   - **Nodo Sorgente**: nodo PVE con VM
   - **VMID**: ID VM
   - **PBS Node**: nodo Proxmox Backup Server
   - **Nodo Destinazione**: dove ripristinare
   - **Schedule**: frequenza backup/restore
3. Il sistema eseguirà:
   - Backup VM su PBS
   - Restore su nodo destinazione
   - Registrazione VM

### Migrare/Copiare VM

1. Vai su **Migrazione VM** → **➕ Nuova Migrazione**
2. Configura:
   - **Nome**: identificativo
   - **Tipo**: Migrazione (move) o Copia
   - **Nodo Sorgente**: nodo origine
   - **VM**: seleziona VM
   - **Nodo Destinazione**: nodo destinazione
   - **VMID Destinazione**: ID VM destinazione (opzionale)
3. **Riconfigurazione Hardware** (opzionale):
   - CPU, RAM
   - Storage dischi
   - Network bridges
4. **Snapshot**:
   - Crea snapshot prima migrazione
   - Mantieni snapshot dopo migrazione
5. Salva ed esegui

### Configurare HTTPS

1. Vai su **Impostazioni** → **🔒 SSL/HTTPS**
2. **Genera Certificato** o **Carica Certificato** personalizzato
3. Modifica **Porta Web Server** (opzionale)
4. Abilita **HTTPS**
5. Clicca **💾 Salva Configurazione**
6. Clicca **🔄 Riavvia per Applicare**
7. Accedi con `https://IP:PORTA`

### Aggiornare Sistema

1. Vai su **Impostazioni** → **🔄 Aggiornamenti**
2. Clicca **🔍 Verifica Aggiornamenti**
3. Se disponibile, clicca **⬆️ Aggiorna Sistema**
4. Monitora il processo in tempo reale
5. Al termine, ricarica la pagina (F5) e rieffettua login

---

## ⚙️ Configurazione

### Impostazioni Generali

**Impostazioni** → **Generale**:
- **Compressione Default**: lz4, gzip, zstd, none
- **Mbuffer Default**: dimensione buffer
- **Retention Log**: giorni di retention log

### Autenticazione

**Impostazioni** → **Autenticazione**:
- **Metodo**: Proxmox o Locale
- **Nodo Proxmox**: per autenticazione Proxmox
- **Porta Proxmox**: default 8006
- **Verifica SSL**: abilita/disabilita
- **Timeout Sessione**: minuti (default 480)
- **Fallback Locale**: permette login locale se Proxmox fallisce

### Notifiche

**Impostazioni** → **Notifiche**:

#### Email (SMTP)
```
Server SMTP: smtp.example.com
Porta: 587
TLS: Abilitato
Username: sanoid@example.com
Password: ********
Destinatario: admin@example.com
Prefisso Oggetto: [DAPX]
```

#### Webhook
```
URL: https://hooks.slack.com/services/xxx
Secret: (opzionale)
```

#### Telegram
```
Bot Token: 123456789:ABC...
Chat ID: -1001234567890
```

#### Trigger
- ✅ Notifica su successo
- ✅ Notifica su errore
- ✅ Notifica su warning

### SSL/HTTPS

**Impostazioni** → **SSL/HTTPS**:
- **Porta Web Server**: 1-65535 (default 8420)
- **Abilita HTTPS**: checkbox (richiede certificato)
- **Genera Certificato**: auto-firmato
- **Carica Certificato**: personalizzato (PEM)

### Variabili d'Ambiente

File: `/etc/dapx-backandrepl/.env` (o `/opt/dapx-backandrepl/backend/.env`)

```bash
# Database
DAPX_DB=/var/lib/dapx-backandrepl/dapx-backandrepl.db

# Porta web
DAPX_PORT=8420

# SSL
DAPX_SSL=false

# Chiave segreta JWT
DAPX_SECRET_KEY=your-secret-key

# Scadenza token (minuti)
DAPX_TOKEN_EXPIRE=480

# Origini CORS
DAPX_CORS_ORIGINS=

# Livello log
DAPX_LOG_LEVEL=INFO
```

---

## 🔧 Amministrazione

### Comandi Servizio

```bash
# Stato
systemctl status dapx-backandrepl  # o sanoid-manager

# Avvia/Ferma/Riavvia
systemctl start dapx-backandrepl
systemctl stop dapx-backandrepl
systemctl restart dapx-backandrepl

# Log in tempo reale
journalctl -u dapx-backandrepl -f

# Log applicazione
tail -f /var/log/dapx-backandrepl/dapx-backandrepl.log
```

### Backup Database

```bash
# Backup manuale
cp /var/lib/dapx-backandrepl/dapx-backandrepl.db ~/backup-$(date +%Y%m%d).db

# Restore
systemctl stop dapx-backandrepl
cp ~/backup.db /var/lib/dapx-backandrepl/dapx-backandrepl.db
systemctl start dapx-backandrepl
```

### Aggiornamento

#### Via Web UI (Consigliato)
1. **Impostazioni** → **🔄 Aggiornamenti**
2. Clicca **⬆️ Aggiorna Sistema**

#### Via Git
```bash
cd /opt/dapx-backandrepl
git pull origin main
systemctl restart dapx-backandrepl
```

#### Container LXC
```bash
pct exec <ID> -- bash -c "cd /opt/dapx-backandrepl && git pull && systemctl restart dapx-backandrepl"
```

#### Docker
```bash
cd /path/to/dapx-backandrepl
git pull
docker-compose restart
```

### Reset Database

⚠️ **ATTENZIONE**: Questa operazione elimina TUTTI i dati!

1. **Impostazioni** → **Generale** → **🗄️ Database**
2. Seleziona **Crea backup prima del reset**
3. Clicca **🗑️ Reset Database**
4. Conferma
5. Riavvia servizio e ricrea utente admin

---

## 🔒 Sicurezza

### Best Practices

1. **Accesso Rete**: Limita porta 8420 solo alla rete di gestione
2. **HTTPS**: Abilita HTTPS per comunicazioni sicure
3. **SSH**: Usa chiavi SSH dedicate
4. **Password**: Password complesse per admin locale
5. **Firewall**: Configura firewall appropriato

### Firewall

```bash
# UFW
ufw allow from 192.168.100.0/24 to any port 8420

# iptables
iptables -A INPUT -p tcp --dport 8420 -s 192.168.100.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 8420 -j DROP
```

### Reverse Proxy con SSL (Nginx)

```nginx
server {
    listen 443 ssl;
    server_name dapx.example.com;
    
    ssl_certificate /etc/ssl/certs/dapx.pem;
    ssl_certificate_key /etc/ssl/private/dapx.key;
    
    location / {
        proxy_pass http://127.0.0.1:8420;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```

---

## 🐛 Troubleshooting

### Il servizio non parte

```bash
# Controlla i log
journalctl -u dapx-backandrepl -n 50

# Verifica permessi
ls -la /opt/dapx-backandrepl/
ls -la /var/lib/dapx-backandrepl/

# Testa manualmente
cd /opt/dapx-backandrepl/backend
python3 -c "from main import app; print('OK')"
```

### Errore autenticazione

```bash
# Verifica configurazione
cat /etc/dapx-backandrepl/.env

# Reset password admin
cd /opt/dapx-backandrepl/backend
python3 -c "
from database import SessionLocal, User
from services.auth_service import auth_service
db = SessionLocal()
user = db.query(User).filter(User.username == 'admin').first()
if user:
    user.hashed_password = auth_service.get_password_hash('newpassword')
    db.commit()
    print('Password reset!')
"
```

### Connessione SSH fallisce

```bash
# Testa connessione manuale
ssh -i /root/.ssh/id_rsa -p 22 root@hostname "echo OK"

# Verifica chiave autorizzata
ssh root@hostname "cat ~/.ssh/authorized_keys"
```

### Sanoid non crea snapshot

```bash
# Verifica config sul nodo
ssh root@nodo "cat /etc/sanoid/sanoid.conf"

# Esegui manualmente
ssh root@nodo "sanoid --cron --verbose"

# Verifica timer systemd
ssh root@nodo "systemctl status sanoid.timer"
```

### Aggiornamento fallisce

```bash
# Verifica che .git esista
ls -la /opt/dapx-backandrepl/.git

# Se manca, inizializza git
cd /opt/dapx-backandrepl
git init
git remote add origin https://github.com/grandir66/dapx-backandrepl.git
git fetch origin
git reset --hard origin/main
```

---

## 📝 API Reference

**Base URL**: `http://localhost:8420/api`  
**Documentazione Interattiva**: `http://localhost:8420/docs`

### Autenticazione

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| POST | `/auth/login` | Login utente |
| POST | `/auth/logout` | Logout |
| POST | `/auth/refresh` | Rinnova token |
| GET | `/auth/me` | Info utente corrente |

### Nodi

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/nodes/` | Lista nodi |
| POST | `/nodes/` | Crea nodo |
| GET | `/nodes/{id}` | Dettaglio nodo |
| PUT | `/nodes/{id}` | Modifica nodo |
| DELETE | `/nodes/{id}` | Elimina nodo |
| POST | `/nodes/{id}/test` | Test connessione |
| GET | `/nodes/{id}/datasets` | Lista dataset ZFS |
| GET | `/nodes/{id}/bridges` | Lista network bridges |
| GET | `/nodes/{id}/storages` | Lista storage |

### Snapshot

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/snapshots/node/{id}` | Lista snapshot |
| GET | `/snapshots/vm/{node_id}/{vm_id}/all` | Snapshot VM (tutti i tipi) |
| GET | `/snapshots/vm/{node_id}/{vm_id}/config` | Config snapshot VM |
| PUT | `/snapshots/vm/{node_id}/{vm_id}/config` | Aggiorna config snapshot VM |
| POST | `/snapshots/node/{id}/apply-config` | Applica config Sanoid |
| DELETE | `/snapshots/{name}` | Elimina snapshot |

### Replica ZFS/BTRFS

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/sync-jobs/` | Lista job |
| POST | `/sync-jobs/` | Crea job |
| GET | `/sync-jobs/{id}` | Dettaglio job |
| PUT | `/sync-jobs/{id}` | Modifica job |
| DELETE | `/sync-jobs/{id}` | Elimina job |
| POST | `/sync-jobs/{id}/run` | Esegui job |
| GET | `/sync-jobs/{id}/compatibility` | Verifica compatibilità |

### Backup Jobs (PBS)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/backup-jobs/` | Lista backup job |
| POST | `/backup-jobs/` | Crea backup job |
| PUT | `/backup-jobs/{id}` | Modifica backup job |
| DELETE | `/backup-jobs/{id}` | Elimina backup job |
| POST | `/backup-jobs/{id}/run` | Esegui backup |

### Replica Jobs (PBS)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/recovery-jobs/` | Lista recovery job |
| POST | `/recovery-jobs/` | Crea recovery job |
| GET | `/recovery-jobs/{id}` | Dettaglio recovery job |
| PUT | `/recovery-jobs/{id}` | Modifica recovery job |
| DELETE | `/recovery-jobs/{id}` | Elimina recovery job |
| POST | `/recovery-jobs/{id}/run` | Esegui recovery completo |
| POST | `/recovery-jobs/{id}/backup-only` | Solo fase backup |
| POST | `/recovery-jobs/{id}/restore-only` | Solo fase restore |

### Migrazione VM

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/migration-jobs/` | Lista migration job |
| POST | `/migration-jobs/` | Crea migration job |
| GET | `/migration-jobs/{id}` | Dettaglio migration job |
| PUT | `/migration-jobs/{id}` | Modifica migration job |
| DELETE | `/migration-jobs/{id}` | Elimina migration job |
| POST | `/migration-jobs/{id}/run` | Esegui migrazione |

### Impostazioni

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/settings/` | Leggi impostazioni |
| PUT | `/settings/` | Aggiorna impostazioni |
| GET | `/settings/auth/config` | Config autenticazione |
| PUT | `/settings/auth/config` | Aggiorna auth config |
| GET | `/settings/notifications` | Config notifiche |
| PUT | `/settings/notifications` | Aggiorna notifiche |
| GET | `/settings/ssl/status` | Stato SSL |
| POST | `/settings/ssl/generate-cert` | Genera certificato |
| POST | `/settings/ssl/upload-cert` | Carica certificato |
| GET | `/settings/server/config` | Config server (porta, HTTPS) |
| PUT | `/settings/server/config` | Aggiorna config server |
| POST | `/settings/server/restart` | Riavvia server |
| POST | `/settings/database/reset` | Reset database |

### Aggiornamenti

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/updates/check` | Verifica aggiornamenti |
| GET | `/updates/status` | Stato aggiornamento |
| POST | `/updates/start` | Avvia aggiornamento |
| GET | `/updates/version` | Versione corrente |

---

## 📁 Struttura Directory

```
/opt/dapx-backandrepl/          # Applicazione
├── backend/
│   ├── main.py                 # Entry point FastAPI
│   ├── database.py             # Models SQLAlchemy
│   ├── routers/                # API endpoints
│   │   ├── auth.py
│   │   ├── nodes.py
│   │   ├── snapshots.py
│   │   ├── sync_jobs.py
│   │   ├── backup_jobs.py
│   │   ├── recovery_jobs.py
│   │   ├── migration_jobs.py
│   │   ├── vms.py
│   │   ├── logs.py
│   │   ├── settings.py
│   │   ├── ssh_keys.py
│   │   ├── updates.py
│   │   └── ...
│   ├── services/               # Business logic
│   │   ├── auth_service.py
│   │   ├── proxmox_service.py
│   │   ├── sanoid_service.py
│   │   ├── syncoid_service.py
│   │   ├── pbs_service.py
│   │   ├── migration_service.py
│   │   └── ...
│   └── certs/                  # Certificati SSL
├── frontend/
│   └── dist/
│       └── index.html          # Single-page application
├── lxc/                        # Script LXC
├── VERSION                     # Versione corrente
└── requirements.txt

/etc/dapx-backandrepl/          # Configurazione
└── .env                        # Variabili d'ambiente

/var/lib/dapx-backandrepl/      # Dati persistenti
└── dapx-backandrepl.db         # Database SQLite

/var/log/dapx-backandrepl/      # Log
└── dapx-backandrepl.log
```

---

## 🧪 Testing

```bash
cd /opt/dapx-backandrepl/backend
source venv/bin/activate

# Tutti i test
pytest tests/ -v

# Con coverage
pytest tests/ -v --cov=. --cov-report=html

# Test specifico
pytest tests/test_auth.py -v
```

---

## 🤝 Contribuire

1. Fork del repository
2. Crea un branch (`git checkout -b feature/AmazingFeature`)
3. Commit (`git commit -m 'Add AmazingFeature'`)
4. Push (`git push origin feature/AmazingFeature`)
5. Apri una Pull Request

---

## 📄 Licenza

**Licenza Proprietaria** - © 2025 Domarc S.r.l.

Questo software è proprietà esclusiva di Domarc S.r.l. Tutti i diritti riservati.
L'uso, la copia, la modifica e la distribuzione non autorizzati sono vietati.

Per informazioni sulla licenza commerciale: [info@domarc.it](mailto:info@domarc.it)

---

## 🙏 Credits

- [Sanoid/Syncoid](https://github.com/jimsalterjrs/sanoid) - Jim Salter
- [Proxmox VE](https://www.proxmox.com/)
- [FastAPI](https://fastapi.tiangolo.com/)
- [Vue.js](https://vuejs.org/)

---

## 📞 Contatti

**Domarc S.r.l.**
- 🌐 Website: [www.domarc.it](https://www.domarc.it)
- 📧 Email: [info@domarc.it](mailto:info@domarc.it)
- 📍 Italia

---

## 📋 Changelog

Vedi [CHANGELOG.md](CHANGELOG.md) per la lista completa delle modifiche.

---

## 📚 Documentazione

- **[GUIDA_RAPIDA.md](GUIDA_RAPIDA.md)** - Guida rapida per iniziare in 5 minuti
- **[GUIDA_UTENTE.md](GUIDA_UTENTE.md)** - Guida utente completa e dettagliata
- **[DOCKER.md](DOCKER.md)** - Installazione e gestione Docker
- **[lxc/README.md](lxc/README.md)** - Installazione e gestione LXC
- **[CHANGELOG.md](CHANGELOG.md)** - Storico delle versioni e modifiche
