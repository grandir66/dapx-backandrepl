"""
Database models per DAPX-backandrepl
Con supporto autenticazione integrata Proxmox
"""

from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey, JSON, Enum
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import enum

def get_default_db_path():
    """Determina il path del database in base al sistema operativo"""
    import platform
    
    # Se specificato via env var, usa quello
    if os.environ.get("DAPX_DB"):
        return os.environ.get("DAPX_DB")
    
    system = platform.system()
    
    if system == "Darwin":  # macOS
        base_dir = os.path.expanduser("~/.dapx-backandrepl")
    elif system == "Linux":
        # Prova /var/lib se abbiamo permessi, altrimenti home
        if os.access("/var/lib", os.W_OK):
            base_dir = "/var/lib/dapx-backandrepl"
        else:
            base_dir = os.path.expanduser("~/.dapx-backandrepl")
    else:
        # Windows o altro
        base_dir = os.path.expanduser("~/.dapx-backandrepl")
    
    return os.path.join(base_dir, "dapx.db")

DATABASE_PATH = get_default_db_path()
os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)

SQLALCHEMY_DATABASE_URL = f"sqlite:///{DATABASE_PATH}"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL, 
    connect_args={"check_same_thread": False}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ============== ENUMS ==============

class AuthMethod(str, enum.Enum):
    """Metodi di autenticazione supportati"""
    LOCAL = "local"
    PROXMOX = "proxmox"
    LDAP = "ldap"


class UserRole(str, enum.Enum):
    """Ruoli utente"""
    ADMIN = "admin"
    OPERATOR = "operator"
    VIEWER = "viewer"


class NodeType(str, enum.Enum):
    """Tipi di nodo supportati"""
    PVE = "pve"  # Proxmox VE (hypervisor)
    PBS = "pbs"  # Proxmox Backup Server


class StorageType(str, enum.Enum):
    """Tipi di storage supportati per la replica"""
    ZFS = "zfs"
    BTRFS = "btrfs"


class SyncMethod(str, enum.Enum):
    """Metodi di sincronizzazione"""
    SYNCOID = "syncoid"  # ZFS con syncoid
    BTRFS_SEND = "btrfs_send"  # BTRFS con btrfs send/receive
    PBS_RESTORE = "pbs_restore"  # Replica tramite backup PBS


class RecoveryJobStatus(str, enum.Enum):
    """Stati del recovery job"""
    PENDING = "pending"
    BACKING_UP = "backing_up"
    RESTORING = "restoring"
    REGISTERING = "registering"
    COMPLETED = "completed"
    FAILED = "failed"


# ============== AUTH MODELS ==============

class User(Base):
    """Utente del sistema"""
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(100), unique=True, index=True, nullable=False)
    email = Column(String(255), unique=True, index=True, nullable=True)
    password_hash = Column(String(255), nullable=True)  # Null per auth Proxmox
    full_name = Column(String(255), nullable=True)
    
    # Autenticazione
    auth_method = Column(String(20), default=AuthMethod.LOCAL.value)
    proxmox_userid = Column(String(100), nullable=True)  # es: root@pam
    proxmox_realm = Column(String(50), nullable=True)  # es: pam, pve, ldap
    
    # Ruolo e permessi
    role = Column(String(20), default=UserRole.VIEWER.value)
    is_active = Column(Boolean, default=True)
    must_change_password = Column(Boolean, default=False)
    
    # Restrizioni nodi (JSON array di node_id, null = tutti)
    allowed_nodes = Column(JSON, nullable=True)
    
    # Timestamps
    last_login = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    
    # Relationships
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    audit_logs = relationship("AuditLog", back_populates="user")


class UserSession(Base):
    """Sessioni utente attive"""
    __tablename__ = "user_sessions"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    token_hash = Column(String(255), nullable=False)  # Hash del token per revoca
    refresh_token_hash = Column(String(255), nullable=True)
    
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    # Per auth Proxmox
    proxmox_ticket = Column(Text, nullable=True)
    proxmox_csrf = Column(String(255), nullable=True)
    
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False)
    last_activity = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="sessions")


