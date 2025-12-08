# 🗃️ DAPX-backandrepl

**Sistema centralizzato di backup e replica per infrastrutture Proxmox VE**

![Version](https://img.shields.io/badge/version-3.5.0-blue)
![Python](https://img.shields.io/badge/python-3.9+-green)
![License](https://img.shields.io/badge/license-Proprietary-red)

> **© 2025 Domarc S.r.l.** - Tutti i diritti riservati  
> [www.domarc.it](https://www.domarc.it)

---

## ✨ Caratteristiche

- **🔐 Autenticazione Integrata** - Login con credenziali Proxmox VE (PAM, PVE, LDAP, AD)
- **🖥️ Dashboard Centralizzata** - Monitora tutti i tuoi nodi Proxmox da un'unica interfaccia
- **📸 Gestione Snapshot** - Configura Sanoid per snapshot automatici con policy personalizzabili
- **🔄 Replica Multi-Storage** - Supporta ZFS (Syncoid), BTRFS (btrfs send/receive) e PBS (Proxmox Backup Server)
- **🎮 Registrazione VM** - Registra automaticamente le VM replicate sul nodo di destinazione
- **👥 Gestione Utenti** - Ruoli (Admin, Operator, Viewer) con permessi granulari
- **📊 Audit Log** - Tracciamento completo di tutte le operazioni
- **🔔 Notifiche** - Email, Webhook, Telegram per alert e report
- **🎨 Interfaccia Moderna** - Web UI responsive e intuitiva
- **🔄 Recovery Jobs (PBS)** - Backup e restore automatici tramite Proxmox Backup Server

---

## 📋 Requisiti

### Nodo Manager (dove installi DAPX-backandrepl)
- Proxmox VE 7.x / 8.x (o Debian 11/12, Ubuntu 20.04+)
- ZFS o BTRFS installato e configurato (per funzionalità snapshot/replica)
- Python 3.9+ (testato fino a Python 3.13)
- Accesso root o sudo

### Nodi Gestiti
- **Proxmox VE**: Con ZFS o BTRFS per replica diretta
- **Proxmox Backup Server**: Per recovery jobs (backup/restore)
- SSH accessibile (porta 22 di default)
- Chiave SSH del nodo manager autorizzata

---

## 🚀 Installazione Rapida

### Opzione 1: Installazione Containerizzata (Consigliata per sviluppo/test)

```bash
# Clona il repository
git clone https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl

# Esegui installazione Docker
chmod +x docker-install.sh
./docker-install.sh
```

Il container sarà disponibile su `http://localhost:8420`

> 📘 **Vedi [DOCKER.md](DOCKER.md) per documentazione completa sull'installazione containerizzata**

### Opzione 2: Installazione in Container LXC Proxmox (Consigliata per produzione)

Installa direttamente in un container LXC su Proxmox con un singolo comando:

```bash
# Esegui sul nodo Proxmox (non nel container)
bash <(curl -s https://raw.githubusercontent.com/grandir66/dapx-backandrepl/main/lxc/auto-deploy.sh)
```

Lo script interattivo ti guiderà nella:
- Selezione dell'ID container
- Scelta dello storage
- Selezione del bridge di rete
- Scelta del template Debian/Ubuntu

Al termine, accedi a `http://IP-CONTAINER:8420`

> 📘 **Vedi [lxc/README.md](lxc/README.md) per documentazione completa sull'installazione LXC**

#### Comandi Manuali LXC

Se preferisci un controllo più granulare:

```bash
# 1. Scarica gli script
cd /root
git clone https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl/lxc

# 2. Crea il container (personalizza i parametri)
./create-lxc-container.sh 200 dapx-backandrepl local-lvm 8G 1024 2 vmbr0 dhcp

# 3. Installa l'applicazione nel container
pct exec 200 -- bash < install-in-lxc.sh

# 4. Gestisci il container
./manage-lxc.sh 200 status
./manage-lxc.sh 200 logs
./manage-lxc.sh 200 update
```

### Opzione 3: Installazione Standard (Consigliata per installazione diretta)

```bash
# Clona il repository
cd /opt
git clone https://github.com/grandir66/dapx-backandrepl.git
cd dapx-backandrepl

# Rendi eseguibile e avvia l'installer
chmod +x install.sh
./install.sh
```

Oppure scarica l'ultima release:

```bash
cd /tmp
wget https://github.com/grandir66/dapx-backandrepl/archive/refs/tags/v3.4.5.tar.gz
tar xzf v3.4.5.tar.gz
cd dapx-backandrepl-3.4.5
chmod +x install.sh
./install.sh
```

### 2. Setup Iniziale

1. Apri il browser su: `http://<IP-NODO-MANAGER>:8420`
2. Completa il wizard di setup:
   - Crea l'account amministratore
   - Configura il metodo di autenticazione (Proxmox o locale)
   - Imposta le preferenze di base

### 3. Configura Accesso SSH ai Nodi

L'installer mostrerà la chiave pubblica SSH. Copiala su ogni nodo:

```bash
# Per ogni nodo Proxmox da gestire:
ssh-copy-id -i /root/.ssh/id_rsa.pub root@192.168.1.10
ssh-copy-id -i /root/.ssh/id_rsa.pub root@192.168.1.11
# ... etc
```

### 4. Verifica Installazione

```bash
# Esegui lo script di test
./test-installation.sh

# Per test completi (include pytest)
./test-installation.sh --full
```

---

## 🔐 Autenticazione

### Metodi Supportati

| Metodo | Descrizione |
|--------|-------------|
| **Proxmox** | Login con credenziali Proxmox VE |
| **Locale** | Utenti gestiti direttamente in Sanoid Manager |

### Autenticazione Proxmox

Sanoid Manager può autenticare gli utenti direttamente contro Proxmox VE:

1. **Realm PAM**: Utenti locali del sistema Linux
2. **Realm PVE**: Utenti nativi Proxmox
3. **Realm LDAP/AD**: Utenti da directory LDAP o Active Directory

Configurazione:
1. Vai su **Impostazioni** → **Autenticazione**
2. Seleziona "Proxmox" come metodo primario
3. Scegli il nodo Proxmox di riferimento per l'autenticazione
4. Configura il realm predefinito

### Ruoli Utente

| Ruolo | Visualizza | Crea/Modifica | Admin |
|-------|------------|---------------|-------|
| **Viewer** | ✅ | ❌ | ❌ |
| **Operator** | ✅ | ✅ | ❌ |
| **Admin** | ✅ | ✅ | ✅ |

### Restrizione Nodi

Gli utenti possono essere limitati a gestire solo specifici nodi:
- Vai su **Impostazioni** → **Utenti**
- Modifica l'utente
- Seleziona i nodi consentiti

---

## 📖 Guida all'Uso

> 💡 **Guida Rapida**: Per iniziare velocemente, consulta [GUIDA_RAPIDA.md](GUIDA_RAPIDA.md)  
> 📘 **Guida Completa**: Per documentazione dettagliata, consulta [GUIDA_UTENTE.md](GUIDA_UTENTE.md)  
> 💡 **Miglioramenti**: Per suggerimenti e roadmap, consulta [MIGLIORAMENTI_PROPOSTI.md](MIGLIORAMENTI_PROPOSTI.md)

### Aggiungere un Nodo

1. Vai su **Nodi** → **Aggiungi Nodo**
2. Inserisci:
   - **Nome**: identificativo (es. `pve-node-01`)
   - **Hostname/IP**: indirizzo del nodo
   - **Porta SSH**: default 22
   - **Utente SSH**: default root
   - **Chiave SSH**: `/root/.ssh/id_rsa`
3. Clicca **Aggiungi** e poi **Test** per verificare la connessione

### Configurare Snapshot (Sanoid)

1. Vai su **Snapshot**
2. Seleziona un nodo dal dropdown
3. Per ogni dataset che vuoi proteggere:
   - Abilita la checkbox **Sanoid**
   - Scegli un **Template** di retention:
     
     | Template | Hourly | Daily | Weekly | Monthly | Yearly |
     |----------|--------|-------|--------|---------|--------|
     | production | 48 | 90 | 12 | 24 | 5 |
     | default | 24 | 30 | 4 | 12 | 0 |
     | minimal | 12 | 7 | 0 | 0 | 0 |
     | backup | 0 | 30 | 8 | 12 | 2 |
     | vm | 24 | 14 | 4 | 6 | 0 |

4. Clicca **Applica Config** per salvare sul nodo

### Creare un Job di Replica

#### Replica ZFS (Syncoid) o BTRFS

1. Vai su **Replica** → **Nuovo Job**
2. Configura:
   - **Nome**: identificativo del job
   - **Nodo Sorgente**: da dove replicare
   - **Dataset Sorgente**: es. `rpool/data/vm-100-disk-0`
   - **Nodo Destinazione**: dove replicare
   - **Dataset Destinazione**: es. `rpool/replica/vm-100-disk-0`
   - **Metodo**: `syncoid` (ZFS) o `btrfs_send` (BTRFS)
   - **Schedule** (opzionale): formato cron, es:
     - `0 */4 * * *` = ogni 4 ore
     - `0 2 * * *` = ogni notte alle 2:00
     - `*/30 * * * *` = ogni 30 minuti
3. Opzioni avanzate:
   - **Ricorsivo**: replica anche sotto-dataset
   - **Compressione**: lz4 (default), gzip, zstd
   - **Registra VM**: registra automaticamente la VM sul nodo destinazione

#### Recovery Job (PBS - Proxmox Backup Server)

1. Vai su **Recovery (PBS)** → **Nuovo Job**
2. Configura:
   - **Nome**: identificativo del job
   - **Nodo Sorgente**: nodo PVE con la VM
   - **VMID**: ID della VM da replicare
   - **PBS Node**: nodo Proxmox Backup Server
   - **Nodo Destinazione**: dove ripristinare la VM
   - **Schedule**: frequenza backup/restore
3. Il sistema eseguirà automaticamente:
   - Backup VM su PBS
   - Restore su nodo destinazione
   - Registrazione VM

### Registrazione VM Post-Replica

Per avere una VM funzionante sul nodo di destinazione dopo la replica:

1. Nella creazione del job, abilita **Registra VM dopo replica**
2. Inserisci il **VMID** e il **Tipo** (qemu/lxc)
3. Dopo la sincronizzazione, Sanoid Manager:
   - Copia il file di configurazione dalla sorgente
   - Lo adatta per il nodo destinazione
   - Registra la VM in Proxmox

> ⚠️ La VM registrata sarà in stato **stopped**. Avviala manualmente solo in caso di failover.

---

## ⚙️ Configurazione

### Impostazioni Generali

Vai su **Impostazioni** → **Generale**:
- **Lingua**: Italiano/Inglese
- **Tema**: Chiaro/Scuro
- **Timezone**: Fuso orario per log e scheduling

### Configurazione Notifiche

#### Email (SMTP)
```
Server SMTP: smtp.example.com
Porta: 587
TLS: Abilitato
Username: sanoid@example.com
Password: ********
Destinatario: admin@example.com
```

#### Webhook
```
URL: https://hooks.slack.com/services/xxx
Metodo: POST
Header: Content-Type: application/json
```

#### Telegram
```
Bot Token: 123456789:ABC...
Chat ID: -1001234567890
```

### Variabili d'Ambiente

File: `/etc/sanoid-manager/sanoid-manager.env`

```bash
# Chiave segreta JWT (generata automaticamente)
SANOID_MANAGER_SECRET_KEY=your-secret-key

# Database
SANOID_MANAGER_DB=/var/lib/sanoid-manager/sanoid-manager.db

# Porta web
SANOID_MANAGER_PORT=8420

# Scadenza token (minuti)
SANOID_MANAGER_TOKEN_EXPIRE=480

# Origini CORS (vuoto = solo same-origin)
SANOID_MANAGER_CORS_ORIGINS=

# Livello log
SANOID_MANAGER_LOG_LEVEL=INFO
```

---

## 🔧 Amministrazione

### Comandi Servizio

```bash
# Stato
systemctl status sanoid-manager

# Avvia/Ferma/Riavvia
systemctl start sanoid-manager
systemctl stop sanoid-manager
systemctl restart sanoid-manager

# Log in tempo reale
journalctl -u sanoid-manager -f

# Log applicazione
tail -f /var/log/sanoid-manager/sanoid-manager.log
```

### Backup Database

```bash
# Backup manuale
cp /var/lib/sanoid-manager/sanoid-manager.db ~/sanoid-manager-backup-$(date +%Y%m%d).db

# Restore
systemctl stop sanoid-manager
cp ~/sanoid-manager-backup.db /var/lib/sanoid-manager/sanoid-manager.db
systemctl start sanoid-manager
```

### Aggiornamento

```bash
# Scarica nuova versione
cd /tmp
wget https://github.com/yourusername/sanoid-manager/releases/download/vX.Y.Z/sanoid-manager-X.Y.Z.tar.gz
tar xzf sanoid-manager-X.Y.Z.tar.gz
cd sanoid-manager-X.Y.Z

# L'installer rileva l'installazione esistente e fa upgrade
./install.sh
```

### Disinstallazione

```bash
./install.sh --uninstall
```

---

## 📁 Struttura Directory

```
/opt/sanoid-manager/          # Applicazione
├── main.py                   # Entry point FastAPI
├── database.py               # Models SQLAlchemy
├── routers/                  # API endpoints
│   ├── auth.py               # Autenticazione
│   ├── nodes.py
│   ├── snapshots.py
│   ├── sync_jobs.py
│   ├── vms.py
│   ├── logs.py
│   └── settings.py
├── services/                 # Business logic
│   ├── auth_service.py       # JWT e gestione utenti
│   ├── proxmox_auth_service.py # Auth Proxmox
│   ├── ssh_service.py
│   ├── sanoid_service.py
│   ├── syncoid_service.py
│   ├── proxmox_service.py
│   └── scheduler.py
├── tests/                    # Test suite
├── frontend/
│   └── dist/
│       └── index.html        # Single-page application
└── venv/                     # Python virtual environment

/etc/sanoid-manager/          # Configurazione
└── sanoid-manager.env        # Variabili d'ambiente

/var/lib/sanoid-manager/      # Dati persistenti
└── sanoid-manager.db         # Database SQLite

/var/log/sanoid-manager/      # Log
└── sanoid-manager.log
```

---

## 🔒 Sicurezza

### Best Practices

1. **Accesso Rete**: Limita l'accesso alla porta 8420 solo alla rete di gestione
2. **SSH**: Usa chiavi SSH dedicate, non condividere con altri servizi
3. **Password**: Usa password complesse per l'admin locale
4. **HTTPS**: Configura un reverse proxy con SSL

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

## 🐛 Troubleshooting

### Il servizio non parte

```bash
# Controlla i log
journalctl -u sanoid-manager -n 50

# Verifica permessi
ls -la /opt/sanoid-manager/
ls -la /var/lib/sanoid-manager/

# Testa manualmente
cd /opt/sanoid-manager
source venv/bin/activate
python -c "from main import app; print('OK')"
```

### Errore autenticazione

```bash
# Verifica configurazione
cat /etc/sanoid-manager/sanoid-manager.env

# Reset password admin (da implementare)
cd /opt/sanoid-manager
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
# Testa connessione manuale
ssh -i /root/.ssh/id_rsa -p 22 root@hostname "echo OK"

# Verifica chiave autorizzata sul nodo remoto
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

---

## 📝 API Reference

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
| GET | `/nodes/{id}/datasets` | Lista dataset ZFS |

### Snapshot

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/snapshots/node/{id}` | Lista snapshot |
| POST | `/snapshots/node/{id}/apply-config` | Applica config Sanoid |
| DELETE | `/snapshots/{name}` | Elimina snapshot |

### Replica

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/sync-jobs/` | Lista job |
| POST | `/sync-jobs/` | Crea job |
| GET | `/sync-jobs/{id}` | Dettaglio job |
| PUT | `/sync-jobs/{id}` | Modifica job |
| DELETE | `/sync-jobs/{id}` | Elimina job |
| POST | `/sync-jobs/{id}/run` | Esegui job |

### Recovery Jobs (PBS)

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

### Impostazioni

| Metodo | Endpoint | Descrizione |
|--------|----------|-------------|
| GET | `/settings/` | Leggi impostazioni |
| PUT | `/settings/` | Aggiorna impostazioni |
| GET | `/settings/auth` | Config autenticazione |
| PUT | `/settings/auth` | Aggiorna auth config |

---

## 🧪 Testing

### Esegui Test

```bash
cd /opt/sanoid-manager
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

---

## 📞 Contatti

**Domarc S.r.l.**
- 🌐 Website: [www.domarc.it](https://www.domarc.it)
- 📧 Email: [info@domarc.it](mailto:info@domarc.it)
- 📍 Italia
- [Vue.js](https://vuejs.org/)

---

## 📋 Changelog

Vedi [CHANGELOG.md](CHANGELOG.md) per la lista completa delle modifiche.

---

## 📚 Documentazione

- **[GUIDA_RAPIDA.md](GUIDA_RAPIDA.md)** - Guida rapida per iniziare in 5 minuti
- **[GUIDA_UTENTE.md](GUIDA_UTENTE.md)** - Guida utente completa e dettagliata
- **[MIGLIORAMENTI_PROPOSTI.md](MIGLIORAMENTI_PROPOSTI.md)** - Suggerimenti e roadmap per miglioramenti futuri
- **[CHANGELOG.md](CHANGELOG.md)** - Storico delle versioni e modifiche
