"""
Servizio per gestire la configurazione di Sanoid sui nodi.
Permette di configurare snapshot e retention per dataset specifici.
"""

import logging
from typing import Dict, Optional, List
from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)


class SanoidConfigService:
    """Gestisce la configurazione di Sanoid sui nodi remoti"""
    
    SANOID_CONF_PATH = "/etc/sanoid/sanoid.conf"
    
    def _build_dataset_config(
        self,
        dataset: str,
        autosnap: bool = True,
        autoprune: bool = True,
        hourly: int = 0,
        daily: int = 7,
        weekly: int = 4,
        monthly: int = 3,
        yearly: int = 0
    ) -> str:
        """Costruisce la configurazione sanoid per un dataset"""
        config = f"""
[{dataset}]
    use_template = production
    autosnap = {"yes" if autosnap else "no"}
    autoprune = {"yes" if autoprune else "no"}
    hourly = {hourly}
    daily = {daily}
    weekly = {weekly}
    monthly = {monthly}
    yearly = {yearly}
"""
        return config
    
    async def get_config(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> str:
        """Legge la configurazione sanoid corrente da un nodo"""
        result = await ssh_service.execute(
            hostname=hostname,
            command=f"cat {self.SANOID_CONF_PATH} 2>/dev/null || echo ''",
            port=port,
            username=username,
            key_path=key_path,
            timeout=30
        )
        return result.stdout if result.success else ""
    
    async def add_dataset_config(
        self,
        hostname: str,
        dataset: str,
        autosnap: bool = True,
        autoprune: bool = True,
        keep_snapshots: int = 7,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> tuple[bool, str]:
        """
        Aggiunge o aggiorna la configurazione per un dataset.
        
        Args:
            hostname: Nodo su cui configurare
            dataset: Dataset ZFS da configurare
            autosnap: Se True, sanoid crea snapshot automaticamente
            autoprune: Se True, sanoid elimina snapshot vecchie
            keep_snapshots: Numero di snapshot da mantenere (convertito in daily)
        """
        try:
            # Leggi configurazione attuale
            current_config = await self.get_config(hostname, port, username, key_path)
            
            # Verifica se il dataset è già configurato
            if f"[{dataset}]" in current_config:
                # Rimuovi la vecchia configurazione per questo dataset
                lines = current_config.split('\n')
                new_lines = []
                skip = False
                for line in lines:
                    if line.strip().startswith(f"[{dataset}]"):
                        skip = True
                        continue
                    elif line.strip().startswith("[") and skip:
                        skip = False
                    if not skip:
                        new_lines.append(line)
                current_config = '\n'.join(new_lines)
            
            # Costruisci nuova configurazione per il dataset
            # Converti keep_snapshots in policy sanoid
            daily = min(keep_snapshots, 30)  # Max 30 daily
            weekly = max(0, (keep_snapshots - 30) // 7)  # Extra as weekly
            
            new_config = self._build_dataset_config(
                dataset=dataset,
                autosnap=autosnap,
                autoprune=autoprune,
                hourly=0,
                daily=daily,
                weekly=min(weekly, 4),
                monthly=0,
                yearly=0
            )
            
            # Combina configurazioni
            final_config = current_config.rstrip() + "\n" + new_config
            
            # Scrivi configurazione
            # Escape per bash
            escaped_config = final_config.replace("'", "'\\''")
            write_cmd = f"echo '{escaped_config}' > {self.SANOID_CONF_PATH}"
            
            result = await ssh_service.execute(
                hostname=hostname,
                command=write_cmd,
                port=port,
                username=username,
                key_path=key_path,
                timeout=30
            )
            
            if result.success:
                logger.info(f"Configurazione sanoid aggiornata per {dataset} su {hostname}")
                return True, f"Dataset {dataset} configurato con retention {keep_snapshots}"
            else:
                return False, f"Errore scrittura config: {result.stderr}"
                
        except Exception as e:
            logger.error(f"Errore configurazione sanoid: {e}")
            return False, str(e)
    
    async def remove_dataset_config(
        self,
        hostname: str,
        dataset: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> tuple[bool, str]:
        """Rimuove la configurazione per un dataset"""
        try:
            current_config = await self.get_config(hostname, port, username, key_path)
            
            if f"[{dataset}]" not in current_config:
                return True, "Dataset non configurato"
            
            # Rimuovi la sezione del dataset
            lines = current_config.split('\n')
            new_lines = []
            skip = False
            for line in lines:
                if line.strip().startswith(f"[{dataset}]"):
                    skip = True
                    continue
                elif line.strip().startswith("[") and skip:
                    skip = False
                if not skip:
                    new_lines.append(line)
            
            new_config = '\n'.join(new_lines)
            escaped_config = new_config.replace("'", "'\\''")
            write_cmd = f"echo '{escaped_config}' > {self.SANOID_CONF_PATH}"
            
            result = await ssh_service.execute(
                hostname=hostname,
                command=write_cmd,
                port=port,
                username=username,
                key_path=key_path,
                timeout=30
            )
            
            return result.success, "Configurazione rimossa" if result.success else result.stderr
            
        except Exception as e:
            return False, str(e)
    
    async def run_sanoid(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> tuple[bool, str]:
        """Esegue sanoid manualmente per creare/eliminare snapshot"""
        result = await ssh_service.execute(
            hostname=hostname,
            command="sanoid --cron --verbose",
            port=port,
            username=username,
            key_path=key_path,
            timeout=300
        )
        return result.success, result.stdout if result.success else result.stderr
    
    async def list_snapshots(
        self,
        hostname: str,
        dataset: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> List[Dict]:
        """Lista le snapshot sanoid per un dataset"""
        cmd = f"zfs list -t snapshot -o name,creation,used -s creation {dataset} 2>/dev/null | grep -E 'autosnap|syncoid' || true"
        result = await ssh_service.execute(
            hostname=hostname,
            command=cmd,
            port=port,
            username=username,
            key_path=key_path,
            timeout=60
        )
        
        snapshots = []
        if result.success and result.stdout.strip():
            for line in result.stdout.strip().split('\n')[1:]:  # Skip header
                parts = line.split()
                if len(parts) >= 3:
                    snapshots.append({
                        "name": parts[0],
                        "creation": " ".join(parts[1:-1]),
                        "used": parts[-1]
                    })
        return snapshots


sanoid_config_service = SanoidConfigService()

