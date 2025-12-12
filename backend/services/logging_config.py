"""
DAPX-backandrepl - Configurazione Logging Avanzato
Sistema di logging strutturato con dettagli estesi
"""

import logging
import logging.handlers
import os
import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any
import traceback
import threading
import asyncio


# ============== CONFIGURAZIONE ==============

# Livello di log (può essere sovrascritto da env)
LOG_LEVEL = os.environ.get("DAPX_LOG_LEVEL", "INFO").upper()

# Directory per i file di log
LOG_DIR = os.environ.get("DAPX_LOG_DIR", "/var/log/dapx-backandrepl")

# Dimensione massima file di log (10MB default)
LOG_MAX_BYTES = int(os.environ.get("DAPX_LOG_MAX_BYTES", 10 * 1024 * 1024))

# Numero di backup dei file di log
LOG_BACKUP_COUNT = int(os.environ.get("DAPX_LOG_BACKUP_COUNT", 5))

# Log verboso (include stack trace per ogni log)
LOG_VERBOSE = os.environ.get("DAPX_LOG_VERBOSE", "false").lower() == "true"


# ============== FORMATTATORI PERSONALIZZATI ==============

class DetailedFormatter(logging.Formatter):
    """
    Formattatore con dettagli estesi:
    - Timestamp preciso
    - Nome modulo, funzione, linea
    - Thread/Task ID
    - Contesto operazione
    """
    
    # Colori ANSI per terminale
    COLORS = {
        'DEBUG': '\033[36m',      # Cyan
        'INFO': '\033[32m',       # Verde
        'WARNING': '\033[33m',    # Giallo
        'ERROR': '\033[31m',      # Rosso
        'CRITICAL': '\033[35m',   # Magenta
        'RESET': '\033[0m',       # Reset
        'BOLD': '\033[1m',        # Bold
        'DIM': '\033[2m',         # Dim
    }
    
    def __init__(self, use_colors: bool = True, include_thread: bool = True):
        self.use_colors = use_colors and sys.stdout.isatty()
        self.include_thread = include_thread
        super().__init__()
    
    def format(self, record: logging.LogRecord) -> str:
        # Timestamp preciso con millisecondi
        timestamp = datetime.fromtimestamp(record.created).strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        
        # Livello con padding
        level = record.levelname.ljust(8)
        
        # Modulo e funzione
        module = record.name
        if len(module) > 30:
            module = '...' + module[-27:]
        module = module.ljust(30)
        
        # Funzione e linea
        func_info = f"{record.funcName}:{record.lineno}"
        func_info = func_info.ljust(25)
        
        # Thread/Task info
        thread_info = ""
        if self.include_thread:
            thread_name = threading.current_thread().name
            if thread_name == "MainThread":
                thread_name = "Main"
            elif thread_name.startswith("Thread-"):
                thread_name = f"T{thread_name[7:]}"
            
            # Prova a ottenere il nome del task asyncio
            try:
                task = asyncio.current_task()
                if task:
                    task_name = task.get_name()
                    if task_name.startswith("Task-"):
                        task_name = f"A{task_name[5:]}"
                    thread_info = f"[{thread_name}/{task_name}]"
                else:
                    thread_info = f"[{thread_name}]"
            except RuntimeError:
                thread_info = f"[{thread_name}]"
            
            thread_info = thread_info.ljust(15)
        
        # Messaggio
        message = record.getMessage()
        
        # Costruisci la linea di log
        if self.use_colors:
            color = self.COLORS.get(record.levelname, '')
            reset = self.COLORS['RESET']
            dim = self.COLORS['DIM']
            
            log_line = (
                f"{dim}{timestamp}{reset} "
                f"{color}{level}{reset} "
                f"{dim}{module}{reset} "
                f"{dim}{func_info}{reset} "
                f"{thread_info}"
                f"{message}"
            )
        else:
            log_line = (
                f"{timestamp} "
                f"{level} "
                f"{module} "
                f"{func_info} "
                f"{thread_info}"
                f"{message}"
            )
        
        # Aggiungi exception info se presente
        if record.exc_info:
            log_line += "\n" + self.formatException(record.exc_info)
        
        # Aggiungi stack info se presente
        if record.stack_info:
            log_line += "\n" + record.stack_info
        
        return log_line


