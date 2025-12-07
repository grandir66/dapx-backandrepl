# Changelog

Tutte le modifiche significative a DAPX-backandrepl sono documentate in questo file.

Il formato è basato su [Keep a Changelog](https://keepachangelog.com/it-IT/1.0.0/),
e questo progetto aderisce al [Semantic Versioning](https://semver.org/lang/it/).

## [3.3.0] - 2024-12-06

### Aggiunto

#### 🗄️ Supporto Proxmox Backup Server (PBS)
- **Recovery Jobs (PBS)**: Nuovo sistema di replica basato su backup/restore PBS
- **Nodi PBS**: Supporto per registrare e gestire nodi Proxmox Backup Server
- **Backup automatici**: Esecuzione backup VM verso PBS da nodo sorgente
- **Restore automatico**: Ripristino VM da backup PBS su nodo destinazione
- **Replica filesystem non supportati**: Permette replicare VM con LVM, local, etc.

#### Nuovi Modelli Database
- `NodeType` enum: `pve` (Proxmox VE) e `pbs` (Proxmox Backup Server)
- `RecoveryJobStatus` enum: stati per tracking recovery jobs
- `RecoveryJob` model: configurazione job backup → restore → registrazione
- Campi PBS nei nodi: `node_type`, `pbs_datastore`, `pbs_fingerprint`, `pbs_password`, `pbs_available`, `pbs_version`

#### Servizio PBSService (`services/pbs_service.py`)
- `check_pbs_available()` - Verifica client PBS su nodo PVE
- `check_pbs_server()` - Verifica se nodo è un PBS server
- `list_datastores()` - Lista datastore su PBS
- `list_backups()` - Lista backup disponibili
- `get_latest_backup()` - Ottiene ultimo backup per VM
- `run_backup()` - Esegue backup VM verso PBS
- `run_restore()` - Ripristina VM da backup PBS
- `run_full_recovery()` - Workflow completo: backup → restore

#### Router Recovery Jobs (`routers/recovery_jobs.py`)
- CRUD endpoints per recovery jobs
- `/run` - Esecuzione manuale recovery completo
- `/backup-only` - Solo fase backup
- `/restore-only` - Solo fase restore
- `/pbs-nodes/` - Lista e test nodi PBS

#### Frontend
- Nuova pagina "Recovery (PBS)" con gestione recovery jobs
- Modal creazione recovery job con wizard
- Visualizzazione stato nodi PBS
- Supporto creazione nodi PBS nel modal "Aggiungi Nodo"
- Badge distintivi per nodi PVE/PBS
- Statistiche recovery jobs nel dashboard

### Modificato
- Router nodes: Aggiunto supporto test/verifica nodi PBS
- main.py: Nuova versione 3.3.0, router recovery_jobs
- Frontend: Tabella nodi aggiornata con colonna "Tipo"

---

## [3.2.0] - 2024-12-06

### Aggiunto

#### 🆕 Supporto BTRFS
- **Replica VM con BTRFS**: Nuovo metodo di sincronizzazione basato su `btrfs send/receive`
- **Sync incrementale BTRFS**: Utilizza snapshot parent per trasferimenti incrementali efficienti
- **Gestione snapshot BTRFS**: Creazione automatica e pulizia snapshot secondo policy configurabili
- **Nuovi campi database**:
  - `storage_type` nei nodi (zfs, btrfs)
  - `sync_method` nei job (syncoid, btrfs_send)
  - Campi BTRFS specifici: `btrfs_mount`, `btrfs_snapshot_dir`, `btrfs_max_snapshots`, `btrfs_full_sync`
- **Verifica BTRFS**: Il test connessione nodo ora verifica anche la disponibilità BTRFS

#### Servizio BTRFSService (`services/btrfs_service.py`)
- `check_btrfs_available()` - Verifica disponibilità BTRFS sul nodo
- `check_btrfs_mount()` - Verifica mount point BTRFS
- `create_snapshot()` - Crea snapshot BTRFS readonly
- `delete_snapshot()` - Elimina snapshot/subvolume
- `convert_to_subvolume()` - Converte file in subvolume BTRFS
- `run_sync()` - Esegue sincronizzazione con btrfs send/receive
- `build_btrfs_sync_command()` - Costruisce comando sync (analogo a syncoid)

### Modificato
- **Schema nodi**: Aggiunti campi `storage_type`, `btrfs_mount`, `btrfs_snapshot_dir`, `btrfs_available`, `btrfs_version`
- **Schema job**: Aggiunti campi `sync_method`, `btrfs_snapshot_dir`, `btrfs_dest_snapshot_dir`, `btrfs_max_snapshots`, `btrfs_full_sync`, `last_sync_type`
- **Router sync_jobs**: `execute_sync_job_task()` ora supporta entrambi i metodi (syncoid e btrfs_send)
- **Router nodes**: `test_node_connection()` verifica anche BTRFS se configurato
- **Configurazione default**: Aggiunte impostazioni BTRFS (`btrfs_default_mount`, `btrfs_default_snapshot_dir`, `btrfs_max_snapshots`, `btrfs_sync_timeout`)

---

## [2.0.0] - 2024-12-02

### Breaking Changes
- Rimossa dipendenza da `passlib` - ora usa `bcrypt` direttamente
- Richiede Python 3.9+ (testato fino a Python 3.13)

### Corretto
- **Fix critico**: Errore "password cannot be longer than 72 bytes" su Python 3.13
- Compatibilità bcrypt con Python 3.13 (AttributeError su `bcrypt.__about__`)
- Gestione corretta del troncamento password a 72 byte (limite bcrypt)
- Determinazione directory script nell'installer più robusta
- Percorso frontend dinamico con fallback multipli

### Migliorato
- Messaggi di errore più dettagliati durante il setup
- Logging migliorato per debug
- Gestione errori più robusta in `auth_service.py`

---

## [1.1.0] - 2024-12-02

### Aggiunto

#### 🔐 Sistema di Autenticazione
- **Autenticazione JWT** con token di accesso e refresh
- **Integrazione Proxmox** - Login usando credenziali Proxmox VE (PAM, PVE, LDAP, AD)
- **Autenticazione locale** come fallback quando Proxmox non è disponibile
- **Sistema di ruoli** con tre livelli: Admin, Operator, Viewer
- **Restrizione accesso nodi** - Gli utenti possono essere limitati a specifici nodi
- **Audit log** - Tracciamento completo di tutte le azioni utente
- **Gestione sessioni** con scadenza configurabile
- **API Key** per accesso programmatico

#### ⚙️ Configurazione Avanzata
- **Wizard setup iniziale** per la configurazione del primo amministratore
- **Pagina gestione utenti** (solo admin)
- **Configurazione autenticazione** (metodo, timeout, realm Proxmox)
- **Configurazione notifiche**:
  - SMTP per email
  - Webhook per integrazioni
  - Telegram per messaggi istantanei
- **Tab organizzate** nelle impostazioni (Generale, Autenticazione, Notifiche)

#### 🧪 Test Suite
- **Framework pytest** con configurazione completa
- **Fixtures** per database di test, client API, utenti e token
- **Test autenticazione**: login, logout, token refresh, validazione
- **Test API protette**: nodi, sync jobs, impostazioni
- **Test ruoli**: verifica permessi per admin/operator/viewer
- **Test audit log**: verifica tracciamento azioni

#### 🎨 Frontend Aggiornato
- **Pagina di login** con supporto selezione realm Proxmox
- **Indicatore sessione** nella sidebar con info utente e ruolo
- **Menu navigazione** riorganizzato per sezioni
- **Gestione token automatica** con interceptor Axios
- **Logout e cambio password** integrati

#### 📦 Installer Migliorato
- **Banner grafico** durante l'installazione
- **Progress bar** per le operazioni lunghe
- **Generazione automatica secret key** per JWT
- **Configurazione firewall** automatica (UFW, info iptables)
- **Script test-installation.sh** per verifica post-installazione
- **Supporto upgrade** da versioni precedenti con backup database
- **Comando --uninstall** per rimozione pulita
- **Comando --status** per verifica stato servizio

### Modificato

#### Backend
- **main.py**: Aggiunta protezione autenticazione a tutti i router
- **database.py**: Nuovi modelli User, Session, Audit
- **requirements.txt**: Aggiunte dipendenze jwt, bcrypt, aiohttp
- **Tutti i router**: Aggiunta dipendenza autenticazione

#### Sicurezza
- **CORS**: Configurazione più restrittiva in produzione
- **Password hashing**: Utilizzo bcrypt con salt
- **Token JWT**: Scadenza configurabile, algoritmo HS256

---

## [1.0.0] - 2024-11-15

### Aggiunto
- Gestione centralizzata nodi Proxmox via SSH
- Interfaccia web Vue.js single-page
- Configurazione policy Sanoid (snapshot)
- Scheduling job Syncoid (replica)
- Registrazione automatica VM post-replica
- Log dettagliati operazioni
- API REST documentata con Swagger/OpenAPI

### Caratteristiche Iniziali
- Backend FastAPI con SQLite
- Frontend Vue.js 3 con Tailwind CSS
- Connessione SSH con chiavi
- Cron-like scheduling
- Multi-nodo support
