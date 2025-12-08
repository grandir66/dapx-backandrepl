"""
DAPX-backandrepl - Sistema di Aggiornamento
Gestione aggiornamenti da interfaccia web
"""

from fastapi import APIRouter, HTTPException, Depends, BackgroundTasks
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import subprocess
import os
import logging
import asyncio
from datetime import datetime
import json
import httpx

from database import get_db, SessionLocal
from routers.auth import require_admin, User

router = APIRouter(prefix="/api/updates", tags=["updates"])
logger = logging.getLogger(__name__)

# Stato aggiornamento globale
update_status = {
    "in_progress": False,
    "last_check": None,
    "last_update": None,
    "current_version": None,
    "available_version": None,
    "update_available": False,
    "log": [],
    "error": None
}

# Configurazione
GITHUB_REPO = "grandir66/dapx-backandrepl"
GITHUB_API = f"https://api.github.com/repos/{GITHUB_REPO}"
INSTALL_DIR = "/opt/dapx-backandrepl"
VERSION_FILE = os.path.join(INSTALL_DIR, "VERSION")  # File VERSION nella root

# Modelli
class UpdateCheckResponse(BaseModel):
    current_version: str
    available_version: Optional[str]
    update_available: bool
    last_check: Optional[str]
    changelog: Optional[str] = None
    release_date: Optional[str] = None
    release_url: Optional[str] = None

class UpdateStatusResponse(BaseModel):
    in_progress: bool
    last_update: Optional[str]
    log: List[str]
    error: Optional[str]
    success: Optional[bool] = None

class UpdateStartResponse(BaseModel):
    success: bool
    message: str


def get_current_version() -> str:
    """Ottieni versione corrente installata"""
    try:
        # Prova file VERSION (priorità massima)
        version_file = VERSION_FILE
        # Prova anche nella root del progetto se INSTALL_DIR non contiene VERSION
        if not os.path.exists(version_file):
            # Prova percorsi alternativi
            alt_paths = [
                os.path.join(INSTALL_DIR, "VERSION"),
                "/opt/dapx-backandrepl/VERSION",
                os.path.join(os.path.dirname(os.path.dirname(__file__)), "..", "VERSION"),
                os.path.join(os.getcwd(), "VERSION")
            ]
            for alt_path in alt_paths:
                if os.path.exists(alt_path):
                    version_file = alt_path
                    break
        
        if os.path.exists(version_file):
            try:
                with open(version_file, 'r') as f:
                    version = f.read().strip()
                    if version:
                        logger.debug(f"Versione letta da {version_file}: {version}")
                        return version
            except Exception as e:
                logger.warning(f"Errore lettura file VERSION {version_file}: {e}")
        
        # Fallback: Prova git describe
        if os.path.exists(os.path.join(INSTALL_DIR, ".git")):
            result = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                cwd=INSTALL_DIR,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                version = result.stdout.strip()
                logger.debug(f"Versione da git describe: {version}")
                return version
        
        # Fallback: Prova git rev-parse
        if os.path.exists(os.path.join(INSTALL_DIR, ".git")):
            result = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                cwd=INSTALL_DIR,
                capture_output=True,
                text=True,
                timeout=5
            )
            if result.returncode == 0 and result.stdout.strip():
                version = result.stdout.strip()
                logger.debug(f"Versione da git rev-parse: {version}")
                return version
        
        logger.warning("Impossibile determinare versione, uso 'unknown'")
        return "unknown"
    except Exception as e:
        logger.error(f"Errore lettura versione: {e}")
        return "unknown"


async def get_latest_release() -> Dict[str, Any]:
    """Ottieni ultima release da GitHub"""
    try:
        async with httpx.AsyncClient() as client:
            # Prova prima le releases
            response = await client.get(
                f"{GITHUB_API}/releases/latest",
                timeout=10.0,
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "version": data.get("tag_name", "").lstrip("v"),
                    "changelog": data.get("body", ""),
                    "date": data.get("published_at", ""),
                    "url": data.get("html_url", ""),
                    "prerelease": data.get("prerelease", False)
                }
            
            # Se non ci sono releases, usa i commit
            response = await client.get(
                f"{GITHUB_API}/commits/main",
                timeout=10.0,
                headers={"Accept": "application/vnd.github.v3+json"}
            )
            
            if response.status_code == 200:
                data = response.json()
                return {
                    "version": data.get("sha", "")[:7],
                    "changelog": data.get("commit", {}).get("message", ""),
                    "date": data.get("commit", {}).get("author", {}).get("date", ""),
                    "url": data.get("html_url", ""),
                    "prerelease": False
                }
            
            return None
    except Exception as e:
        logger.error(f"Errore recupero release GitHub: {e}")
        return None