class JSONFormatter(logging.Formatter):
    """
    Formattatore JSON per log strutturati (utile per sistemi di log aggregation)
    """
    
    def format(self, record: logging.LogRecord) -> str:
        log_data = {
            "timestamp": datetime.fromtimestamp(record.created).isoformat(),
            "level": record.levelname,
            "module": record.name,
            "function": record.funcName,
            "line": record.lineno,
            "thread": threading.current_thread().name,
            "message": record.getMessage(),
        }
        
        # Aggiungi task asyncio se disponibile
        try:
            task = asyncio.current_task()
            if task:
                log_data["async_task"] = task.get_name()
        except RuntimeError:
            pass
        
        # Aggiungi extra data se presente
        if hasattr(record, 'extra_data'):
            log_data["extra"] = record.extra_data
        
        # Aggiungi exception info
        if record.exc_info:
            log_data["exception"] = {
                "type": record.exc_info[0].__name__ if record.exc_info[0] else None,
                "message": str(record.exc_info[1]) if record.exc_info[1] else None,
                "traceback": traceback.format_exception(*record.exc_info)
            }
        
        return json.dumps(log_data, default=str)


# ============== CONTEXT LOGGER ==============

class ContextLogger:
    """
    Logger con supporto per contesto di operazione.
    Permette di aggiungere contesto che viene incluso in ogni log.
    """
    
    def __init__(self, logger: logging.Logger, context: Optional[Dict[str, Any]] = None):
        self._logger = logger
        self._context = context or {}
    
    def with_context(self, **kwargs) -> 'ContextLogger':
        """Crea un nuovo logger con contesto aggiuntivo"""
        new_context = {**self._context, **kwargs}
        return ContextLogger(self._logger, new_context)
    
    def _format_message(self, message: str) -> str:
        """Aggiunge il contesto al messaggio"""
        if self._context:
            ctx_str = " | ".join(f"{k}={v}" for k, v in self._context.items())
            return f"[{ctx_str}] {message}"
        return message
    
    def debug(self, message: str, *args, **kwargs):
        self._logger.debug(self._format_message(message), *args, **kwargs)
    
    def info(self, message: str, *args, **kwargs):
        self._logger.info(self._format_message(message), *args, **kwargs)
    
    def warning(self, message: str, *args, **kwargs):
        self._logger.warning(self._format_message(message), *args, **kwargs)
    
    def error(self, message: str, *args, **kwargs):
        self._logger.error(self._format_message(message), *args, **kwargs)
    
    def critical(self, message: str, *args, **kwargs):
        self._logger.critical(self._format_message(message), *args, **kwargs)
    
    def exception(self, message: str, *args, **kwargs):
        self._logger.exception(self._format_message(message), *args, **kwargs)


# ============== OPERATION LOGGER ==============