class AuditLog(Base):
    """Log di audit per tracciare le azioni"""
    __tablename__ = "audit_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    action = Column(String(100), nullable=False)  # login, logout, create_job, etc.
    resource_type = Column(String(50), nullable=True)  # node, job, user, etc.
    resource_id = Column(Integer, nullable=True)
    
    details = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)
    user_agent = Column(String(500), nullable=True)
    
    status = Column(String(20), default="success")  # success, failed
    created_at = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    user = relationship("User", back_populates="audit_logs")


# ============== CONFIG MODELS ==============

class SystemConfig(Base):
    """Configurazione di sistema"""
    __tablename__ = "system_config"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    value_type = Column(String(20), default="string")  # string, int, bool, json
    category = Column(String(50), default="general")
    description = Column(String(500), nullable=True)
    is_secret = Column(Boolean, default=False)  # Se true, non mostrare in API
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationConfig(Base):
    """Configurazione notifiche"""
    __tablename__ = "notification_config"
    
    id = Column(Integer, primary_key=True, index=True)
    
    # Email SMTP
    smtp_enabled = Column(Boolean, default=False)
    smtp_host = Column(String(255), nullable=True)
    smtp_port = Column(Integer, default=587)
    smtp_user = Column(String(255), nullable=True)
    smtp_password = Column(String(255), nullable=True)  # Encrypted
    smtp_from = Column(String(255), nullable=True)
    smtp_to = Column(String(500), nullable=True)  # Destinatari (separati da virgola)
    smtp_subject_prefix = Column(String(100), default="[DAPX]")  # Prefisso soggetto
    smtp_tls = Column(Boolean, default=True)
    
    # Webhook
    webhook_enabled = Column(Boolean, default=False)
    webhook_url = Column(String(500), nullable=True)
    webhook_secret = Column(String(255), nullable=True)
    
    # Telegram
    telegram_enabled = Column(Boolean, default=False)
    telegram_bot_token = Column(String(255), nullable=True)
    telegram_chat_id = Column(String(100), nullable=True)
    
    # Notifiche abilitate
    notify_on_success = Column(Boolean, default=False)
    notify_on_failure = Column(Boolean, default=True)
    notify_on_warning = Column(Boolean, default=True)
    
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


# ============== NODE MODELS ==============

class Node(Base):
    """Nodo Proxmox gestito (PVE o PBS)"""
    __tablename__ = "nodes"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, index=True)
    hostname = Column(String(255), nullable=False)
    ssh_port = Column(Integer, default=22)
    ssh_user = Column(String(100), default="root")
    ssh_key_path = Column(String(500), default="/root/.ssh/id_rsa")
    
    # Tipo di nodo: pve (Proxmox VE) o pbs (Proxmox Backup Server)
    node_type = Column(String(20), default=NodeType.PVE.value)
    
    # API Proxmox (per autenticazione integrata)
    proxmox_api_url = Column(String(500), nullable=True)  # https://host:8006/api2/json
    proxmox_api_token = Column(String(500), nullable=True)  # user@pam!tokenid=secret
    proxmox_verify_ssl = Column(Boolean, default=False)
    is_auth_node = Column(Boolean, default=False)  # Nodo usato per autenticazione
    
    # PBS Specific (quando node_type == 'pbs')
    pbs_datastore = Column(String(100), nullable=True)  # Nome datastore PBS
    pbs_fingerprint = Column(String(255), nullable=True)  # Fingerprint SSL PBS
    pbs_password = Column(String(500), nullable=True)  # Password API PBS (encrypted)
    
    # Storage type support (per PVE)
    storage_type = Column(String(20), default=StorageType.ZFS.value)  # zfs, btrfs
    
    # BTRFS specific configuration
    btrfs_mount = Column(String(500), nullable=True)  # es: /mnt/btrfs-storage
    btrfs_snapshot_dir = Column(String(500), nullable=True)  # es: /mnt/btrfs-storage/.snapshots
    btrfs_available = Column(Boolean, default=False)
    btrfs_version = Column(String(50), nullable=True)
    
    is_active = Column(Boolean, default=True)
    is_online = Column(Boolean, default=False)
    last_check = Column(DateTime, nullable=True)
    sanoid_installed = Column(Boolean, default=False)
    sanoid_version = Column(String(50), nullable=True)
    
    # PBS specific status
    pbs_version = Column(String(50), nullable=True)
    pbs_available = Column(Boolean, default=False)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    notes = Column(Text, nullable=True)
    
    # Relationships
    datasets = relationship("Dataset", back_populates="node", cascade="all, delete-orphan")
    sync_jobs_source = relationship("SyncJob", foreign_keys="SyncJob.source_node_id", back_populates="source_node")
    sync_jobs_dest = relationship("SyncJob", foreign_keys="SyncJob.dest_node_id", back_populates="dest_node")
    recovery_jobs_source = relationship("RecoveryJob", foreign_keys="RecoveryJob.source_node_id", back_populates="source_node")
    recovery_jobs_pbs = relationship("RecoveryJob", foreign_keys="RecoveryJob.pbs_node_id", back_populates="pbs_node")
    recovery_jobs_dest = relationship("RecoveryJob", foreign_keys="RecoveryJob.dest_node_id", back_populates="dest_node")


