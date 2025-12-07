# 🚀 Guida Rapida - DAPX-backandrepl

**Guida pratica per iniziare rapidamente con DAPX-backandrepl**

---

## ⚡ Quick Start (5 minuti)

### 1. Installazione

```bash
# Clona o scarica il progetto
cd /tmp
git clone <repository-url> sanoid-manager
cd sanoid-manager

# Esegui l'installer
chmod +x install.sh
sudo ./install.sh
```

### 2. Primo Accesso

1. Apri il browser: `http://<IP-SERVER>:8420`
2. Crea l'account amministratore nel wizard di setup
3. Configura l'autenticazione (Proxmox o locale)

### 3. Aggiungi Primo Nodo

1. Vai su **Nodi** → **Aggiungi Nodo**
2. Inserisci:
   - Nome: `pve-01`
   - Hostname/IP: `192.168.1.10`
   - Porta SSH: `22`
   - Utente: `root`
3. Clicca **Aggiungi** e poi **Test** per verificare

### 4. Configura Snapshot

1. Vai su **Snapshot**
2. Seleziona il nodo
3. Abilita **Sanoid** per i dataset che vuoi proteggere
4. Scegli un template (es. `production` per VM critiche)
5. Clicca **Applica Config**

### 5. Crea Job di Replica

1. Vai su **Replica** → **Nuovo Job**
2. Configura:
   - Nome: `replica-vm-100`
   - Nodo Sorgente: `pve-01`
   - Dataset Sorgente: `rpool/data/vm-100-disk-0`
   - Nodo Destinazione: `pve-02`
   - Dataset Destinazione: `rpool/replica/vm-100-disk-0`
   - Schedule: `0 */4 * * *` (ogni 4 ore)
3. Clicca **Crea**

---

## 📋 Scenari Comuni

### Scenario 1: Backup VM Critica

**Obiettivo**: Backup automatico ogni 6 ore di una VM importante

1. **Snapshot**:
   - Nodo: `pve-prod`
   - Dataset: `rpool/data/vm-100-disk-0`
   - Template: `production` (48 hourly, 90 daily, 12 weekly, 24 monthly, 5 yearly)

2. **Replica**:
   - Job: `backup-vm-100`
   - Sorgente: `pve-prod` → `rpool/data/vm-100-disk-0`
   - Destinazione: `pve-backup` → `rpool/backup/vm-100-disk-0`
   - Schedule: `0 */6 * * *` (ogni 6 ore)
   - Compressione: `lz4`
   - Registra VM: ✅ (per disaster recovery)

### Scenario 2: Replica Multi-Nodo

**Obiettivo**: Replicare una VM su 3 nodi diversi

Crea 3 job di replica:
- `replica-vm-100-node1`: `pve-01` → `pve-02`
- `replica-vm-100-node2`: `pve-01` → `pve-03`
- `replica-vm-100-node3`: `pve-01` → `pve-04`

Ogni job con schedule diverso per distribuire il carico:
- Job 1: `0 2 * * *` (2:00 AM)
- Job 2: `0 6 * * *` (6:00 AM)
- Job 3: `0 10 * * *` (10:00 AM)

### Scenario 3: Recovery da PBS

**Obiettivo**: Backup automatico verso PBS e restore su nodo standby

1. **Aggiungi Nodo PBS**:
   - Tipo: `Proxmox Backup Server`
   - Hostname: `pbs-01.example.com`
   - Datastore: `backup-store`

2. **Crea Recovery Job**:
   - Nome: `recovery-vm-100`
   - Nodo Sorgente: `pve-prod`
   - VMID: `100`
   - PBS Node: `pbs-01`
   - Nodo Destinazione: `pve-standby`
   - Schedule: `0 3 * * *` (ogni notte alle 3:00)

Il sistema eseguirà automaticamente:
1. Backup VM su PBS
2. Restore su nodo destinazione
3. Registrazione VM

---

## 🎯 Template Snapshot Predefiniti

| Template | Hourly | Daily | Weekly | Monthly | Yearly | Uso |
|----------|--------|-------|--------|---------|--------|-----|
| **production** | 48 | 90 | 12 | 24 | 5 | VM critiche, database |
| **default** | 24 | 30 | 4 | 12 | 0 | Uso generale |
| **minimal** | 12 | 7 | 0 | 0 | 0 | Test, sviluppo |
| **backup** | 0 | 30 | 8 | 12 | 2 | Storage backup |
| **vm** | 24 | 14 | 4 | 6 | 0 | VM standard |

---

## ⏰ Esempi Schedule (Cron)

| Schedule | Significato | Uso |
|----------|-------------|-----|
| `*/30 * * * *` | Ogni 30 minuti | Replica frequente |
| `0 * * * *` | Ogni ora | Replica oraria |
| `0 */4 * * *` | Ogni 4 ore | Replica standard |
| `0 2 * * *` | Ogni notte alle 2:00 | Backup notturno |
| `0 2 * * 0` | Ogni domenica alle 2:00 | Backup settimanale |
| `0 2 1 * *` | Primo del mese alle 2:00 | Backup mensile |

---

## 🔧 Comandi Utili

### Verifica Stato

```bash
# Stato servizio
systemctl status sanoid-manager

# Log in tempo reale
journalctl -u sanoid-manager -f

# Test API
curl http://localhost:8420/api/health
```

### Backup Database

```bash
# Backup manuale
cp /var/lib/sanoid-manager/sanoid-manager.db \
   ~/sanoid-manager-backup-$(date +%Y%m%d).db
```

### Test Connessione Nodo

```bash
# Test SSH manuale
ssh -i /root/.ssh/id_rsa root@<IP-NODO> "hostname"

# Test ZFS
ssh -i /root/.ssh/id_rsa root@<IP-NODO> "zfs list"
```

---

## ⚠️ Troubleshooting Rapido

### Il servizio non parte

```bash
# Controlla log
journalctl -u sanoid-manager -n 50

# Verifica permessi
ls -la /opt/sanoid-manager/
ls -la /var/lib/sanoid-manager/
```

### Connessione SSH fallisce

```bash
# Verifica chiave
cat /root/.ssh/id_rsa.pub

# Copia chiave sul nodo remoto
ssh-copy-id -i /root/.ssh/id_rsa.pub root@<IP-NODO>
```

### Sanoid non crea snapshot

```bash
# Verifica config sul nodo
ssh root@<NODO> "cat /etc/sanoid/sanoid.conf"

# Esegui manualmente
ssh root@<NODO> "sanoid --cron --verbose"
```

### Syncoid fallisce

```bash
# Verifica spazio su destinazione
ssh root@<DEST> "zfs list -o name,avail"

# Test manuale
ssh root@<SOURCE> "syncoid --compress=lz4 <source> root@<dest>:<dest>"
```

---

## 📚 Documentazione Completa

- **Guida Utente Completa**: Vedi [GUIDA_UTENTE.md](GUIDA_UTENTE.md)
- **API Reference**: `http://<SERVER>:8420/docs`
- **Changelog**: Vedi [CHANGELOG.md](CHANGELOG.md)

---

## 🆘 Supporto

1. Controlla la sezione Troubleshooting in [GUIDA_UTENTE.md](GUIDA_UTENTE.md)
2. Verifica i log: `journalctl -u sanoid-manager -f`
3. Consulta la documentazione Sanoid/Syncoid ufficiale

---

*Ultimo aggiornamento: v3.3.0*


