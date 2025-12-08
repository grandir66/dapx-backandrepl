# 📘 Manuale Completo DAPX-backandrepl v3.4.5

**Sistema centralizzato di backup e replica per infrastrutture Proxmox VE**

> **© 2025 Domarc S.r.l.** - Tutti i diritti riservati  
> [www.domarc.it](https://www.domarc.it)

---

## 📑 Indice

1. [Introduzione](#introduzione)
2. [Installazione](#installazione)
3. [Configurazione Iniziale](#configurazione-iniziale)
4. [Funzionalità Principali](#funzionalità-principali)
5. [Gestione Nodi](#gestione-nodi)
6. [Replica VM](#replica-vm)
7. [Backup e Restore](#backup-e-restore)
8. [Migrazione VM](#migrazione-vm)
9. [Snapshot Management](#snapshot-management)
10. [Notifiche](#notifiche)
11. [Amministrazione](#amministrazione)
12. [Troubleshooting](#troubleshooting)
13. [API Reference](#api-reference)

---

## 🎯 Introduzione

DAPX-backandrepl è un sistema centralizzato per la gestione di backup, replica e snapshot di macchine virtuali in ambienti Proxmox VE. Supporta:

- **ZFS Replication** tramite Syncoid
- **BTRFS Replication** tramite btrfs send/receive
- **PBS Backup/Restore** tramite Proxmox Backup Server
- **VM Migration** tra nodi Proxmox
- **Snapshot Management** con Sanoid
- **Multi-tenant** con gestione utenti e permessi

### Requisiti di Sistema

**Nodo Manager:**
- Proxmox VE 7.x / 8.x o Debian 11/12 / Ubuntu 20.04+
- Python 3.9+
- ZFS o BTRFS (opzionale, per funzionalità snapshot)
- Accesso root o sudo

**Nodi Gestiti:**
- Proxmox VE con ZFS/BTRFS per replica diretta
- Proxmox Backup Server per backup/restore
- Accesso SSH (porta 22)
- Chiave SSH autorizzata

---

## 🚀 Installazione

### Installazione Automatica

```bash
cd /opt
git clone https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl
chmod +x install.sh
./install.sh
```

L'installer:
1. Crea l'ambiente virtuale Python
2. Installa le dipendenze
3. Configura il servizio systemd
4. Genera chiavi SSH
5. Crea la struttura directory

### Verifica Installazione

```bash
# Controlla stato servizio
systemctl status sanoid-manager

# Testa installazione
./test-installation.sh

# Log in tempo reale
journalctl -u sanoid-manager -f
```

---

## ⚙️ Configurazione Iniziale

### 1. Accesso Web UI

Apri il browser su: `http://<IP-NODO>:8420`

### 2. Setup Wizard

Al primo accesso, completa il wizard:

1. **Crea Account Amministratore**
   - Username: `admin` (consigliato)
   - Password: (scegli una password sicura)
   - Email: (opzionale, per notifiche)

2. **Configura Autenticazione**
   - **Locale**: Utenti gestiti direttamente in DAPX
   - **Proxmox**: Login con credenziali Proxmox VE (PAM, PVE, LDAP, AD)

3. **Configurazione Base**
   - Timezone
   - Lingua interfaccia
   - Preferenze notifiche

### 3. Configurazione SSH

L'installer mostra la chiave pubblica SSH. Copiala su ogni nodo:

```bash
# Mostra chiave pubblica
cat /root/.ssh/id_rsa.pub

# Su ogni nodo Proxmox da gestire:
ssh-copy-id -i /root/.ssh/id_rsa.pub root@192.168.1.10
```

---

## 🎨 Funzionalità Principali

### Dashboard

La dashboard mostra:
- **Panoramica Nodi**: Stato, risorse, VM
- **Statistiche**: Job attivi, ultimi backup, errori
- **Attività Recente**: Log ultime operazioni
- **Quick Actions**: Accesso rapido a funzioni comuni

### Gestione Utenti

**Ruoli:**
- **Admin**: Accesso completo, gestione utenti, configurazione sistema
- **Operator**: Crea/modifica job, esegue operazioni
- **Viewer**: Solo visualizzazione

**Restrizioni:**
- Gli utenti possono essere limitati a specifici nodi
- Configurabile in **Impostazioni** → **Utenti**

---

## 🖥️ Gestione Nodi

### Aggiungere un Nodo

1. Vai su **Nodi** → **Aggiungi Nodo**
2. Compila i campi:
   - **Nome**: Identificativo (es. `pve-node-01`)
   - **Hostname/IP**: Indirizzo del nodo
   - **Porta SSH**: Default 22
   - **Utente SSH**: Default `root`
   - **Chiave SSH**: `/root/.ssh/id_rsa`
   - **Tipo**: PVE (Proxmox VE) o PBS (Proxmox Backup Server)
   - **Storage Type**: ZFS, BTRFS o altro
3. Clicca **Aggiungi**
4. Clicca **Test** per verificare la connessione

### Installazione Sanoid

Per abilitare snapshot automatici:

1. Seleziona il nodo
2. Clicca **Installa Sanoid**
3. Attendi il completamento (può richiedere alcuni minuti)
4. Verifica: `ssh root@nodo "systemctl status sanoid.timer"`

---

## 🔄 Replica VM

### Replica ZFS/BTRFS

**Workflow:**
1. Vai su **Replica**
2. Clicca **➕ Nuova Replica**
3. Seleziona:
   - **Metodo**: ZFS/Syncoid o BTRFS
   - **Nodo Sorgente**: Da dove replicare
   - **Nodo Destinazione**: Dove replicare
4. Seleziona la **VM** da replicare
5. Configura:
   - **Pool ZFS Destinazione**
   - **Sottocartella** (es. `replica`)
   - **VMID Destinazione** (se diverso)
   - **Schedule** (cron format)
   - **Compressione**: lz4, zstd, gzip
   - **Versioni da mantenere**: Numero snapshot
6. Opzioni:
   - **Registra VM**: Registra automaticamente sul nodo destinazione
   - **Force CPU Host**: Cambia CPU type a `host`
   - **Network Bridge Mapping**: Mappa bridge di rete diversi

**Schedule Esempi:**
- `0 */4 * * *` = Ogni 4 ore
- `0 2 * * *` = Ogni notte alle 2:00
- `*/30 * * * *` = Ogni 30 minuti
- `0 0 * * 0` = Ogni domenica a mezzanotte

### Replica Jobs (PBS)

Per VM con storage non-ZFS (LVM, local, etc.):

1. Vai su **Replica (PBS)**
2. Clicca **Nuovo Replica Job**
3. Configura:
   - **Nodo Sorgente**: Nodo PVE con la VM
   - **VMID**: ID della VM
   - **PBS Node**: Nodo Proxmox Backup Server
   - **Nodo Destinazione**: Dove ripristinare
   - **Schedule**: Frequenza backup/restore
4. Il sistema eseguirà automaticamente:
   - Backup VM su PBS
   - Restore su nodo destinazione
   - Registrazione VM

---

## 💾 Backup e Restore

### Backup Jobs (PBS)

1. Vai su **Backup (PBS)**
2. Clicca **Nuovo Backup Job**
3. Configura:
   - **Nodo Sorgente**: Nodo PVE
   - **VM**: VM da backuppare
   - **PBS Node**: Nodo Proxmox Backup Server
   - **Storage PBS**: Datastore su PBS
   - **Schedule**: Frequenza backup
   - **Retention**: Numero backup da mantenere

### Restore da Backup

1. Vai su **Restore (PBS)**
2. Seleziona **Nodo PBS**
3. Sfoglia i backup disponibili
4. Seleziona il backup da ripristinare
5. Configura:
   - **Nodo Destinazione**
   - **VMID Destinazione**
   - **Storage Destinazione**
6. Clicca **Esegui Restore**

---

## 🚀 Migrazione VM

Per copiare o spostare VM tra nodi (indipendentemente da ZFS/PBS):

1. Vai su **Migrazione VM**
2. Clicca **➕ Nuovo Job Migrazione**
3. Configura:
   - **Nodo Sorgente** e **Destinazione**
   - **VM da Migrare**
   - **Tipo Migrazione**: Copy (copia) o Move (sposta)
   - **VMID Destinazione**
4. **Riconfigurazione Hardware** (opzionale):
   - **RAM**: Dimensione memoria
   - **CPU**: Cores, Sockets, Type
   - **Network**: Bridge mapping per ogni scheda
   - **Storage**: Storage mapping per ogni disco
5. **Opzioni**:
   - **Crea Snapshot**: Crea snapshot prima della migrazione
   - **Mantieni Snapshot**: Numero snapshot da mantenere
   - **Avvia dopo migrazione**: Avvia automaticamente la VM
6. **Schedule** (opzionale): Per migrazioni ricorrenti

**Nota**: Per "Copy", il sistema usa `vzdump` + restore. Per "Move", usa `qm migrate` / `pct migrate`.

---

## 📸 Snapshot Management

### Snapshot Proxmox

Snapshot creati manualmente o tramite backup Proxmox.

### Snapshot Sanoid

Snapshot automatici configurati con Sanoid:

1. Vai su **Proxmox** → Seleziona una VM
2. Tab **Snapshot**
3. Sezione **Configurazione Sanoid**
4. Abilita e configura:
   - **Schedule**: Quando creare snapshot (cron)
   - **Retention**: Hourly, Daily, Weekly, Monthly, Yearly
   - **Template**: production, default, minimal, backup, vm

### Snapshot Syncoid

Snapshot creati durante la replica ZFS (`syncoid_*`).

### Snapshot Backup

Snapshot di retention per replica (`backup_*`).

### Visualizzazione Snapshot

Nella pagina VM, tab **Snapshot**, vedi:
- **Proxmox Snapshots**: Snapshot Proxmox nativi
- **Sanoid Snapshots**: Snapshot automatici (`autosnap_*`)
- **Syncoid Snapshots**: Snapshot replica (`syncoid_*`)
- **Backup Snapshots**: Snapshot retention (`backup_*`)

---

## 🔔 Notifiche

### Configurazione Email

1. Vai su **Impostazioni** → **Notifiche**
2. Abilita **SMTP**
3. Configura:
   - **Server SMTP**: `smtp.example.com`
   - **Porta**: 587 (TLS) o 465 (SSL)
   - **Username/Password**
   - **Destinatario**: Email predefinita

### Configurazione Webhook

1. Abilita **Webhook**
2. Inserisci **URL** del webhook
3. Configura **Header** personalizzati (opzionale)

### Modalità Notifica

Per ogni job, configura **Notify Mode**:
- **daily**: Solo nel riepilogo giornaliero
- **always**: Ad ogni esecuzione
- **failure**: Solo in caso di errore
- **never**: Disabilitate

---

## 🛠️ Amministrazione

### Reset Database

⚠️ **ATTENZIONE**: Operazione irreversibile!

Per riportare il sistema allo stato iniziale:

1. Vai su **Impostazioni** → **Generale**
2. Sezione **Database**
3. Clicca **Reset Database**
4. Conferma con `confirm: true`
5. Opzionale: Crea backup automatico
6. Riavvia il servizio dopo il reset

**API:**
```bash
POST /api/settings/database/reset
{
  "confirm": true,
  "backup": true
}
```

### Backup Database

```bash
# Backup manuale
cp /var/lib/sanoid-manager/sanoid-manager.db \
   ~/backup-$(date +%Y%m%d).db

# Restore
systemctl stop sanoid-manager
cp ~/backup-20250101.db /var/lib/sanoid-manager/sanoid-manager.db
systemctl start sanoid-manager
```

### Aggiornamento

```bash
cd /opt/dapx-backandrepl
git pull
./update.sh
systemctl restart sanoid-manager
```

### Log

```bash
# Log servizio
journalctl -u sanoid-manager -f

# Log applicazione
tail -f /var/log/sanoid-manager/sanoid-manager.log

# Log specifico
journalctl -u sanoid-manager --since "1 hour ago"
```

### SSL/TLS

**Genera Certificato:**
1. Vai su **Impostazioni** → **SSL**
2. Clicca **Genera Certificato**
3. Inserisci hostname e IP
4. Il certificato viene generato automaticamente

**Carica Certificato Personalizzato:**
1. Clicca **Carica Certificato**
2. Incolla certificato e chiave privata (formato PEM)

---

## 🐛 Troubleshooting

### Servizio non parte

```bash
# Controlla log
journalctl -u sanoid-manager -n 50

# Verifica permessi
ls -la /opt/dapx-backandrepl/
ls -la /var/lib/sanoid-manager/

# Testa manualmente
cd /opt/dapx-backandrepl/backend
source venv/bin/activate
python -c "from main import app; print('OK')"
```

### Errore autenticazione

```bash
# Verifica configurazione
cat /etc/sanoid-manager/sanoid-manager.env

# Reset password admin
cd /opt/dapx-backandrepl/backend
source venv/bin/activate
python -c "
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
# Testa connessione
ssh -i /root/.ssh/id_rsa -p 22 root@hostname "echo OK"

# Verifica chiave autorizzata
ssh root@hostname "cat ~/.ssh/authorized_keys"
```

### Sanoid non crea snapshot

```bash
# Verifica config
ssh root@nodo "cat /etc/sanoid/sanoid.conf"

# Esegui manualmente
ssh root@nodo "sanoid --cron --verbose"

# Verifica timer
ssh root@nodo "systemctl status sanoid.timer"
```

### Replica non funziona

1. Verifica connessione SSH tra nodi
2. Controlla che i dataset esistano
3. Verifica permessi ZFS/BTRFS
4. Controlla log job: **Logs** → Filtra per job ID

---

## 📡 API Reference

Base URL: `http://localhost:8420/api`

Documentazione interattiva: `http://localhost:8420/docs`

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
| GET | `/nodes/{id}/datasets` | Lista dataset |
| GET | `/nodes/{id}/bridges` | Lista network bridges |
| GET | `/nodes/{id}/storages` | Lista storage |

### Replica (Sync Jobs)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/sync-jobs/` | Lista job |
| POST | `/sync-jobs/` | Crea job |
| POST | `/sync-jobs/vm-replica` | Crea job replica VM |
| GET | `/sync-jobs/{id}` | Dettaglio job |
| PUT | `/sync-jobs/{id}` | Modifica job |
| DELETE | `/sync-jobs/{id}` | Elimina job |
| POST | `/sync-jobs/{id}/run` | Esegui job |
| POST | `/sync-jobs/{id}/register-vm` | Registra VM |

### Backup Jobs (PBS)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/backup-jobs/` | Lista job |
| POST | `/backup-jobs/` | Crea job |
| POST | `/backup-jobs/{id}/run` | Esegui backup |

### Replica Jobs (PBS)

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/recovery-jobs/` | Lista job |
| POST | `/recovery-jobs/` | Crea job |
| POST | `/recovery-jobs/{id}/run` | Esegui replica completa |

### Migrazione VM

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/migration-jobs/` | Lista job |
| POST | `/migration-jobs/` | Crea job |
| POST | `/migration-jobs/{id}/run` | Esegui migrazione |
| POST | `/migration-jobs/{id}/run?force=true` | Esegui con overwrite |

### Snapshot

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/snapshots/vm/{node_id}/{vm_id}/all` | Tutti snapshot VM |
| GET | `/snapshots/vm/{node_id}/{vm_id}/config` | Config Sanoid VM |
| PUT | `/snapshots/vm/{node_id}/{vm_id}/config` | Aggiorna config |

### Impostazioni

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/settings/` | Leggi impostazioni |
| PUT | `/settings/` | Aggiorna impostazioni |
| POST | `/settings/database/reset` | Reset database |
| POST | `/settings/ssl/generate-cert` | Genera certificato SSL |

---

## 📚 File e Directory

### Struttura Installazione

```
/opt/dapx-backandrepl/          # Applicazione
├── backend/                    # Backend Python
│   ├── main.py                 # Entry point FastAPI
│   ├── database.py             # Models SQLAlchemy
│   ├── routers/                # API endpoints
│   ├── services/               # Business logic
│   └── venv/                   # Virtual environment
├── frontend/
│   └── dist/
│       └── index.html          # Single-page application
└── install.sh                  # Installer

/etc/sanoid-manager/            # Configurazione
└── sanoid-manager.env          # Variabili d'ambiente

/var/lib/sanoid-manager/        # Dati persistenti
├── sanoid-manager.db           # Database SQLite
└── backups/                    # Backup database

/var/log/sanoid-manager/        # Log
└── sanoid-manager.log
```

### File di Configurazione

**Variabili d'Ambiente** (`/etc/sanoid-manager/sanoid-manager.env`):
```bash
SANOID_MANAGER_SECRET_KEY=...
SANOID_MANAGER_DB=/var/lib/sanoid-manager/sanoid-manager.db
SANOID_MANAGER_PORT=8420
SANOID_MANAGER_TOKEN_EXPIRE=480
SANOID_MANAGER_CORS_ORIGINS=
SANOID_MANAGER_LOG_LEVEL=INFO
```

---

## 🔒 Sicurezza

### Best Practices

1. **Accesso Rete**: Limita porta 8420 solo alla rete di gestione
2. **SSH**: Usa chiavi SSH dedicate
3. **Password**: Password complesse per admin
4. **HTTPS**: Configura reverse proxy con SSL
5. **Firewall**: Restringi accesso ai nodi gestiti

### Firewall

```bash
# UFW
ufw allow from 192.168.100.0/24 to any port 8420

# iptables
iptables -A INPUT -p tcp --dport 8420 -s 192.168.100.0/24 -j ACCEPT
iptables -A INPUT -p tcp --dport 8420 -j DROP
```

### Reverse Proxy (Nginx)

```nginx
server {
    listen 443 ssl;
    server_name sanoid.example.com;
    
    ssl_certificate /etc/ssl/certs/sanoid.pem;
    ssl_certificate_key /etc/ssl/private/sanoid.key;
    
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

## 📞 Supporto

**Domarc S.r.l.**
- 🌐 Website: [www.domarc.it](https://www.domarc.it)
- 📧 Email: [info@domarc.it](mailto:info@domarc.it)

---

## 📋 Changelog

Vedi [CHANGELOG.md](CHANGELOG.md) per la lista completa delle modifiche.

**Versione Corrente**: 3.4.5

**Ultime Modifiche**:
- Aggiunto supporto migrazione VM tra nodi
- Integrazione snapshot management nella pagina VM
- Supporto multi-disco e multi-network per migrazione
- Reset database per riconfigurazione sistema
- Ristrutturazione pagina Replica con modal wizard

---

**© 2025 Domarc S.r.l. - Tutti i diritti riservati**