class Dataset(Base):
    """Dataset ZFS su un nodo"""
    __tablename__ = "datasets"
    
    id = Column(Integer, primary_key=True, index=True)
    node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    name = Column(String(500), nullable=False)  # es: rpool/data/vm-100-disk-0
    mountpoint = Column(String(500), nullable=True)
    used = Column(String(50), nullable=True)
    available = Column(String(50), nullable=True)
    snapshot_count = Column(Integer, default=0)
    
    # Sanoid configuration
    sanoid_enabled = Column(Boolean, default=False)
    sanoid_template = Column(String(100), default="default")
    hourly = Column(Integer, default=24)
    daily = Column(Integer, default=30)
    weekly = Column(Integer, default=4)
    monthly = Column(Integer, default=12)
    yearly = Column(Integer, default=0)
    autosnap = Column(Boolean, default=True)
    autoprune = Column(Boolean, default=True)
    
    last_snapshot = Column(DateTime, nullable=True)
    last_updated = Column(DateTime, default=datetime.utcnow)
    
    # Relationships
    node = relationship("Node", back_populates="datasets")


# ============== SYNC JOB MODELS ==============

class SyncJob(Base):
    """Job di sincronizzazione Syncoid/BTRFS"""
    __tablename__ = "sync_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    
    # Sync method: syncoid (ZFS) or btrfs_send (BTRFS)
    sync_method = Column(String(20), default=SyncMethod.SYNCOID.value)
    
    source_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    source_dataset = Column(String(500), nullable=False)
    
    dest_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    dest_dataset = Column(String(500), nullable=False)
    
    # Opzioni Syncoid (ZFS)
    recursive = Column(Boolean, default=False)
    compress = Column(String(20), default="lz4")  # none, gzip, lz4, zstd
    mbuffer_size = Column(String(20), default="128M")
    no_sync_snap = Column(Boolean, default=False)
    force_delete = Column(Boolean, default=False)
    extra_args = Column(String(500), nullable=True)
    
    # Opzioni BTRFS
    btrfs_snapshot_dir = Column(String(500), nullable=True)  # Directory snapshot sorgente
    btrfs_dest_snapshot_dir = Column(String(500), nullable=True)  # Directory snapshot destinazione
    btrfs_max_snapshots = Column(Integer, default=5)  # Numero max snapshot da mantenere
    btrfs_full_sync = Column(Boolean, default=False)  # Forza sync completo invece di incrementale
    
    # Scheduling (cron format)
    schedule = Column(String(100), nullable=True)  # es: "0 */4 * * *" ogni 4 ore
    is_active = Column(Boolean, default=True)
    
    # VM Registration
    register_vm = Column(Boolean, default=False)
    vm_id = Column(Integer, nullable=True)  # VMID Proxmox sorgente
    dest_vm_id = Column(Integer, nullable=True)  # VMID Proxmox destinazione (se diverso)
    vm_type = Column(String(10), nullable=True)  # qemu o lxc
    vm_name = Column(String(100), nullable=True)
    
    # Grouping - per raggruppare job multipli di una stessa VM
    vm_group_id = Column(String(50), nullable=True)  # UUID gruppo (tutti i dischi di una VM)
    disk_name = Column(String(50), nullable=True)  # Nome disco (es: scsi0, virtio0)
    
    # Storage mapping per registrazione VM
    source_storage = Column(String(100), nullable=True)  # Storage Proxmox sorgente (es: local-zfs)
    dest_storage = Column(String(100), nullable=True)  # Storage Proxmox destinazione (es: replica-zfs)
    
    # Retry policy
    retry_on_failure = Column(Boolean, default=True)
    max_retries = Column(Integer, default=3)
    retry_delay_minutes = Column(Integer, default=15)
    
    # Stats
    last_run = Column(DateTime, nullable=True)
    last_status = Column(String(50), nullable=True)  # success, failed, running
    last_duration = Column(Integer, nullable=True)  # secondi
    last_transferred = Column(String(50), nullable=True)  # es: "1.5G"
    last_sync_type = Column(String(20), nullable=True)  # full, incremental (per BTRFS)
    run_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    consecutive_failures = Column(Integer, default=0)
    
    created_at = Column(DateTime, default=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Relationships
    source_node = relationship("Node", foreign_keys=[source_node_id], back_populates="sync_jobs_source")
    dest_node = relationship("Node", foreign_keys=[dest_node_id], back_populates="sync_jobs_dest")


class RecoveryJob(Base):
    """
    Job di recovery automatica basata su PBS (Proxmox Backup Server).
    Permette di replicare VM anche con filesystem non supportati (LVM, local, etc.)
    attraverso il ciclo: backup su PBS -> restore su nodo destinazione -> registrazione
    """
    __tablename__ = "recovery_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(200), nullable=False)
    
    # VM sorgente
    source_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    vm_id = Column(Integer, nullable=False)  # VMID sorgente
    vm_type = Column(String(10), default="qemu")  # qemu, lxc
    vm_name = Column(String(100), nullable=True)
    
    # PBS (intermediario)
    pbs_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    pbs_datastore = Column(String(100), nullable=True)  # Override datastore del nodo
    pbs_storage_id = Column(String(100), nullable=True)  # Nome storage PBS configurato su nodo sorgente (es: pbs-backup)
    
    # Nodo destinazione
    dest_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    dest_vm_id = Column(Integer, nullable=True)  # VMID destinazione (null = stesso del sorgente)
    dest_vm_name_suffix = Column(String(50), nullable=True)  # Suffisso nome VM (es: "-replica", "-dr")
    dest_storage = Column(String(100), nullable=True)  # Storage target per restore (es: local-lvm, local-zfs)
    
    # Opzioni backup
    backup_mode = Column(String(20), default="snapshot")  # snapshot, stop, suspend
    backup_compress = Column(String(20), default="zstd")  # none, lzo, gzip, zstd
    include_all_disks = Column(Boolean, default=True)  # Include tutti i dischi
    
    # Opzioni restore
    restore_start_vm = Column(Boolean, default=False)  # Avvia VM dopo restore
    restore_unique = Column(Boolean, default=True)  # Genera nuovi UUID per dischi
    overwrite_existing = Column(Boolean, default=True)  # Sovrascrive se esiste
    
    # Scheduling
    schedule = Column(String(100), nullable=True)  # Cron format
    backup_schedule = Column(String(100), nullable=True)  # Schedule separato per backup (null = stesso di restore)
    is_active = Column(Boolean, default=True)
    
    # Stato corrente
    current_status = Column(String(20), default=RecoveryJobStatus.PENDING.value)
    last_backup_time = Column(DateTime, nullable=True)
    last_backup_id = Column(String(100), nullable=True)  # ID backup PBS
    last_restore_time = Column(DateTime, nullable=True)
    
    # Stats
    last_run = Column(DateTime, nullable=True)
    last_status = Column(String(50), nullable=True)  # success, failed
    last_duration = Column(Integer, nullable=True)  # secondi
    last_error = Column(Text, nullable=True)
    run_count = Column(Integer, default=0)
    error_count = Column(Integer, default=0)
    consecutive_failures = Column(Integer, default=0)
    
    # Retry policy
    retry_on_failure = Column(Boolean, default=True)
    max_retries = Column(Integer, default=3)
    retry_delay_minutes = Column(Integer, default=15)
    
    # Notifiche
    notify_on_each_run = Column(Boolean, default=False)  # True = notifica ogni esecuzione, False = solo report giornaliero
    
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    created_by = Column(Integer, ForeignKey("users.id"), nullable=True)
    
    # Relationships
    source_node = relationship("Node", foreign_keys=[source_node_id], back_populates="recovery_jobs_source")
    pbs_node = relationship("Node", foreign_keys=[pbs_node_id], back_populates="recovery_jobs_pbs")
    dest_node = relationship("Node", foreign_keys=[dest_node_id], back_populates="recovery_jobs_dest")


class JobLog(Base):
    """Log delle esecuzioni"""
    __tablename__ = "job_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    job_type = Column(String(50), nullable=False)  # sync, snapshot, register, recovery, backup, restore
    job_id = Column(Integer, nullable=True)  # ID del SyncJob/RecoveryJob se applicabile
    node_name = Column(String(100), nullable=True)
    dataset = Column(String(500), nullable=True)
    
    status = Column(String(50), nullable=False)  # started, success, failed
    message = Column(Text, nullable=True)
    output = Column(Text, nullable=True)
    error = Column(Text, nullable=True)
    
    duration = Column(Integer, nullable=True)  # secondi
    transferred = Column(String(50), nullable=True)
    
    # PBS specific
    backup_id = Column(String(100), nullable=True)  # ID backup PBS
    
    # Retry info
    attempt_number = Column(Integer, default=1)
    
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)
    
    triggered_by = Column(Integer, ForeignKey("users.id"), nullable=True)