class OperationLogger:
    """
    Logger per operazioni lunghe con tracciamento fasi.
    Esempio:
        with OperationLogger("migration", vm_id=100) as op:
            op.phase("backup")
            op.info("Creazione backup...")
            op.phase("transfer")
            op.info("Trasferimento...")
    """
    
    def __init__(self, operation_name: str, logger: Optional[logging.Logger] = None, **context):
        self.operation_name = operation_name
        self.context = context
        self.current_phase = "init"
        self.start_time = None
        self.phase_start_time = None
        self._logger = logger or logging.getLogger(f"operations.{operation_name}")
        self.phases_completed = []
    
    def __enter__(self):
        self.start_time = datetime.now()
        self.phase_start_time = self.start_time
        self._log("INFO", f"{'='*20} INIZIO OPERAZIONE: {self.operation_name.upper()} {'='*20}")
        if self.context:
            ctx_str = ", ".join(f"{k}={v}" for k, v in self.context.items())
            self._log("INFO", f"Contesto: {ctx_str}")
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration = (datetime.now() - self.start_time).total_seconds()
        if exc_type:
            self._log("ERROR", f"OPERAZIONE FALLITA: {exc_type.__name__}: {exc_val}")
            self._log("ERROR", f"{'='*20} FINE OPERAZIONE: {self.operation_name.upper()} (ERRORE, {duration:.2f}s) {'='*20}")
        else:
            self._log("INFO", f"{'='*20} FINE OPERAZIONE: {self.operation_name.upper()} (OK, {duration:.2f}s) {'='*20}")
        return False  # Non sopprimere eccezioni
    
    def phase(self, phase_name: str):
        """Inizia una nuova fase dell'operazione"""
        if self.phase_start_time and self.current_phase != "init":
            phase_duration = (datetime.now() - self.phase_start_time).total_seconds()
            self.phases_completed.append((self.current_phase, phase_duration))
            self._log("INFO", f"Fase '{self.current_phase}' completata in {phase_duration:.2f}s")
        
        self.current_phase = phase_name
        self.phase_start_time = datetime.now()
        self._log("INFO", f">>> FASE: {phase_name.upper()}")
    
    def _log(self, level: str, message: str):
        """Log interno con prefisso operazione"""
        prefix = f"[{self.operation_name.upper()}]"
        if self.current_phase and self.current_phase != "init":
            prefix += f"[{self.current_phase}]"
        
        full_message = f"{prefix} {message}"
        getattr(self._logger, level.lower())(full_message)
    
    def debug(self, message: str):
        self._log("DEBUG", message)
    
    def info(self, message: str):
        self._log("INFO", message)
    
    def warning(self, message: str):
        self._log("WARNING", message)
    
    def error(self, message: str):
        self._log("ERROR", message)
    
    def success(self, message: str):
        self._log("INFO", f"✓ {message}")
    
    def fail(self, message: str):
        self._log("ERROR", f"✗ {message}")


# ============== SETUP FUNZIONI ==============

