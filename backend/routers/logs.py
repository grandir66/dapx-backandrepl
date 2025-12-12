"""
Router per gestione log
Con autenticazione
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, timedelta
from pydantic import BaseModel
import os
import subprocess
import logging

from database import get_db, JobLog, User, AuditLog
from routers.auth import get_current_user, require_admin

router = APIRouter()
logger = logging.getLogger(__name__)

# Directory dei log di sistema
SYSTEM_LOG_DIR = os.environ.get("DAPX_LOG_DIR", "/var/log/dapx-backandrepl")


# ============== Schemas ==============

class JobLogResponse(BaseModel):
    id: int
    job_type: str
    job_id: Optional[int] = None
    node_name: Optional[str] = None
    dataset: Optional[str] = None
    status: str
    message: Optional[str] = None
    output: Optional[str] = None
    error: Optional[str] = None
    duration: Optional[float] = None  # Can be float from database
    transferred: Optional[str] = None
    attempt_number: Optional[int] = 1
    started_at: datetime
    completed_at: Optional[datetime] = None
    triggered_by: Optional[int] = None
    backup_id: Optional[str] = None
    
    class Config:
        from_attributes = True


class LogStatsResponse(BaseModel):
    total: int
    success: int
    failed: int
    running: int
    success_rate: float
    avg_duration: Optional[float]
    total_transferred: Optional[str]


# ============== Endpoints ==============

@router.get("/", response_model=List[JobLogResponse])
async def list_logs(
    limit: int = 100,
    offset: int = 0,
    job_type: Optional[str] = None,
    status: Optional[str] = None,
    job_id: Optional[int] = None,
    since: Optional[datetime] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista i log delle operazioni"""
    query = db.query(JobLog)
    
    if job_type:
        query = query.filter(JobLog.job_type == job_type)
    if status:
        query = query.filter(JobLog.status == status)
    if job_id:
        query = query.filter(JobLog.job_id == job_id)
    if since:
        query = query.filter(JobLog.started_at >= since)
    
    logs = query.order_by(JobLog.started_at.desc()).offset(offset).limit(limit).all()
    return logs