class Settings(Base):
    """Impostazioni globali (legacy, usare SystemConfig)"""
    __tablename__ = "settings"
    
    id = Column(Integer, primary_key=True, index=True)
    key = Column(String(100), unique=True, nullable=False)
    value = Column(Text, nullable=True)
    description = Column(String(500), nullable=True)


class VMRegistry(Base):
    """Registro VM replicate"""
    __tablename__ = "vm_registry"
    
    id = Column(Integer, primary_key=True, index=True)
    vm_id = Column(Integer, nullable=False)
    vm_type = Column(String(10), nullable=False)  # qemu, lxc
    vm_name = Column(String(100), nullable=True)
    
    source_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    source_dataset = Column(String(500), nullable=False)
    
    dest_node_id = Column(Integer, ForeignKey("nodes.id"), nullable=False)
    dest_dataset = Column(String(500), nullable=False)
    
    config_backup = Column(Text, nullable=True)  # Backup del file .conf
    is_registered = Column(Boolean, default=False)
    registered_vmid = Column(Integer, nullable=True)  # VMID sul nodo destinazione
    
    last_sync = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============== API KEY MODELS ==============

class APIKey(Base):
    """API Keys per accesso programmatico"""
    __tablename__ = "api_keys"
    
    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    
    name = Column(String(100), nullable=False)
    key_hash = Column(String(255), nullable=False)  # Hash della key
    key_prefix = Column(String(10), nullable=False)  # Primi caratteri per identificazione
    
    # Permessi
    permissions = Column(JSON, nullable=True)  # Lista di permessi specifici
    allowed_ips = Column(JSON, nullable=True)  # Lista IP consentiti
    
    is_active = Column(Boolean, default=True)
    expires_at = Column(DateTime, nullable=True)
    
    last_used = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


