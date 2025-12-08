"""
Router per gestione impostazioni di sistema
Con autenticazione e configurazione avanzata
"""

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session
from typing import Optional, Dict, Any, List
from pydantic import BaseModel, field_validator
from datetime import datetime
import logging

from database import (
    get_db, Settings, SystemConfig, NotificationConfig, User,
    get_config_value, set_config_value, init_default_config, SessionLocal
)
from routers.auth import get_current_user, require_admin, log_audit

router = APIRouter()
logger = logging.getLogger(__name__)


# ============== Schemas ==============

class SettingUpdate(BaseModel):
    value: str


class SystemConfigUpdate(BaseModel):
    value: str
    description: Optional[str] = None


class SystemConfigResponse(BaseModel):
    key: str
    value: Optional[str]
    value_type: str
    category: str
    description: Optional[str]
    is_secret: bool
    
    class Config:
        from_attributes = True


class NotificationConfigUpdate(BaseModel):
    # SMTP
    smtp_enabled: Optional[bool] = None
    smtp_host: Optional[str] = None
    smtp_port: Optional[int] = None
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_from: Optional[str] = None
    smtp_to: Optional[str] = None  # Destinatari separati da virgola
    smtp_subject_prefix: Optional[str] = None  # Prefisso soggetto
    smtp_tls: Optional[bool] = None
    
    # Webhook
    webhook_enabled: Optional[bool] = None
    webhook_url: Optional[str] = None
    webhook_secret: Optional[str] = None
    
    # Telegram
    telegram_enabled: Optional[bool] = None
    telegram_bot_token: Optional[str] = None
    telegram_chat_id: Optional[str] = None
    
    # Triggers
    notify_on_success: Optional[bool] = None
    notify_on_failure: Optional[bool] = None
    notify_on_warning: Optional[bool] = None
    
    @field_validator('smtp_port', mode='before')
    @classmethod
    def convert_port_to_int(cls, v):
        if v is None or v == '':
            return None
        return int(v)


class NotificationConfigResponse(BaseModel):
    id: int
    smtp_enabled: bool
    smtp_host: Optional[str]
    smtp_port: int
    smtp_user: Optional[str]
    smtp_from: Optional[str]
    smtp_to: Optional[str]
    smtp_subject_prefix: Optional[str]
    smtp_tls: bool
    
    webhook_enabled: bool
    webhook_url: Optional[str]
    
    telegram_enabled: bool
    telegram_chat_id: Optional[str]
    
    notify_on_success: bool
    notify_on_failure: bool
    notify_on_warning: bool
    
    class Config:
        from_attributes = True


class AuthConfigUpdate(BaseModel):
    auth_method: str  # local, proxmox
    auth_proxmox_node: Optional[str] = None
    auth_proxmox_port: Optional[int] = 8006
    auth_proxmox_verify_ssl: Optional[bool] = False
    auth_session_timeout: Optional[int] = 480
    auth_allow_local_fallback: Optional[bool] = True


class ServerConfigUpdate(BaseModel):
    port: Optional[int] = None
    ssl_enabled: Optional[bool] = None


class ServerConfigResponse(BaseModel):
    port: int
    ssl_enabled: bool
    ssl_ready: bool
    cert_exists: bool
    key_exists: bool
    restart_required: bool


class DatabaseResetRequest(BaseModel):
    confirm: bool = False
    backup: bool = True  # Crea backup prima del reset


# ============== Legacy Endpoints (compatibilità) ==============

