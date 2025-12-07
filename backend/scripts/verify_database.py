#!/usr/bin/env python3
"""
Script per verificare e applicare migrazioni database
Verifica che tutte le colonne e tabelle necessarie siano presenti
"""

import sqlite3
import sys
import os

# Aggiungi path backend - prova diversi percorsi
script_dir = os.path.dirname(os.path.abspath(__file__))
possible_backend_paths = [
    os.path.dirname(script_dir),  # backend/scripts -> backend
    os.path.join(os.path.dirname(script_dir), '..'),  # backend/scripts -> .. -> root
    '/opt/dapx-backandrepl/backend',
    '/opt/sanoid-manager/backend',
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))  # scripts -> backend -> root
]

for backend_path in possible_backend_paths:
    if os.path.exists(os.path.join(backend_path, 'database.py')):
        sys.path.insert(0, backend_path)
        break

try:
    from database import get_default_db_path
except ImportError:
    print("ERRORE: Impossibile importare database module")
    print("Percorsi backend provati:")
    for path in possible_backend_paths:
        print(f"  - {path}")
    sys.exit(1)

def get_db_path():
    """Ottiene il path del database"""
    # Prova diversi percorsi
    paths = []
    
    # Prova con get_default_db_path se disponibile
    try:
        default_path = get_default_db_path()
        if default_path:
            paths.append(default_path)
    except:
        pass
    
    # Aggiungi percorsi standard
    paths.extend([
        "/var/lib/dapx-backandrepl/dapx.db",
        "/opt/dapx-backandrepl/dapx.db",
        "/opt/sanoid-manager/dapx.db",
        "/opt/sanoid-manager/sanoid-manager.db",
        "/var/lib/sanoid-manager/sanoid-manager.db",
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "dapx.db"),
        os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "sanoid-manager.db")
    ])
    
    for path in paths:
        if path and os.path.exists(path):
            return path
    
    return None

def check_column_exists(conn, table, column):
    """Verifica se una colonna esiste in una tabella"""
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table})")
    columns = [row[1] for row in cursor.fetchall()]
    return column in columns

def apply_migrations():
    """Applica tutte le migrazioni necessarie"""
    db_path = get_db_path()
    
    if not db_path:
        print("ERRORE: Database non trovato")
        print("Percorsi cercati:")
        for path in [
            get_default_db_path(),
            "/var/lib/dapx-backandrepl/dapx.db",
            "/opt/sanoid-manager/dapx.db",
            "/opt/sanoid-manager/sanoid-manager.db",
            "/var/lib/sanoid-manager/sanoid-manager.db"
        ]:
            print(f"  - {path}")
        return False
    
    print(f"Database trovato: {db_path}")
    
    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()
        
        migrations_applied = []
        
        # Verifica tabella recovery_jobs
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='recovery_jobs'")
        if not cursor.fetchone():
            print("ERRORE: Tabella recovery_jobs non trovata")
            print("Esegui: python -c 'from database import Base, engine; Base.metadata.create_all(bind=engine)'")
            conn.close()
            return False
        
        # Migrazione: notify_on_each_run in recovery_jobs
        if not check_column_exists(conn, "recovery_jobs", "notify_on_each_run"):
            print("Applicazione migrazione: aggiunta colonna notify_on_each_run a recovery_jobs...")
            cursor.execute("ALTER TABLE recovery_jobs ADD COLUMN notify_on_each_run BOOLEAN DEFAULT 0")
            migrations_applied.append("notify_on_each_run")
        
        # Verifica altre colonne importanti
        important_columns = {
            "recovery_jobs": [
                "name", "source_node_id", "vm_id", "vm_type", "pbs_node_id",
                "dest_node_id", "backup_mode", "backup_compress", "schedule",
                "is_active", "current_status", "last_status", "notify_on_each_run"
            ]
        }
        
        for table, columns in important_columns.items():
            cursor.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
            if cursor.fetchone():
                for column in columns:
                    if not check_column_exists(conn, table, column):
                        print(f"ATTENZIONE: Colonna {table}.{column} mancante!")
        
        # Commit modifiche
        if migrations_applied:
            conn.commit()
            print(f"Migrazioni applicate: {', '.join(migrations_applied)}")
        else:
            print("Database già aggiornato, nessuna migrazione necessaria")
        
        # Verifica schema finale
        print("\nVerifica schema recovery_jobs:")
        cursor.execute("PRAGMA table_info(recovery_jobs)")
        columns = cursor.fetchall()
        for col in columns:
            print(f"  - {col[1]} ({col[2]})")
        
        conn.close()
        return True
        
    except sqlite3.Error as e:
        print(f"ERRORE database: {e}")
        return False
    except Exception as e:
        print(f"ERRORE: {e}")
        return False

if __name__ == "__main__":
    success = apply_migrations()
    sys.exit(0 if success else 1)

