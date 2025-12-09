# 📋 File e Directory da Rimuovere/Ignorare

Questo documento elenca i file e le directory che dovrebbero essere rimossi o ignorati dal repository.

## 🗑️ File da Rimuovere

### 1. Directory `backend/venv/`
**Motivo**: Virtual environment Python non dovrebbe essere committato
**Azione**: Aggiunto a `.gitignore`, rimuovere dal repository se già presente

```bash
git rm -r --cached backend/venv/
```

### 2. Directory `backend-btrfs/`
**Motivo**: Directory vuota o non utilizzata (solo `__init__.py`)
**Azione**: Rimuovere se non più necessaria

```bash
rm -rf backend-btrfs/
```

### 3. Directory `data/`
**Motivo**: Contiene database di test/development
**Azione**: Aggiunto a `.gitignore`, rimuovere se contiene solo dati di test

```bash
# Verifica contenuto prima di rimuovere
ls -la data/
# Se contiene solo database di test:
rm -rf data/
```

### 4. File di log
**Motivo**: File di log non dovrebbero essere committati
**Azione**: Aggiunto a `.gitignore`

## 📝 File da Verificare

### Documentazione MD
Verificare se questi file sono ancora aggiornati o possono essere consolidati:
- `ANALISI_PANORAMICA_NODI.md`
- `GUIDA_RAPIDA.md`
- `GUIDA_UTENTE.md`
- `IMPLEMENTAZIONE_DASHBOARD.md`
- `MIGLIORAMENTI_IMPLEMENTATI.md`
- `MIGLIORAMENTI_PROPOSTI.md`
- `RIEPILOGO_VERIFICA.md`

**Raccomandazione**: Consolidare in `MANUAL.md` (nuovo manuale completo) e mantenere solo:
- `README.md` (overview)
- `MANUAL.md` (manuale completo)
- `CHANGELOG.md` (storico versioni)

### Script di installazione
Verificare se tutti gli script sono necessari:
- `install.sh` ✅ (necessario)
- `update.sh` ✅ (necessario)
- `deploy.sh` ⚠️ (verificare se ancora utilizzato)
- `fix_production.sh` ⚠️ (verificare se ancora utilizzato)
- `fix_service.sh` ⚠️ (verificare se ancora utilizzato)
- `check_service.sh` ⚠️ (verificare se ancora utilizzato)
- `test-installation.sh` ✅ (necessario)
- `start.sh` ⚠️ (verificare se ancora utilizzato)

## ✅ File da Mantenere

- `README.md` - Overview del progetto
- `MANUAL.md` - Manuale completo (nuovo)
- `CHANGELOG.md` - Storico versioni
- `LICENSE` - Licenza
- `version.txt` - Versione corrente
- `logo.png` - Logo progetto
- `backend/` - Codice sorgente
- `frontend/` - Frontend
- Script di installazione e aggiornamento

## 🔧 Comandi per Pulizia

```bash
# Rimuovi venv dal tracking git (mantiene locale)
git rm -r --cached backend/venv/

# Rimuovi directory inutili
rm -rf backend-btrfs/
rm -rf data/  # Solo se contiene solo dati di test

# Aggiungi .gitignore
git add .gitignore
git commit -m "Add .gitignore and remove unnecessary files"
```

## 📌 Note

- **NON rimuovere** file senza prima verificare che non siano utilizzati
- **Fare backup** prima di rimuovere directory con dati
- **Verificare** che gli script siano ancora necessari prima di rimuoverli
- **Consolidare** documentazione obsoleta nel nuovo `MANUAL.md`