async def run_update_process():
    """Esegue il processo di aggiornamento"""
    global update_status
    
    update_status["in_progress"] = True
    update_status["log"] = []
    update_status["error"] = None
    
    def log(msg: str):
        timestamp = datetime.now().strftime("%H:%M:%S")
        update_status["log"].append(f"[{timestamp}] {msg}")
        logger.info(f"Update: {msg}")
    
    try:
        log("Avvio aggiornamento...")
        
        # Verifica directory installazione
        if not os.path.exists(INSTALL_DIR):
            raise Exception(f"Directory installazione non trovata: {INSTALL_DIR}")
        
        # Backup database
        log("Creazione backup database...")
        backup_dir = "/tmp/dapx-backup"
        os.makedirs(backup_dir, exist_ok=True)
        
        db_paths = [
            "/var/lib/dapx-backandrepl/dapx-backandrepl.db",
            "/var/lib/sanoid-manager/sanoid-manager.db"
        ]
        for db_path in db_paths:
            if os.path.exists(db_path):
                backup_name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
                subprocess.run(["cp", db_path, os.path.join(backup_dir, backup_name)])
                log(f"Backup creato: {backup_name}")
                break
        
        # Ferma servizio temporaneamente (opzionale, per sicurezza)
        # log("Fermata servizio...")
        # subprocess.run(["systemctl", "stop", "dapx-backandrepl"], capture_output=True)
        
        # Aggiorna codice da Git
        log("Download aggiornamenti da GitHub...")
        
        if os.path.exists(os.path.join(INSTALL_DIR, ".git")):
            # Repository Git esistente
            result = subprocess.run(
                ["git", "fetch", "origin", "main"],
                cwd=INSTALL_DIR,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise Exception(f"Errore git fetch: {result.stderr}")
            
            result = subprocess.run(
                ["git", "reset", "--hard", "origin/main"],
                cwd=INSTALL_DIR,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise Exception(f"Errore git reset: {result.stderr}")
            
            log("Codice aggiornato da Git")
            
            # Verifica che il file VERSION sia stato aggiornato
            if os.path.exists(VERSION_FILE):
                try:
                    with open(VERSION_FILE, 'r') as f:
                        new_version = f.read().strip()
                    log(f"Versione aggiornata: {new_version}")
                except Exception as e:
                    log(f"Warning: impossibile leggere VERSION dopo aggiornamento: {e}")
        else:
            # Non è un repository Git
            log("Download nuova versione...")
            subprocess.run(["rm", "-rf", "/tmp/dapx-update"], capture_output=True)
            result = subprocess.run(
                ["git", "clone", "--depth", "1", "--branch", "main",
                 f"https://github.com/{GITHUB_REPO}.git", "/tmp/dapx-update"],
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                raise Exception(f"Errore git clone: {result.stderr}")
            
            # Copia nuovi file
            subprocess.run(
                ["rsync", "-av", "--exclude=.git", "/tmp/dapx-update/", f"{INSTALL_DIR}/"],
                capture_output=True
            )
            log("Nuova versione scaricata")
        
        # Aggiorna dipendenze Python
        log("Aggiornamento dipendenze Python...")
        backend_dir = os.path.join(INSTALL_DIR, "backend")
        
        # Prima prova con --break-system-packages (Debian 12+)
        result = subprocess.run(
            ["pip3", "install", "--no-cache-dir", "--break-system-packages", "-r", "requirements.txt", "--upgrade"],
            cwd=backend_dir,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            # Riprova senza --break-system-packages (versioni più vecchie)
            result = subprocess.run(
                ["pip3", "install", "--no-cache-dir", "-r", "requirements.txt", "--upgrade"],
                cwd=backend_dir,
                capture_output=True,
                text=True
            )
        if result.returncode != 0:
            log(f"Warning dipendenze: {result.stderr[:200] if result.stderr else 'errore pip'}")
        
        log("Dipendenze aggiornate")
        
        # Ricarica servizio
        log("Ricarica configurazione systemd...")
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
        
        # Riavvia servizio - trova il servizio corretto
        log("Riavvio servizio...")
        service_names = ["dapx-backandrepl", "sanoid-manager"]
        service_found = None
        
        # Cerca quale servizio esiste
        for service in service_names:
            result = subprocess.run(
                ["systemctl", "list-unit-files", f"{service}.service"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0 and service in result.stdout:
                service_found = service
                log(f"Servizio trovato: {service}")
                break
        
        if not service_found:
            # Prova a cercare servizi che contengono "dapx" o "sanoid"
            log("Ricerca servizio alternativo...")
            result = subprocess.run(
                ["systemctl", "list-unit-files", "--type=service", "--no-pager"],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                for line in result.stdout.splitlines():
                    if "dapx" in line.lower() or "sanoid" in line.lower():
                        # Estrai nome servizio
                        parts = line.split()
                        if parts and ".service" in parts[0]:
                            service_found = parts[0].replace(".service", "")
                            log(f"Servizio alternativo trovato: {service_found}")
                            break
        
        if service_found:
            # Riavvia il servizio trovato
            result = subprocess.run(
                ["systemctl", "restart", service_found],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                log(f"Servizio {service_found} riavviato")
            else:
                log(f"Warning: errore riavvio servizio {service_found}: {result.stderr}")
        else:
            log("Warning: nessun servizio systemd trovato. Il servizio potrebbe non essere installato come systemd service.")
            log("Per installare il servizio, esegui: ./install.sh")
        
        # Attendi che il servizio sia pronto
        await asyncio.sleep(3)
        
        # Verifica servizio
        if service_found:
            log("Verifica servizio...")
            result = subprocess.run(
                ["systemctl", "is-active", service_found],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                log(f"Servizio {service_found} attivo")
            else:
                log(f"Warning: servizio {service_found} non risulta attivo")
                log(f"Controlla con: systemctl status {service_found}")
        else:
            log("Impossibile verificare servizio: servizio non trovato")
        
        # Aggiorna versione (forza rilettura dopo aggiornamento)
        log("Lettura versione aggiornata...")
        old_version = update_status.get("current_version", "unknown")
        new_version = get_current_version()
        
        # Verifica che il file VERSION sia stato aggiornato
        if os.path.exists(VERSION_FILE):
            try:
                with open(VERSION_FILE, 'r') as f:
                    file_version = f.read().strip()
                log(f"Versione nel file VERSION: {file_version}")
                if file_version and file_version != new_version:
                    log(f"Warning: versione file ({file_version}) diversa da quella letta ({new_version})")
            except Exception as e:
                log(f"Warning: impossibile leggere file VERSION: {e}")
        
        update_status["current_version"] = new_version
        update_status["last_update"] = datetime.now().isoformat()
        update_status["update_available"] = False
        
        if old_version != new_version:
            log(f"Versione aggiornata: {old_version} → {new_version}")
        else:
            log(f"Versione corrente: {new_version}")
        
        log("✓ Aggiornamento completato con successo!")
        
    except Exception as e:
        logger.error(f"Errore aggiornamento: {e}")
        update_status["error"] = str(e)
        update_status["log"].append(f"[ERRORE] {str(e)}")
    
    finally:
        update_status["in_progress"] = False


@router.get("/check", response_model=UpdateCheckResponse)
async def check_for_updates(user: User = Depends(require_admin)):
    """Verifica se ci sono aggiornamenti disponibili"""
    global update_status
    
    current = get_current_version()
    update_status["current_version"] = current
    
    latest = await get_latest_release()
    
    if latest:
        available = latest.get("version", "")
        update_status["available_version"] = available
        update_status["last_check"] = datetime.now().isoformat()
        
        # Confronta versioni (semplificato)
        update_available = False
        if current != available and available:
            # Se la versione corrente è un hash corto, confronta
            if len(current) == 7 and len(available) >= 7:
                update_available = current != available[:7]
            else:
                update_available = current != available
        
        update_status["update_available"] = update_available
        
        return UpdateCheckResponse(
            current_version=current,
            available_version=available,
            update_available=update_available,
            last_check=update_status["last_check"],
            changelog=latest.get("changelog"),
            release_date=latest.get("date"),
            release_url=latest.get("url")
        )
    
    return UpdateCheckResponse(
        current_version=current,
        available_version=None,
        update_available=False,
        last_check=datetime.now().isoformat()
    )


@router.get("/status", response_model=UpdateStatusResponse)
async def get_update_status(user: User = Depends(require_admin)):
    """Ottieni stato aggiornamento in corso"""
    return UpdateStatusResponse(
        in_progress=update_status["in_progress"],
        last_update=update_status["last_update"],
        log=update_status["log"],
        error=update_status["error"],
        success=update_status["error"] is None if update_status["log"] else None
    )


@router.post("/start", response_model=UpdateStartResponse)
async def start_update(
    background_tasks: BackgroundTasks,
    user: User = Depends(require_admin)
):
    """Avvia aggiornamento"""
    global update_status
    
    if update_status["in_progress"]:
        raise HTTPException(status_code=409, detail="Aggiornamento già in corso")
    
    # Avvia aggiornamento in background
    background_tasks.add_task(run_update_process)
    
    return UpdateStartResponse(
        success=True,
        message="Aggiornamento avviato. Controlla lo stato per i progressi."
    )


@router.get("/version")
async def get_version():
    """Ottieni versione corrente (pubblico)"""
    version = get_current_version()
    version_file_exists = os.path.exists(VERSION_FILE)
    return {
        "version": version,
        "install_dir": INSTALL_DIR,
        "version_file": VERSION_FILE,
        "version_file_exists": version_file_exists,
        "version_file_content": None if not version_file_exists else open(VERSION_FILE, 'r').read().strip()
    }


@router.post("/refresh-version")
async def refresh_version(user: User = Depends(require_admin)):
    """Forza refresh della versione (utile dopo aggiornamento)"""
    try:
        # Forza rilettura del file VERSION
        version = get_current_version()
        update_status["current_version"] = version
        
        # Verifica anche se il file esiste
        version_file_exists = os.path.exists(VERSION_FILE)
        version_file_content = None
        if version_file_exists:
            with open(VERSION_FILE, 'r') as f:
                version_file_content = f.read().strip()
        
        return {
            "success": True,
            "version": version,
            "version_file": VERSION_FILE,
            "version_file_exists": version_file_exists,
            "version_file_content": version_file_content,
            "message": f"Versione aggiornata: {version}"
        }
    except Exception as e:
        logger.error(f"Errore refresh versione: {e}")
        raise HTTPException(status_code=500, detail=f"Errore refresh versione: {str(e)}")