@router.get("/")
async def list_settings(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Lista tutte le impostazioni (legacy)"""
    settings = db.query(Settings).all()
    return {s.key: {"value": s.value, "description": s.description} for s in settings}


@router.get("/legacy/{key}")
async def get_setting(
    key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene un'impostazione specifica (legacy)"""
    setting = db.query(Settings).filter(Settings.key == key).first()
    if not setting:
        raise HTTPException(status_code=404, detail="Impostazione non trovata")
    return {"key": setting.key, "value": setting.value, "description": setting.description}


@router.put("/legacy/{key}")
async def update_setting(
    key: str,
    update: SettingUpdate,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Aggiorna un'impostazione (legacy)"""
    setting = db.query(Settings).filter(Settings.key == key).first()
    
    if setting:
        setting.value = update.value
    else:
        setting = Settings(key=key, value=update.value)
        db.add(setting)
    
    log_audit(
        db, user.id, "setting_updated", "settings",
        details=f"Updated setting: {key}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    return {"key": key, "value": update.value}


# ============== System Config Endpoints ==============

@router.get("/system/all", response_model=Dict[str, Any])
async def get_all_system_config(
    category: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene tutte le configurazioni di sistema"""
    init_default_config(db)
    
    query = db.query(SystemConfig)
    if category:
        query = query.filter(SystemConfig.category == category)
    
    configs = query.all()
    
    result = {}
    for config in configs:
        # Non mostrare valori segreti a non-admin
        if config.is_secret and user.role != "admin":
            value = "********"
        else:
            value = config.value
        
        if config.category not in result:
            result[config.category] = {}
        
        result[config.category][config.key] = {
            "value": value,
            "type": config.value_type,
            "description": config.description
        }
    
    return result


@router.get("/system/{key}")
async def get_system_config(
    key: str,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene una configurazione di sistema specifica"""
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    if not config:
        raise HTTPException(status_code=404, detail="Configurazione non trovata")
    
    if config.is_secret and user.role != "admin":
        raise HTTPException(status_code=403, detail="Accesso negato")
    
    return SystemConfigResponse.model_validate(config)


@router.put("/system/{key}")
async def update_system_config(
    key: str,
    update: SystemConfigUpdate,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Aggiorna una configurazione di sistema"""
    config = db.query(SystemConfig).filter(SystemConfig.key == key).first()
    
    if config:
        config.value = update.value
        if update.description:
            config.description = update.description
        config.updated_at = datetime.utcnow()
    else:
        config = SystemConfig(
                key=key,
            value=update.value,
            description=update.description
        )
        db.add(config)
    
    log_audit(
        db, user.id, "system_config_updated", "settings",
        details=f"Updated system config: {key}",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    return {"key": key, "value": update.value}


# ============== Auth Config Endpoints ==============

@router.get("/auth/config")
async def get_auth_settings(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Ottiene le impostazioni di autenticazione"""
    init_default_config(db)
    
    return {
        "auth_method": get_config_value(db, "auth_method", "proxmox"),
        "auth_proxmox_node": get_config_value(db, "auth_proxmox_node", ""),
        "auth_proxmox_port": get_config_value(db, "auth_proxmox_port", 8006),
        "auth_proxmox_verify_ssl": get_config_value(db, "auth_proxmox_verify_ssl", False),
        "auth_session_timeout": get_config_value(db, "auth_session_timeout", 480),
        "auth_allow_local_fallback": get_config_value(db, "auth_allow_local_fallback", True)
    }


@router.put("/auth/config")
async def update_auth_settings(
    config: AuthConfigUpdate,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Aggiorna le impostazioni di autenticazione"""
    
    set_config_value(db, "auth_method", config.auth_method)
    
    if config.auth_proxmox_node is not None:
        set_config_value(db, "auth_proxmox_node", config.auth_proxmox_node)
    if config.auth_proxmox_port is not None:
        set_config_value(db, "auth_proxmox_port", config.auth_proxmox_port, "int")
    if config.auth_proxmox_verify_ssl is not None:
        set_config_value(db, "auth_proxmox_verify_ssl", config.auth_proxmox_verify_ssl, "bool")
    if config.auth_session_timeout is not None:
        set_config_value(db, "auth_session_timeout", config.auth_session_timeout, "int")
    if config.auth_allow_local_fallback is not None:
        set_config_value(db, "auth_allow_local_fallback", config.auth_allow_local_fallback, "bool")
    
    log_audit(
        db, user.id, "auth_config_updated", "settings",
        details=f"Auth method: {config.auth_method}",
        ip_address=request.client.host if request.client else None
    )
    
    return {"message": "Configurazione autenticazione aggiornata"}


# ============== Notification Config Endpoints ==============

@router.get("/notifications", response_model=NotificationConfigResponse)
async def get_notification_config(
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Ottiene la configurazione delle notifiche"""
    config = db.query(NotificationConfig).first()
    if not config:
        config = NotificationConfig()
        db.add(config)
        db.commit()
        db.refresh(config)
    
    return config


@router.put("/notifications")
async def update_notification_config(
    update: NotificationConfigUpdate,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Aggiorna la configurazione delle notifiche"""
    config = db.query(NotificationConfig).first()
    if not config:
        config = NotificationConfig()
        db.add(config)
    
    for key, value in update.model_dump(exclude_unset=True).items():
        setattr(config, key, value)
    
    config.updated_at = datetime.utcnow()
    
    log_audit(
        db, user.id, "notification_config_updated", "settings",
        ip_address=request.client.host if request.client else None
    )
    
    db.commit()
    return {"message": "Configurazione notifiche aggiornata"}


@router.post("/notifications/test")
async def test_notification(
    channel: str,  # email, webhook, telegram
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Invia una notifica di test"""
    config = db.query(NotificationConfig).first()
    if not config:
        raise HTTPException(status_code=400, detail="Notifiche non configurate")
    
    if channel == "email":
        if not config.smtp_enabled:
            raise HTTPException(status_code=400, detail="Email non abilitata")
        if not config.smtp_host:
            raise HTTPException(status_code=400, detail="Server SMTP non configurato")
        if not config.smtp_to:
            raise HTTPException(status_code=400, detail="Destinatario email non configurato")
        
        from services.email_service import email_service
        
        # Configura il servizio email
        email_service.configure(
            host=config.smtp_host,
            port=config.smtp_port or 587,
            user=config.smtp_user,
            password=config.smtp_password,
            from_addr=config.smtp_from,
            to_addrs=config.smtp_to,
            subject_prefix=config.smtp_subject_prefix or "[DAPX]",
            use_tls=config.smtp_tls
        )
        
        # Invia email di test
        success, message = email_service.send_test_email()
        
        if success:
            return {"success": True, "message": f"Email di test inviata a {config.smtp_to}"}
        else:
            raise HTTPException(status_code=500, detail=f"Errore invio email: {message}")
    
    elif channel == "webhook":
        if not config.webhook_enabled:
            raise HTTPException(status_code=400, detail="Webhook non abilitato")
        if not config.webhook_url:
            raise HTTPException(status_code=400, detail="URL Webhook non configurato")
        
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    config.webhook_url,
                    json={
                        "type": "test",
                        "message": "Test notifica da DAPX-backandrepl",
                        "timestamp": datetime.utcnow().isoformat()
                    },
                    headers={"X-Webhook-Secret": config.webhook_secret} if config.webhook_secret else {},
                    timeout=10
                )
                if response.status_code < 300:
                    return {"success": True, "message": f"Webhook inviato con successo (status: {response.status_code})"}
                else:
                    raise HTTPException(status_code=500, detail=f"Webhook fallito: HTTP {response.status_code}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Errore webhook: {str(e)}")
    
    elif channel == "telegram":
        if not config.telegram_enabled:
            raise HTTPException(status_code=400, detail="Telegram non abilitato")
        if not config.telegram_bot_token or not config.telegram_chat_id:
            raise HTTPException(status_code=400, detail="Token o Chat ID Telegram non configurati")
        
        import httpx
        try:
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    f"https://api.telegram.org/bot{config.telegram_bot_token}/sendMessage",
                    json={
                        "chat_id": config.telegram_chat_id,
                        "text": "🧪 *Test DAPX-backandrepl*\n\nSe ricevi questo messaggio, Telegram è configurato correttamente!",
                        "parse_mode": "Markdown"
                    },
                    timeout=10
                )
                result = response.json()
                if result.get("ok"):
                    return {"success": True, "message": "Messaggio Telegram inviato con successo"}
                else:
                    raise HTTPException(status_code=500, detail=f"Errore Telegram: {result.get('description', 'Unknown')}")
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Errore Telegram: {str(e)}")
    
    raise HTTPException(status_code=400, detail="Canale non valido")


@router.post("/notifications/send-daily-summary")
async def send_daily_summary_now(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Invia immediatamente il riepilogo giornaliero"""
    from services.notification_service import notification_service
    
    config = db.query(NotificationConfig).first()
    if not config:
        raise HTTPException(status_code=400, detail="Notifiche non configurate")
    
    # Verifica che almeno un canale sia abilitato
    if not (config.smtp_enabled or config.webhook_enabled or config.telegram_enabled):
        raise HTTPException(status_code=400, detail="Nessun canale di notifica abilitato")
    
    try:
        result = await notification_service.send_daily_summary()
        
        if result.get("sent"):
            log_audit(
                db, user.id, "daily_summary_sent", "notifications",
                details=f"Channels: {list(result.get('channels', {}).keys())}",
                ip_address=request.client.host if request.client else None
            )
            return {
                "success": True,
                "message": "Riepilogo giornaliero inviato",
                "channels": result.get("channels", {}),
                "summary": result.get("summary", {})
            }
        else:
            return {
                "success": False,
                "message": f"Riepilogo non inviato: {result.get('reason', 'unknown')}"
            }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore invio riepilogo: {str(e)}")


# ============== Categories ==============

@router.get("/categories")
async def get_config_categories(
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db)
):
    """Ottiene le categorie di configurazione disponibili"""
    return {
        "categories": [
            {"id": "auth", "name": "Autenticazione", "icon": "🔐"},
            {"id": "syncoid", "name": "Syncoid", "icon": "🔄"},
            {"id": "retention", "name": "Retention", "icon": "📦"},
            {"id": "notifications", "name": "Notifiche", "icon": "🔔"},
            {"id": "ssl", "name": "SSL/HTTPS", "icon": "🔒"},
            {"id": "ui", "name": "Interfaccia", "icon": "🎨"},
            {"id": "general", "name": "Generale", "icon": "⚙️"}
        ]
    }


# ============== SSL/HTTPS Configuration ==============

import os
import subprocess
from pathlib import Path

CERTS_DIR = Path(__file__).parent.parent / "certs"

@router.get("/ssl/status")
async def get_ssl_status(
    request: Request,
    user: User = Depends(get_current_user)
):
    """Ottiene lo stato della configurazione SSL"""
    cert_path = CERTS_DIR / "server.crt"
    key_path = CERTS_DIR / "server.key"
    
    # Rileva SSL da: variabile ambiente, header X-Forwarded-Proto, o schema richiesta
    ssl_from_env = os.environ.get("DAPX_SSL", "false").lower() == "true"
    ssl_from_header = request.headers.get("X-Forwarded-Proto", "").lower() == "https"
    ssl_from_scheme = request.url.scheme == "https"
    
    result = {
        "ssl_enabled": ssl_from_env or ssl_from_header or ssl_from_scheme,
        "ssl_ready": cert_path.exists() and key_path.exists(),
        "cert_exists": cert_path.exists(),
        "key_exists": key_path.exists(),
        "cert_path": str(cert_path) if cert_path.exists() else None,
        "key_path": str(key_path) if key_path.exists() else None,
        "cert_info": None
    }
    
    # Se il certificato esiste, ottieni info
    if cert_path.exists():
        try:
            from scripts.generate_cert import check_cert_valid
            valid, days_remaining, error = check_cert_valid(str(cert_path))
            result["cert_info"] = {
                "valid": valid,
                "days_remaining": days_remaining,
                "error": error
            }
        except Exception as e:
            result["cert_info"] = {"error": str(e)}
    
    return result


@router.post("/ssl/generate-cert")
async def generate_ssl_certificate(
    request: Request,
    hostname: str = None,
    ip_addresses: List[str] = None,
    days_valid: int = 365,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Genera un nuovo certificato SSL auto-firmato"""
    import socket
    
    # Determina hostname se non specificato
    if not hostname:
        hostname = socket.getfqdn()
    
    # Aggiungi IP locali se non specificati
    if not ip_addresses:
        ip_addresses = []
        try:
            # Ottieni IP locale
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(("8.8.8.8", 80))
            local_ip = s.getsockname()[0]
            s.close()
            ip_addresses.append(local_ip)
        except:
            pass
    
    try:
        from scripts.generate_cert import generate_self_signed_cert
        
        cert_path, key_path = generate_self_signed_cert(
            cert_dir=str(CERTS_DIR),
            hostname=hostname,
            ip_addresses=ip_addresses,
            days_valid=days_valid
        )
        
        log_audit(
            db, user.id, "ssl_cert_generated", "ssl",
            details=f"Certificate generated for {hostname}, valid {days_valid} days",
            ip_address=request.client.host if request.client else None
        )
        
        return {
            "success": True,
            "message": f"Certificato generato per {hostname}",
            "cert_path": cert_path,
            "key_path": key_path,
            "hostname": hostname,
            "days_valid": days_valid,
            "ip_addresses": ip_addresses
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore generazione certificato: {str(e)}")


class SSLCertUpload(BaseModel):
    certificate: str  # PEM format
    private_key: str  # PEM format


@router.post("/ssl/upload-cert")
async def upload_ssl_certificate(
    cert_data: SSLCertUpload,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Carica un certificato SSL personalizzato"""
    CERTS_DIR.mkdir(parents=True, exist_ok=True)
    
    cert_path = CERTS_DIR / "server.crt"
    key_path = CERTS_DIR / "server.key"
    
    try:
        # Verifica che siano PEM validi
        if not cert_data.certificate.strip().startswith("-----BEGIN CERTIFICATE-----"):
            raise HTTPException(status_code=400, detail="Certificato non in formato PEM valido")
        
        if not cert_data.private_key.strip().startswith("-----BEGIN"):
            raise HTTPException(status_code=400, detail="Chiave privata non in formato PEM valido")
        
        # Salva certificato
        with open(cert_path, "w") as f:
            f.write(cert_data.certificate.strip())
        
        # Salva chiave con permessi restrittivi
        with open(key_path, "w") as f:
            f.write(cert_data.private_key.strip())
        os.chmod(key_path, 0o600)
        
        log_audit(
            db, user.id, "ssl_cert_uploaded", "ssl",
            details="Custom SSL certificate uploaded",
            ip_address=request.client.host if request.client else None
        )
        
        return {
            "success": True,
            "message": "Certificato caricato con successo",
            "cert_path": str(cert_path),
            "key_path": str(key_path)
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Errore caricamento certificato: {str(e)}")


@router.delete("/ssl/cert")
async def delete_ssl_certificate(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """Elimina il certificato SSL corrente"""
    cert_path = CERTS_DIR / "server.crt"
    key_path = CERTS_DIR / "server.key"
    
    deleted = []
    
    if cert_path.exists():
        cert_path.unlink()
        deleted.append("certificate")
    
    if key_path.exists():
        key_path.unlink()
        deleted.append("private_key")
    
    if deleted:
        log_audit(
            db, user.id, "ssl_cert_deleted", "ssl",
            details=f"Deleted: {', '.join(deleted)}",
            ip_address=request.client.host if request.client else None
        )
        return {"success": True, "message": f"Eliminati: {', '.join(deleted)}"}
    else:
        return {"success": False, "message": "Nessun certificato da eliminare"}


# ============== Server Configuration (Port, HTTPS) ==============

CONFIG_FILE = Path(__file__).parent.parent / "server_config.json"


def load_server_config() -> dict:
    """Carica la configurazione del server"""
    default_config = {
        "port": int(os.environ.get("DAPX_PORT", 8420)),
        "ssl_enabled": os.environ.get("DAPX_SSL", "false").lower() == "true"
    }
    
    if CONFIG_FILE.exists():
        try:
            import json
            with open(CONFIG_FILE, "r") as f:
                saved_config = json.load(f)
                default_config.update(saved_config)
        except Exception:
            pass
    
    return default_config


def save_server_config(config: dict):
    """Salva la configurazione del server"""
    import json
    with open(CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


@router.get("/server/config", response_model=ServerConfigResponse)
async def get_server_config(
    user: User = Depends(get_current_user)
):
    """Ottiene la configurazione del server (porta, HTTPS)"""
    config = load_server_config()
    cert_path = CERTS_DIR / "server.crt"
    key_path = CERTS_DIR / "server.key"
    
    # Verifica se c'è una configurazione pendente (diversa da quella attuale)
    current_port = int(os.environ.get("DAPX_PORT", 8420))
    current_ssl = os.environ.get("DAPX_SSL", "false").lower() == "true"
    
    restart_required = (
        config.get("port") != current_port or
        config.get("ssl_enabled") != current_ssl
    )
    
    return ServerConfigResponse(
        port=config.get("port", 8420),
        ssl_enabled=config.get("ssl_enabled", False),
        ssl_ready=cert_path.exists() and key_path.exists(),
        cert_exists=cert_path.exists(),
        key_exists=key_path.exists(),
        restart_required=restart_required
    )


@router.put("/server/config")
async def update_server_config(
    config_update: ServerConfigUpdate,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Aggiorna la configurazione del server.
    
    ⚠️ Le modifiche richiedono un riavvio del servizio per essere applicate.
    """
    config = load_server_config()
    changes = []
    
    if config_update.port is not None:
        if config_update.port < 1 or config_update.port > 65535:
            raise HTTPException(status_code=400, detail="Porta non valida (1-65535)")
        if config_update.port != config.get("port"):
            changes.append(f"port: {config.get('port')} -> {config_update.port}")
            config["port"] = config_update.port
    
    if config_update.ssl_enabled is not None:
        # Se si vuole abilitare SSL, verifica che esistano i certificati
        if config_update.ssl_enabled:
            cert_path = CERTS_DIR / "server.crt"
            key_path = CERTS_DIR / "server.key"
            if not cert_path.exists() or not key_path.exists():
                raise HTTPException(
                    status_code=400,
                    detail="Impossibile abilitare HTTPS: certificato o chiave mancante. Genera o carica prima un certificato."
                )
        
        if config_update.ssl_enabled != config.get("ssl_enabled"):
            changes.append(f"ssl_enabled: {config.get('ssl_enabled')} -> {config_update.ssl_enabled}")
            config["ssl_enabled"] = config_update.ssl_enabled
    
    if changes:
        save_server_config(config)
        
        # Aggiorna anche il file di servizio systemd se possibile
        await update_systemd_service(config)
        
        log_audit(
            db, user.id, "server_config_updated", "server",
            details=f"Changes: {', '.join(changes)}",
            ip_address=request.client.host if request.client else None
        )
        
        return {
            "success": True,
            "message": "Configurazione salvata. Riavvia il servizio per applicare le modifiche.",
            "changes": changes,
            "restart_required": True,
            "config": config
        }
    
    return {
        "success": True,
        "message": "Nessuna modifica",
        "restart_required": False,
        "config": config
    }


async def update_systemd_service(config: dict):
    """Aggiorna il file di servizio systemd con la nuova configurazione"""
    service_file = Path("/etc/systemd/system/dapx-backandrepl.service")
    
    if not service_file.exists():
        return
    
    try:
        content = service_file.read_text()
        lines = content.split('\n')
        new_lines = []
        
        port = config.get("port", 8420)
        ssl_enabled = config.get("ssl_enabled", False)
        cert_dir = str(CERTS_DIR)
        
        # Costruisci il comando ExecStart
        if ssl_enabled:
            exec_start = f'ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port {port} --ssl-keyfile {cert_dir}/server.key --ssl-certfile {cert_dir}/server.crt'
        else:
            exec_start = f'ExecStart=/usr/bin/python3 -m uvicorn main:app --host 0.0.0.0 --port {port}'
        
        for line in lines:
            if line.strip().startswith('ExecStart='):
                new_lines.append(exec_start)
            elif line.strip().startswith('Environment="DAPX_PORT='):
                new_lines.append(f'Environment="DAPX_PORT={port}"')
            elif line.strip().startswith('Environment="DAPX_SSL='):
                new_lines.append(f'Environment="DAPX_SSL={str(ssl_enabled).lower()}"')
            else:
                new_lines.append(line)
        
        # Scrivi il file aggiornato
        service_file.write_text('\n'.join(new_lines))
        
        # Ricarica systemd
        os.system('systemctl daemon-reload')
        
    except Exception as e:
        logger.warning(f"Impossibile aggiornare servizio systemd: {e}")


@router.post("/server/restart")
async def restart_server(
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Riavvia il servizio dapx-backandrepl.
    
    ⚠️ La connessione verrà persa durante il riavvio.
    """
    log_audit(
        db, user.id, "server_restart", "server",
        details="Manual restart requested",
        ip_address=request.client.host if request.client else None
    )
    
    # Programma il riavvio in background usando subprocess.Popen (non bloccante)
    import subprocess
    import threading
    
    def delayed_restart():
        import time
        time.sleep(1)  # Attendi 1 secondo per permettere la risposta HTTP
        # Prova diversi nomi di servizio
        for service in ["dapx-backandrepl", "sanoid-manager"]:
            result = subprocess.run(["systemctl", "is-active", service], capture_output=True)
            if result.returncode == 0:
                subprocess.Popen(["systemctl", "restart", service])
                break
    
    # Esegui in un thread separato
    thread = threading.Thread(target=delayed_restart, daemon=True)
    thread.start()
    
    return {
        "success": True,
        "message": "Riavvio in corso... La pagina si ricaricherà automaticamente."
    }


class ServerConfigUpdate(BaseModel):
    port: Optional[int] = None
    ssl_enabled: Optional[bool] = None
    

class ServerConfigResponse(BaseModel):
    port: int
    ssl_enabled: bool
    ssl_ready: bool
    cert_exists: bool
    key_exists: bool
    restart_required: bool


class DatabaseResetRequest(BaseModel):
    confirm: bool = False
    backup: bool = True  # Crea backup prima del reset


@router.post("/database/reset")
async def reset_database(
    reset_request: DatabaseResetRequest,
    request: Request,
    user: User = Depends(require_admin),
    db: Session = Depends(get_db)
):
    """
    Reset completo del database - ELIMINA TUTTI I DATI
    
    ⚠️ ATTENZIONE: Questa operazione è IRREVERSIBILE!
    Elimina tutti i nodi, job, utenti, configurazioni e log.
    Il sistema tornerà allo stato iniziale come dopo l'installazione.
    
    Richiede conferma esplicita (confirm=true).
    """
    if not reset_request.confirm:
        raise HTTPException(
            status_code=400,
            detail="Reset database richiede conferma esplicita. Imposta 'confirm': true"
        )
    
    import shutil
    from pathlib import Path
    from database import DATABASE_PATH, engine, Base, init_default_config
    
    # Crea backup se richiesto
    backup_path = None
    if reset_request.backup:
        backup_dir = Path(DATABASE_PATH).parent / "backups"
        backup_dir.mkdir(exist_ok=True)
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        backup_path = backup_dir / f"database_backup_{timestamp}.db"
        
        if Path(DATABASE_PATH).exists():
            shutil.copy2(DATABASE_PATH, backup_path)
            logger.info(f"Backup database creato: {backup_path}")
    
    try:
        # Chiudi tutte le connessioni
        db.close()
        engine.dispose()
        
        # Elimina il database
        if Path(DATABASE_PATH).exists():
            Path(DATABASE_PATH).unlink()
            logger.info(f"Database eliminato: {DATABASE_PATH}")
        
        # Ricrea le tabelle
        Base.metadata.create_all(bind=engine)
        logger.info("Tabelle database ricreate")
        
        # Reinizializza configurazione di default
        new_db = SessionLocal()
        try:
            init_default_config(new_db)
            logger.info("Configurazione di default reinizializzata")
        finally:
            new_db.close()
        
        log_audit(
            db, user.id, "database_reset", "system",
            details=f"Database reset completato. Backup: {backup_path}" if backup_path else "Database reset completato (no backup)",
            ip_address=request.client.host if request.client else None
        )
        
        return {
            "success": True,
            "message": "Database resettato con successo. Il sistema è stato riportato allo stato iniziale.",
            "backup_path": str(backup_path) if backup_path else None,
            "warning": "⚠️ Riavvia il servizio per completare il reset. Dovrai ricreare l'utente amministratore."
        }
    except Exception as e:
        logger.error(f"Errore durante reset database: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Errore durante reset database: {str(e)}"
        )