def setup_logging(
    level: str = None,
    log_dir: str = None,
    console_output: bool = True,
    file_output: bool = True,
    json_output: bool = False,
    verbose: bool = None
):
    """
    Configura il sistema di logging.
    
    Args:
        level: Livello di log (DEBUG, INFO, WARNING, ERROR, CRITICAL)
        log_dir: Directory per i file di log
        console_output: Abilita output su console
        file_output: Abilita output su file
        json_output: Usa formato JSON invece di testo
        verbose: Abilita logging verboso (include più dettagli)
    """
    level = level or LOG_LEVEL
    log_dir = log_dir or LOG_DIR
    verbose = verbose if verbose is not None else LOG_VERBOSE
    
    # Crea directory log se necessario
    if file_output and log_dir:
        os.makedirs(log_dir, exist_ok=True)
    
    # Configura root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level, logging.INFO))
    
    # Rimuovi handler esistenti
    root_logger.handlers.clear()
    
    # Handler console
    if console_output:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, level, logging.INFO))
        
        if json_output:
            console_handler.setFormatter(JSONFormatter())
        else:
            console_handler.setFormatter(DetailedFormatter(use_colors=True, include_thread=True))
        
        root_logger.addHandler(console_handler)
    
    # Handler file (rotazione automatica)
    if file_output and log_dir:
        # File principale
        main_log_file = os.path.join(log_dir, "dapx.log")
        file_handler = logging.handlers.RotatingFileHandler(
            main_log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        file_handler.setLevel(getattr(logging, level, logging.INFO))
        file_handler.setFormatter(DetailedFormatter(use_colors=False, include_thread=True))
        root_logger.addHandler(file_handler)
        
        # File errori separato
        error_log_file = os.path.join(log_dir, "dapx-errors.log")
        error_handler = logging.handlers.RotatingFileHandler(
            error_log_file,
            maxBytes=LOG_MAX_BYTES,
            backupCount=LOG_BACKUP_COUNT,
            encoding='utf-8'
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(DetailedFormatter(use_colors=False, include_thread=True))
        root_logger.addHandler(error_handler)
        
        # File JSON per analisi (opzionale)
        if json_output:
            json_log_file = os.path.join(log_dir, "dapx.json.log")
            json_handler = logging.handlers.RotatingFileHandler(
                json_log_file,
                maxBytes=LOG_MAX_BYTES,
                backupCount=LOG_BACKUP_COUNT,
                encoding='utf-8'
            )
            json_handler.setLevel(getattr(logging, level, logging.INFO))
            json_handler.setFormatter(JSONFormatter())
            root_logger.addHandler(json_handler)
    
    # Configura livelli per moduli specifici
    # Riduci verbosità di alcuni moduli esterni
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)
    
    # Log iniziale
    logger = logging.getLogger(__name__)
    logger.info(f"Sistema di logging inizializzato")
    logger.info(f"Livello: {level}")
    if file_output and log_dir:
        logger.info(f"Directory log: {log_dir}")
    logger.info(f"Console: {console_output}, File: {file_output}, JSON: {json_output}")


def get_logger(name: str) -> logging.Logger:
    """
    Ottiene un logger configurato per un modulo.
    Usa questa funzione invece di logging.getLogger() direttamente.
    """
    return logging.getLogger(name)


def get_context_logger(name: str, **context) -> ContextLogger:
    """
    Ottiene un ContextLogger con contesto iniziale.
    
    Esempio:
        logger = get_context_logger("migration", vm_id=100, src="node1")
        logger.info("Inizio migrazione")  # Output: [vm_id=100 | src=node1] Inizio migrazione
    """
    return ContextLogger(logging.getLogger(name), context)


def get_operation_logger(operation: str, **context) -> OperationLogger:
    """
    Crea un OperationLogger per tracciare un'operazione lunga.
    
    Esempio:
        with get_operation_logger("migration", vm_id=100) as op:
            op.phase("backup")
            op.info("Creazione backup...")
    """
    return OperationLogger(operation, **context)


# ============== DECORATORE PER LOGGING AUTOMATICO ==============

def log_function_call(logger: logging.Logger = None):
    """
    Decoratore per loggare automaticamente chiamate a funzioni.
    
    Esempio:
        @log_function_call()
        async def my_function(arg1, arg2):
            ...
    """
    def decorator(func):
        nonlocal logger
        if logger is None:
            logger = logging.getLogger(func.__module__)
        
        if asyncio.iscoroutinefunction(func):
            async def async_wrapper(*args, **kwargs):
                func_name = func.__name__
                args_str = ", ".join([repr(a)[:50] for a in args[:3]])
                if len(args) > 3:
                    args_str += ", ..."
                kwargs_str = ", ".join([f"{k}={repr(v)[:30]}" for k, v in list(kwargs.items())[:3]])
                if len(kwargs) > 3:
                    kwargs_str += ", ..."
                
                logger.debug(f">>> {func_name}({args_str}{', ' + kwargs_str if kwargs_str else ''})")
                start = datetime.now()
                try:
                    result = await func(*args, **kwargs)
                    duration = (datetime.now() - start).total_seconds()
                    logger.debug(f"<<< {func_name} completato in {duration:.3f}s")
                    return result
                except Exception as e:
                    duration = (datetime.now() - start).total_seconds()
                    logger.error(f"<<< {func_name} FALLITO dopo {duration:.3f}s: {type(e).__name__}: {e}")
                    raise
            return async_wrapper
        else:
            def sync_wrapper(*args, **kwargs):
                func_name = func.__name__
                args_str = ", ".join([repr(a)[:50] for a in args[:3]])
                kwargs_str = ", ".join([f"{k}={repr(v)[:30]}" for k, v in list(kwargs.items())[:3]])
                
                logger.debug(f">>> {func_name}({args_str}{', ' + kwargs_str if kwargs_str else ''})")
                start = datetime.now()
                try:
                    result = func(*args, **kwargs)
                    duration = (datetime.now() - start).total_seconds()
                    logger.debug(f"<<< {func_name} completato in {duration:.3f}s")
                    return result
                except Exception as e:
                    duration = (datetime.now() - start).total_seconds()
                    logger.error(f"<<< {func_name} FALLITO dopo {duration:.3f}s: {type(e).__name__}: {e}")
                    raise
            return sync_wrapper
    return decorator
