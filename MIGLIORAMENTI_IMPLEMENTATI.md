# ✅ Miglioramenti Implementati

**Data**: 2024-12-06  
**Versione**: 3.3.0+

---

## 📋 Riepilogo Modifiche

Sono state implementate le seguenti migliorie richieste:

### 1. ✅ Validazione Input Rigorosa

**File modificati**:
- `backend/routers/recovery_jobs.py`

**Implementazione**:
- Validazione Pydantic con `Field` e `field_validator`
- Controllo formato e range per tutti i campi
- Validazione formato cron per schedule
- Validazione caratteri permessi per nomi
- Verifica che nodi sorgente e destinazione siano diversi

**Esempi validazione**:
```python
- name: solo caratteri alfanumerici, spazi, trattini, underscore
- vm_id: range 1-999999
- vm_type: solo "qemu" o "lxc"
- backup_mode: solo "snapshot", "stop", "suspend"
- backup_compress: solo "none", "lzo", "gzip", "zstd"
- schedule: formato cron valido (5 campi)
- max_retries: range 0-10
- retry_delay_minutes: range 1-1440
```

**Benefici**:
- Prevenzione input malformati
- Messaggi di errore chiari e specifici
- Validazione lato server prima dell'esecuzione

---

### 2. ✅ Logging Dettagliato con Fasi

**File modificati**:
- `backend/routers/recovery_jobs.py` (funzione `execute_recovery_job_task`)
- `backend/services/pbs_service.py` (funzione `run_full_recovery`)

**Implementazione**:
- Log separati per ogni fase del recovery job:
  1. **FASE 0: PREPARAZIONE** - Verifica nodi, configurazione
  2. **FASE 1: BACKUP** - Backup VM verso PBS
  3. **FASE 2: RESTORE** - Restore da PBS verso nodo destinazione
  4. **FASE 3: COMPLETAMENTO** - Finalizzazione e notifiche

- Log entry separati nel database:
  - `log_entry_main`: Log principale del recovery job completo
  - `log_entry_backup`: Log specifico fase backup
  - `log_entry_restore`: Log specifico fase restore

- Logging strutturato con prefisso `[Recovery Job {id}]` per tracciabilità

**Esempio output log**:
```
[Recovery Job 1] === FASE 0: PREPARAZIONE ===
[Recovery Job 1] VM: 100 (qemu)
[Recovery Job 1] Sorgente: pve-01 (192.168.1.10)
[Recovery Job 1] PBS: pbs-01 (192.168.1.20)
[Recovery Job 1] Destinazione: pve-02 (192.168.1.11)
[Recovery Job 1] === FASE 1: BACKUP ===
[Recovery Job 1] ✓ Backup completato in 120s - ID: vm/100/2024-12-06T10:30:00Z
[Recovery Job 1] === FASE 2: RESTORE ===
[Recovery Job 1] ✓ Restore completato in 180s - VMID: 100
[Recovery Job 1] === FASE 3: COMPLETAMENTO ===
[Recovery Job 1] ✓ Recovery completata in 300s (Backup: 120s, Restore: 180s)
```

**Benefici**:
- Tracciabilità completa di ogni fase
- Debug facilitato in caso di errori
- Metriche dettagliate per ogni fase
- Log separati per backup e restore nel database

---

### 3. ✅ Configurazione Notifiche per Job

**File modificati**:
- `backend/database.py` (modello `RecoveryJob`)
- `backend/routers/recovery_jobs.py` (schemi e logica)

**Implementazione**:
- Nuovo campo `notify_on_each_run` nel modello `RecoveryJob`
- Default: `False` (notifica solo nel report giornaliero)
- Se `True`: notifica ad ogni esecuzione (successo o fallimento)
- Se `False`: notifica solo nel report giornaliero (comportamento esistente)

**Logica notifiche**:
```python
if job.notify_on_each_run:
    # Notifica immediata ad ogni esecuzione
    await notification_service.send_job_notification(...)
else:
    # Notifica solo nel report giornaliero (gestito da scheduler)
    # Nessuna notifica immediata
```

**Configurazione**:
- Campo disponibile nella creazione/aggiornamento recovery job
- Validazione: campo booleano
- Persistito nel database

**Benefici**:
- Controllo granulare delle notifiche per job
- Riduzione spam per job frequenti
- Notifiche immediate per job critici
- Report giornaliero sempre disponibile

---

### 4. ✅ Verifica Sequenza Recovery Job PBS

**File modificati**:
- `backend/routers/recovery_jobs.py` (funzione `execute_recovery_job_task`)
- `backend/services/pbs_service.py` (funzione `run_full_recovery`)

**Sequenza verificata e implementata**:

1. **PREPARAZIONE**
   - Verifica esistenza job e nodi
   - Log dettagliato configurazione
   - Inizializzazione log entry

