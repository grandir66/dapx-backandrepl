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
VERSION_FILE = os.path.join(INSTALL_DIR, "version.txt")

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
        # Prova file version.txt
        if os.path.exists(VERSION_FILE):
            with open(VERSION_FILE, 'r') as f:
                return f.read().strip()
        
        # Prova git describe
        if os.path.exists(os.path.join(INSTALL_DIR, ".git")):
            result = subprocess.run(
                ["git", "describe", "--tags", "--always"],
                cwd=INSTALL_DIR,
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                return result.stdout.strip()
        
        # Prova git rev-parse
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=INSTALL_DIR,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            return result.stdout.strip()
        
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
        
        result = subprocess.run(
            ["pip3", "install", "--no-cache-dir", "-r", "requirements.txt", "--upgrade"],
            cwd=backend_dir,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            # Prova con pip
            result = subprocess.run(
                ["pip", "install", "--no-cache-dir", "-r", "requirements.txt", "--upgrade"],
                cwd=backend_dir,
                capture_output=True,
                text=True
            )
        
        log("Dipendenze aggiornate")
        
        # Ricarica servizio
        log("Ricarica configurazione systemd...")
        subprocess.run(["systemctl", "daemon-reload"], capture_output=True)
        
        # Riavvia servizio
        log("Riavvio servizio...")
        service_names = ["dapx-backandrepl", "sanoid-manager"]
        for service in service_names:
            result = subprocess.run(
                ["systemctl", "restart", service],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                log(f"Servizio {service} riavviato")
                break
        
        # Attendi che il servizio sia pronto
        await asyncio.sleep(3)
        
        # Verifica servizio
        log("Verifica servizio...")
        for service in service_names:
            result = subprocess.run(
                ["systemctl", "is-active", service],
                capture_output=True,
                text=True
            )
            if result.returncode == 0:
                log(f"Servizio {service} attivo")
                break
        
        # Aggiorna versione
        update_status["current_version"] = get_current_version()
        update_status["last_update"] = datetime.now().isoformat()
        update_status["update_available"] = False
        
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
    return {
        "version": get_current_version(),
        "install_dir": INSTALL_DIR
    }