# ============== HELPER FUNCTIONS ==============

def init_default_config(db_session):
    """Inizializza configurazione di default se non esiste"""
    
    defaults = [
        # Autenticazione
        ("auth_method", "proxmox", "string", "auth", "Metodo autenticazione: local, proxmox"),
        ("auth_proxmox_node", "", "string", "auth", "Nodo Proxmox per autenticazione"),
        ("auth_proxmox_port", "8006", "int", "auth", "Porta API Proxmox"),
        ("auth_proxmox_verify_ssl", "false", "bool", "auth", "Verifica SSL Proxmox"),
        ("auth_session_timeout", "480", "int", "auth", "Timeout sessione in minuti"),
        ("auth_allow_local_fallback", "true", "bool", "auth", "Permetti login locale se Proxmox non disponibile"),
        
        # Syncoid defaults (ZFS)
        ("syncoid_default_compress", "lz4", "string", "syncoid", "Compressione default"),
        ("syncoid_default_mbuffer", "128M", "string", "syncoid", "Buffer size default"),
        ("syncoid_timeout", "3600", "int", "syncoid", "Timeout sync in secondi"),
        
        # BTRFS defaults
        ("btrfs_default_mount", "/mnt/btrfs-storage", "string", "btrfs", "Mount point BTRFS default"),
        ("btrfs_default_snapshot_dir", ".snapshots", "string", "btrfs", "Subdirectory snapshot (relativa al mount)"),
        ("btrfs_max_snapshots", "5", "int", "btrfs", "Numero massimo snapshot da mantenere"),
        ("btrfs_sync_timeout", "3600", "int", "btrfs", "Timeout sync BTRFS in secondi"),
        
        # PBS defaults
        ("pbs_default_datastore", "datastore1", "string", "pbs", "Datastore PBS default"),
        ("pbs_backup_mode", "snapshot", "string", "pbs", "Modalità backup: snapshot, stop, suspend"),
        ("pbs_backup_compress", "zstd", "string", "pbs", "Compressione backup: none, lzo, gzip, zstd"),
        ("pbs_restore_timeout", "7200", "int", "pbs", "Timeout restore in secondi"),
        ("pbs_backup_timeout", "7200", "int", "pbs", "Timeout backup in secondi"),
        
        # Retention
        ("log_retention_days", "30", "int", "retention", "Giorni retention log"),
        ("audit_retention_days", "90", "int", "retention", "Giorni retention audit log"),
        
        # Notifiche
        ("daily_summary_hour", "8", "int", "notifications", "Ora invio riepilogo giornaliero (0-23, UTC)"),
        ("daily_summary_enabled", "true", "bool", "notifications", "Abilita riepilogo giornaliero"),
        
        # UI
        ("ui_theme", "dark", "string", "ui", "Tema interfaccia"),
        ("ui_refresh_interval", "30", "int", "ui", "Intervallo refresh in secondi"),
    ]
    
    for key, value, value_type, category, description in defaults:
        existing = db_session.query(SystemConfig).filter(SystemConfig.key == key).first()
        if not existing:
            config = SystemConfig(
                key=key,
                value=value,
                value_type=value_type,
                category=category,
                description=description
            )
            db_session.add(config)
    
    # Inizializza NotificationConfig se non esiste
    if not db_session.query(NotificationConfig).first():
        db_session.add(NotificationConfig())
    
    db_session.commit()


def get_config_value(db_session, key: str, default=None):
    """Ottiene un valore di configurazione"""
    config = db_session.query(SystemConfig).filter(SystemConfig.key == key).first()
    if not config:
        return default
    
    value = config.value
    if config.value_type == "int":
        return int(value) if value else default
    elif config.value_type == "bool":
        return value.lower() in ("true", "1", "yes") if value else default
    elif config.value_type == "json":
        import json
        return json.loads(value) if value else default
    return value


def set_config_value(db_session, key: str, value, value_type: str = "string"):
    """Imposta un valore di configurazione"""
    config = db_session.query(SystemConfig).filter(SystemConfig.key == key).first()
    
    if value_type == "bool":
        value = "true" if value else "false"
    elif value_type == "json":
        import json
        value = json.dumps(value)
    else:
        value = str(value)
    
    if config:
        config.value = value
        config.value_type = value_type
    else:
        config = SystemConfig(key=key, value=value, value_type=value_type)
        db_session.add(config)
    
    db_session.commit()