2. **FASE BACKUP**
   - Aggiorna stato: `BACKING_UP`
   - Crea log entry specifico backup
   - Esegue backup verso PBS
   - **Attesa completamento backup**
   - Verifica successo backup
   - Se fallito: termina, aggiorna log, notifica (se configurato)

3. **FASE RESTORE** (solo se backup riuscito)
   - Aggiorna stato: `RESTORING`
   - Crea log entry specifico restore
   - **Usa backup_id dal backup completato**
   - Esegue restore da PBS verso nodo destinazione
   - **Attesa completamento restore**
   - Verifica successo restore
   - Se fallito: termina, aggiorna log, notifica (se configurato)

4. **COMPLETAMENTO** (solo se restore riuscito)
   - Aggiorna stato: `COMPLETED`
   - Aggiorna statistiche job
   - Log finale con durate per fase
   - Notifica successo (se configurato)

**Verifiche implementate**:
- ✅ Backup viene eseguito PRIMA del restore
- ✅ Restore attende completamento backup
- ✅ Backup_id viene passato correttamente al restore
- ✅ Se backup fallisce, restore non viene eseguito
- ✅ Log separati per ogni fase
- ✅ Stato job aggiornato per ogni fase
- ✅ Gestione errori per ogni fase

**Benefici**:
- Sequenza garantita e verificata
- Nessun restore senza backup valido
- Tracciabilità completa del processo
- Gestione errori robusta

---

## 🔧 Dettagli Tecnici

### Modifiche Database

**Tabella `recovery_jobs`**:
```sql
ALTER TABLE recovery_jobs ADD COLUMN notify_on_each_run BOOLEAN DEFAULT 0;
```

**Nota**: La migrazione viene applicata automaticamente da SQLAlchemy al prossimo avvio.

### Modifiche API

**Endpoint `/api/recovery-jobs/` (POST)**:
- Campo `notify_on_each_run` opzionale (default: `false`)
- Validazione input rigorosa

**Endpoint `/api/recovery-jobs/{id}` (PUT)**:
- Campo `notify_on_each_run` aggiornabile

**Endpoint `/api/recovery-jobs/{id}/run` (POST)**:
- Esecuzione con logging dettagliato
- Notifiche condizionali

### Logging Strutturato

**Formato log**:
```
[Recovery Job {id}] === FASE {n}: {nome_fase} ===
[Recovery Job {id}] {messaggio}
[Recovery Job {id}] ✓ {successo} o ✗ {errore}
```

**Log nel database**:
- `job_logs.job_type = "recovery"`: Log principale
- `job_logs.job_type = "backup"`: Log fase backup
- `job_logs.job_type = "restore"`: Log fase restore

---

## 📊 Esempi d'Uso

### Creazione Recovery Job con Notifiche

```python
POST /api/recovery-jobs/
{
    "name": "replica-vm-100",
    "source_node_id": 1,
    "vm_id": 100,
    "pbs_node_id": 2,
    "dest_node_id": 3,
    "notify_on_each_run": true,  // Notifica ad ogni esecuzione
    "schedule": "0 2 * * *"      // Ogni notte alle 2:00
}
```

### Creazione Recovery Job senza Notifiche Immediate

```python
POST /api/recovery-jobs/
{
    "name": "replica-vm-200",
    "source_node_id": 1,
    "vm_id": 200,
    "pbs_node_id": 2,
    "dest_node_id": 3,
    "notify_on_each_run": false, // Solo report giornaliero
    "schedule": "*/30 * * * *"   // Ogni 30 minuti
}
```

### Visualizzazione Log Dettagliati

```python
GET /api/logs/?job_id=1&job_type=recovery
GET /api/logs/?job_id=1&job_type=backup
GET /api/logs/?job_id=1&job_type=restore
```

---

## ✅ Testing Consigliato

1. **Test Validazione Input**:
   - Nome con caratteri speciali → deve fallire
   - VMID fuori range → deve fallire
   - Schedule cron non valido → deve fallire
   - Nodi sorgente = destinazione → deve fallire

2. **Test Sequenza PBS**:
   - Backup fallisce → restore non deve essere eseguito
   - Backup riuscito → restore deve usare backup_id corretto
   - Verifica log separati per ogni fase

3. **Test Notifiche**:
   - `notify_on_each_run=true` → notifica ad ogni esecuzione
   - `notify_on_each_run=false` → notifica solo nel report giornaliero

4. **Test Logging**:
   - Verifica log nel database per ogni fase
   - Verifica output log strutturato
   - Verifica durate per ogni fase

---

## 🚀 Prossimi Passi Suggeriti

1. **Frontend**: Aggiungere campo `notify_on_each_run` nel form creazione/editing recovery job
2. **Dashboard**: Visualizzare durate per fase (backup vs restore)
3. **Report**: Includere dettagli fasi nel report giornaliero
4. **Alerting**: Configurare alert per job con fallimenti consecutivi

---

*Documento generato il: 2024-12-06*  
*Versione progetto: 3.3.0+*