@router.get("/stats", response_model=LogStatsResponse)
async def get_log_stats(
    days: int = 7,
    job_type: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene statistiche sui log"""
    since = datetime.utcnow() - timedelta(days=days)
    
    query = db.query(JobLog).filter(JobLog.started_at >= since)
    
    if job_type:
        query = query.filter(JobLog.job_type == job_type)
    
    logs = query.all()
    
    total = len(logs)
    success = len([l for l in logs if l.status == "success"])
    failed = len([l for l in logs if l.status == "failed"])
    running = len([l for l in logs if l.status in ("started", "running")])
    
    durations = [l.duration for l in logs if l.duration]
    avg_duration = sum(durations) / len(durations) if durations else None
    
    success_rate = (success / total * 100) if total > 0 else 0
    
    return LogStatsResponse(
        total=total,
        success=success,
        failed=failed,
        running=running,
        success_rate=round(success_rate, 1),
        avg_duration=round(avg_duration, 1) if avg_duration else None,
        total_transferred=None  # TODO: calcolare
    )


@router.get("/{log_id}", response_model=JobLogResponse)
async def get_log(
    log_id: int,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene un log specifico"""
    log = db.query(JobLog).filter(JobLog.id == log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Log non trovato")
    return log


@router.delete("/cleanup")
async def cleanup_old_logs(
    days: int = 30,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Elimina log più vecchi di N giorni (solo admin)"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    count = db.query(JobLog).filter(JobLog.started_at < cutoff).count()
    db.query(JobLog).filter(JobLog.started_at < cutoff).delete()
    db.commit()
    
    return {"message": f"Eliminati {count} log più vecchi di {days} giorni"}


@router.get("/recent/failed")
async def get_recent_failures(
    limit: int = 10,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene i fallimenti recenti"""
    logs = db.query(JobLog).filter(
        JobLog.status == "failed"
    ).order_by(JobLog.started_at.desc()).limit(limit).all()
    
    return logs


@router.get("/job/{job_id}/history")
async def get_job_history(
    job_id: int,
    limit: int = 50,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene lo storico di un job specifico"""
    logs = db.query(JobLog).filter(
        JobLog.job_id == job_id
    ).order_by(JobLog.started_at.desc()).limit(limit).all()
    
    return logs


# ============== Audit Log Endpoints ==============

@router.get("/audit")
async def list_audit_logs(
    limit: int = 100,
    user_id: Optional[int] = None,
    action: Optional[str] = None,
    resource_type: Optional[str] = None,
    since: Optional[datetime] = None,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Lista i log di audit (solo admin)"""
    query = db.query(AuditLog)
    
    if user_id:
        query = query.filter(AuditLog.user_id == user_id)
    if action:
        query = query.filter(AuditLog.action == action)
    if resource_type:
        query = query.filter(AuditLog.resource_type == resource_type)
    if since:
        query = query.filter(AuditLog.created_at >= since)
    
    logs = query.order_by(AuditLog.created_at.desc()).limit(limit).all()
    
    # Aggiungi username
    from database import User as UserModel
    result = []
    for log in logs:
        log_dict = {
            "id": log.id,
            "user_id": log.user_id,
            "action": log.action,
            "resource_type": log.resource_type,
            "resource_id": log.resource_id,
            "details": log.details,
            "ip_address": log.ip_address,
            "status": log.status,
            "created_at": log.created_at,
            "username": None
        }
        if log.user_id:
            user_obj = db.query(UserModel).filter(UserModel.id == log.user_id).first()
            if user_obj:
                log_dict["username"] = user_obj.username
        result.append(log_dict)
    
    return result


@router.delete("/audit/cleanup")
async def cleanup_audit_logs(
    days: int = 90,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Elimina audit log più vecchi di N giorni (solo admin)"""
    cutoff = datetime.utcnow() - timedelta(days=days)
    
    count = db.query(AuditLog).filter(AuditLog.created_at < cutoff).count()
    db.query(AuditLog).filter(AuditLog.created_at < cutoff).delete()
    db.commit()
    
    return {"message": f"Eliminati {count} audit log più vecchi di {days} giorni"}


# ============== System Log Endpoints ==============

@router.get("/system")
async def get_system_logs(
    lines: int = Query(default=200, le=2000, description="Numero di righe da restituire"),
    level: Optional[str] = Query(default=None, description="Filtra per livello (DEBUG, INFO, WARNING, ERROR)"),
    search: Optional[str] = Query(default=None, description="Cerca nel testo"),
    file: str = Query(default="dapx.log", description="File di log (dapx.log, dapx-errors.log)"),
    user: User = Depends(require_admin)
):
    """
    Legge i log di sistema dal file (solo admin).
    
    I log di sistema contengono dettagli estesi:
    - Timestamp preciso
    - Modulo e funzione
    - Numero di linea
    - Thread/Task asyncio
    """
    # Valida nome file (previeni path traversal)
    allowed_files = ["dapx.log", "dapx-errors.log", "dapx.json.log"]
    if file not in allowed_files:
        raise HTTPException(status_code=400, detail=f"File non valido. Ammessi: {', '.join(allowed_files)}")
    
    log_file = os.path.join(SYSTEM_LOG_DIR, file)
    
    # Se il file non esiste, prova a leggere da journalctl
    if not os.path.exists(log_file):
        logger.info(f"File {log_file} non trovato, uso journalctl")
        return await get_journalctl_logs(lines, level, search)
    
    try:
        # Leggi ultime N righe del file
        result = subprocess.run(
            ["tail", "-n", str(lines), log_file],
            capture_output=True,
            text=True,
            timeout=10
        )
        
        if result.returncode != 0:
            raise HTTPException(status_code=500, detail=f"Errore lettura log: {result.stderr}")
        
        log_lines = result.stdout.strip().split('\n')
        
        # Filtra per livello se specificato
        if level:
            level = level.upper()
            log_lines = [l for l in log_lines if level in l]
        
        # Filtra per testo se specificato
        if search:
            search_lower = search.lower()
            log_lines = [l for l in log_lines if search_lower in l.lower()]
        
        # Parse delle righe per struttura
        parsed_logs = []
        for line in log_lines:
            if not line.strip():
                continue
            
            parsed = parse_log_line(line)
            parsed_logs.append(parsed)
        
        return {
            "source": "file",
            "file": log_file,
            "total_lines": len(parsed_logs),
            "filters": {
                "level": level,
                "search": search
            },
            "logs": parsed_logs
        }
        
    except subprocess.TimeoutExpired:
        raise HTTPException(status_code=500, detail="Timeout lettura log")
    except Exception as e:
        logger.error(f"Errore lettura log di sistema: {e}")
        raise HTTPException(status_code=500, detail=f"Errore: {str(e)}")


async def get_journalctl_logs(lines: int, level: Optional[str], search: Optional[str]):
    """Fallback: legge log da journalctl"""
    try:
        cmd = ["journalctl", "-u", "sanoid-manager", "-n", str(lines), "--no-pager", "-o", "short-iso"]
        
        # Aggiungi filtro priorità se specificato
        priority_map = {
            "DEBUG": "7",
            "INFO": "6", 
            "WARNING": "4",
            "ERROR": "3"
        }
        if level and level.upper() in priority_map:
            cmd.extend(["-p", priority_map[level.upper()]])
        
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        
        log_lines = result.stdout.strip().split('\n')
        
        # Filtra per testo se specificato
        if search:
            search_lower = search.lower()
            log_lines = [l for l in log_lines if search_lower in l.lower()]
        
        parsed_logs = []
        for line in log_lines:
            if not line.strip() or line.startswith("--"):
                continue
            parsed_logs.append({
                "raw": line,
                "timestamp": None,
                "level": "INFO",
                "module": "journalctl",
                "message": line
            })
        
        return {
            "source": "journalctl",
            "total_lines": len(parsed_logs),
            "filters": {
                "level": level,
                "search": search
            },
            "logs": parsed_logs
        }
    except Exception as e:
        logger.error(f"Errore lettura journalctl: {e}")
        raise HTTPException(status_code=500, detail=f"Errore journalctl: {str(e)}")


def parse_log_line(line: str) -> dict:
    """
    Parse di una riga di log nel formato:
    2025-12-12 11:04:40.123 INFO     module.name                    function:42              [Thread] message
    """
    result = {
        "raw": line,
        "timestamp": None,
        "level": None,
        "module": None,
        "function": None,
        "line_no": None,
        "thread": None,
        "message": line
    }
    
    try:
        # Prova a parsare il formato dettagliato
        parts = line.split(None, 5)  # Split sui primi 5 spazi
        
        if len(parts) >= 2:
            # Timestamp (YYYY-MM-DD HH:MM:SS.mmm)
            if len(parts[0]) == 10 and '-' in parts[0]:  # Data
                result["timestamp"] = f"{parts[0]} {parts[1]}"
                
                if len(parts) >= 3:
                    # Livello
                    level = parts[2].strip()
                    if level in ("DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"):
                        result["level"] = level
                    
                    if len(parts) >= 4:
                        # Modulo
                        result["module"] = parts[3].strip()
                        
                        if len(parts) >= 5:
                            # Funzione:linea
                            func_line = parts[4].strip()
                            if ':' in func_line:
                                func, line_no = func_line.rsplit(':', 1)
                                result["function"] = func
                                try:
                                    result["line_no"] = int(line_no)
                                except ValueError:
                                    pass
                            
                            if len(parts) >= 6:
                                # Resto del messaggio (include thread e messaggio)
                                rest = parts[5]
                                # Estrai thread se presente [Thread/Task]
                                if rest.startswith('[') and ']' in rest:
                                    thread_end = rest.index(']')
                                    result["thread"] = rest[1:thread_end]
                                    result["message"] = rest[thread_end+1:].strip()
                                else:
                                    result["message"] = rest.strip()
    except Exception:
        pass  # Mantieni il raw se il parsing fallisce
    
    return result


@router.get("/system/files")
async def list_log_files(user: User = Depends(require_admin)):
    """Lista i file di log disponibili"""
    files = []
    
    if os.path.exists(SYSTEM_LOG_DIR):
        for filename in os.listdir(SYSTEM_LOG_DIR):
            filepath = os.path.join(SYSTEM_LOG_DIR, filename)
            if os.path.isfile(filepath):
                stat = os.stat(filepath)
                files.append({
                    "name": filename,
                    "path": filepath,
                    "size": stat.st_size,
                    "size_human": format_size(stat.st_size),
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
    
    # Aggiungi info su journalctl
    try:
        result = subprocess.run(
            ["journalctl", "-u", "sanoid-manager", "--disk-usage"],
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            files.append({
                "name": "journalctl (sanoid-manager)",
                "path": "journalctl",
                "size": 0,
                "size_human": result.stdout.strip(),
                "modified": None
            })
    except Exception:
        pass
    
    return {
        "log_dir": SYSTEM_LOG_DIR,
        "log_dir_exists": os.path.exists(SYSTEM_LOG_DIR),
        "files": files
    }


@router.get("/system/live")
async def get_live_logs(
    lines: int = Query(default=50, le=500),
    user: User = Depends(require_admin)
):
    """
    Ottiene gli ultimi log in tempo reale (per polling).
    Utile per aggiornamento live nell'interfaccia.
    """
    log_file = os.path.join(SYSTEM_LOG_DIR, "dapx.log")
    
    if os.path.exists(log_file):
        try:
            result = subprocess.run(
                ["tail", "-n", str(lines), log_file],
                capture_output=True,
                text=True,
                timeout=5
            )
            log_lines = result.stdout.strip().split('\n') if result.stdout else []
        except Exception:
            log_lines = []
    else:
        # Fallback a journalctl
        try:
            result = subprocess.run(
                ["journalctl", "-u", "sanoid-manager", "-n", str(lines), "--no-pager"],
                capture_output=True,
                text=True,
                timeout=5
            )
            log_lines = result.stdout.strip().split('\n') if result.stdout else []
        except Exception:
            log_lines = []
    
    return {
        "timestamp": datetime.utcnow().isoformat(),
        "count": len(log_lines),
        "logs": log_lines[-lines:]  # Ultime N righe
    }


def format_size(size_bytes: int) -> str:
    """Formatta dimensione in formato leggibile"""
    if size_bytes >= 1024 * 1024 * 1024:
        return f"{size_bytes / (1024*1024*1024):.2f} GB"
    elif size_bytes >= 1024 * 1024:
        return f"{size_bytes / (1024*1024):.2f} MB"
    elif size_bytes >= 1024:
        return f"{size_bytes / 1024:.2f} KB"
    else:
        return f"{size_bytes} B"
