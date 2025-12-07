"""
Host Info Service - Raccolta informazioni dettagliate host Proxmox
Ispirato a Proxreporter per raccogliere dati hardware, storage, network, etc.
"""

import json
import re
import logging
from typing import Dict, List, Optional, Any, Tuple
from datetime import datetime

from services.ssh_service import ssh_service

logger = logging.getLogger(__name__)


class HostInfoService:
    """Servizio per raccogliere informazioni dettagliate sugli host Proxmox"""
    
    async def get_host_details(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa",
        include_hardware: bool = True,
        include_storage: bool = True,
        include_network: bool = True
    ) -> Dict[str, Any]:
        """
        Raccolta informazioni host usando pvesh e comandi SSH.
        Ispirato a Proxreporter.
        """
        result = {
            "hostname": hostname,
            "timestamp": datetime.utcnow().isoformat(),
            "cpu": {},
            "memory": {},
            "system": {},
            "storage": [],
            "network": [],
            "temperature": {},
            "license": {}
        }
        
        # Info base via pvesh
        node_info = await self._get_node_info_via_pvesh(hostname, port, username, key_path)
        if node_info:
            result.update(node_info)
        
        # CPU info
        if include_hardware:
            cpu_info = await self._get_cpu_info(hostname, port, username, key_path)
            if cpu_info:
                result["cpu"] = cpu_info
            
            # Memory info
            memory_info = await self._get_memory_info(hostname, port, username, key_path)
            if memory_info:
                result["memory"] = memory_info
            
            # Temperature
            temp_info = await self._get_temperature_readings(hostname, port, username, key_path)
            if temp_info:
                result["temperature"] = temp_info
        
        # Storage info
        if include_storage:
            storage_list = await self._get_storage_details(hostname, port, username, key_path)
            if storage_list:
                result["storage"] = storage_list
        
        # Network info
        if include_network:
            network_list = await self._get_network_details(hostname, port, username, key_path)
            if network_list:
                result["network"] = network_list
        
        # License info
        license_info = await self._get_license_info(hostname, port, username, key_path)
        if license_info:
            result["license"] = license_info
        
        return result
    
    async def _get_node_info_via_pvesh(
        self,
        hostname: str,
        port: int,
        username: str,
        key_path: str
    ) -> Optional[Dict[str, Any]]:
        """Ottiene info base del nodo via pvesh"""
        try:
            # Ottieni hostname del nodo
            cmd = "hostname"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            node_name = result.stdout.strip() if result.success else hostname
            
            # Info versione Proxmox
            cmd = "pveversion -v 2>/dev/null | head -1"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            proxmox_version = result.stdout.strip() if result.success else None
            
            # Kernel version
            cmd = "uname -r"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            kernel_version = result.stdout.strip() if result.success else None
            
            # Uptime
            cmd = "cat /proc/uptime | awk '{print int($1)}'"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            uptime_seconds = int(result.stdout.strip()) if result.success and result.stdout.strip().isdigit() else None
            
            return {
                "node_name": node_name,
                "proxmox_version": proxmox_version,
                "kernel_version": kernel_version,
                "uptime_seconds": uptime_seconds
            }
        except Exception as e:
            logger.error(f"Errore raccolta info nodo: {e}")
            return None
    
    async def _get_cpu_info(
        self,
        hostname: str,
        port: int,
        username: str,
        key_path: str
    ) -> Optional[Dict[str, Any]]:
        """Ottiene informazioni CPU"""
        try:
            # lscpu per info CPU
            cmd = "lscpu 2>/dev/null"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if not result.success:
                return None
            
            cpu_info = {}
            for line in result.stdout.splitlines():
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower().replace(' ', '_')
                    value = value.strip()
                    
                    if 'model_name' in key or 'model name' in key:
                        cpu_info["model"] = value
                    elif 'cpu(s)' in key and 'thread' not in key:
                        try:
                            cpu_info["cores"] = int(value)
                        except:
                            pass
                    elif 'socket' in key:
                        try:
                            cpu_info["sockets"] = int(value)
                        except:
                            pass
                    elif 'thread(s)_per_core' in key or 'thread per core' in key:
                        try:
                            cpu_info["threads_per_core"] = int(value)
                        except:
                            pass
            
            # Calcola threads totali
            if "cores" in cpu_info and "sockets" in cpu_info:
                cores_per_socket = cpu_info["cores"] // cpu_info["sockets"] if cpu_info["sockets"] > 0 else cpu_info["cores"]
                threads_per_core = cpu_info.get("threads_per_core", 1)
                cpu_info["threads"] = cpu_info["sockets"] * cores_per_socket * threads_per_core
            
            # Load average
            cmd = "cat /proc/loadavg | awk '{print $1, $2, $3}'"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            if result.success:
                try:
                    loads = result.stdout.strip().split()
                    if len(loads) >= 3:
                        cpu_info["load_1m"] = float(loads[0])
                        cpu_info["load_5m"] = float(loads[1])
                        cpu_info["load_15m"] = float(loads[2])
                except:
                    pass
            
            return cpu_info if cpu_info else None
        except Exception as e:
            logger.error(f"Errore raccolta info CPU: {e}")
            return None
    
    async def _get_memory_info(
        self,
        hostname: str,
        port: int,
        username: str,
        key_path: str
    ) -> Optional[Dict[str, Any]]:
        """Ottiene informazioni memoria"""
        try:
            # MemInfo
            cmd = "cat /proc/meminfo | grep -E '^MemTotal|^MemAvailable|^MemFree|^SwapTotal|^SwapFree'"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if not result.success:
                return None
            
            mem_info = {}
            for line in result.stdout.splitlines():
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower()
                    value = int(value.strip().split()[0]) if value.strip().split()[0].isdigit() else 0
                    
                    # Converti da KB a GB
                    value_gb = value / (1024 * 1024)
                    
                    if 'memtotal' in key:
                        mem_info["total_gb"] = round(value_gb, 2)
                    elif 'memavailable' in key:
                        mem_info["available_gb"] = round(value_gb, 2)
                    elif 'memfree' in key:
                        mem_info["free_gb"] = round(value_gb, 2)
                    elif 'swaptotal' in key:
                        mem_info["swap_total_gb"] = round(value_gb, 2)
                    elif 'swapfree' in key:
                        mem_info["swap_free_gb"] = round(value_gb, 2)
            
            # Calcola used
            if "total_gb" in mem_info and "available_gb" in mem_info:
                mem_info["used_gb"] = round(mem_info["total_gb"] - mem_info["available_gb"], 2)
            
            if "swap_total_gb" in mem_info and "swap_free_gb" in mem_info:
                mem_info["swap_used_gb"] = round(mem_info["swap_total_gb"] - mem_info["swap_free_gb"], 2)
            
            return mem_info if mem_info else None
        except Exception as e:
            logger.error(f"Errore raccolta info memoria: {e}")
            return None
    
    async def _get_storage_details(
        self,
        hostname: str,
        port: int,
        username: str,
        key_path: str
    ) -> List[Dict[str, Any]]:
        """Ottiene dettagli storage via pvesm"""
        try:
            # pvesm status per lista storage
            cmd = "pvesm status --output-format json 2>/dev/null"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if not result.success or not result.stdout.strip():
                # Fallback: pvesm status senza JSON
                cmd = "pvesm status 2>/dev/null"
                result = await ssh_service.execute(hostname, cmd, port, username, key_path)
                return self._parse_pvesm_text(result.stdout) if result.success else []
            
            try:
                storage_list = json.loads(result.stdout)
                storage_details = []
                
                for storage in storage_list:
                    storage_info = {
                        "name": storage.get("name", ""),
                        "type": storage.get("type", ""),
                        "status": storage.get("status", ""),
                        "total_gb": None,
                        "used_gb": None,
                        "available_gb": None,
                        "used_percent": None,
                        "content": storage.get("content", "")
                    }
                    
                    # Parse size (es: "1234567890" bytes)
                    if storage.get("total"):
                        try:
                            total_bytes = int(storage.get("total", 0))
                            storage_info["total_gb"] = round(total_bytes / (1024**3), 2)
                        except:
                            pass
                    
                    if storage.get("used"):
                        try:
                            used_bytes = int(storage.get("used", 0))
                            storage_info["used_gb"] = round(used_bytes / (1024**3), 2)
                        except:
                            pass
                    
                    if storage_info["total_gb"] and storage_info["used_gb"]:
                        storage_info["available_gb"] = round(storage_info["total_gb"] - storage_info["used_gb"], 2)
                        if storage_info["total_gb"] > 0:
                            storage_info["used_percent"] = round((storage_info["used_gb"] / storage_info["total_gb"]) * 100, 2)
                    
                    storage_details.append(storage_info)
                
                return storage_details
            except json.JSONDecodeError:
                # Fallback a parsing testo
                return self._parse_pvesm_text(result.stdout)
        except Exception as e:
            logger.error(f"Errore raccolta storage: {e}")
            return []
    
    def _parse_pvesm_text(self, output: str) -> List[Dict[str, Any]]:
        """Parse output testo pvesm status"""
        storage_details = []
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        
        # Skip header
        for line in lines[1:]:
            parts = re.split(r'\s+', line)
            if len(parts) < 7:
                continue
            
            name, stype, status = parts[0], parts[1], parts[2]
            total_raw, used_raw, avail_raw, percent_raw = parts[3], parts[4], parts[5], parts[6]
            
            storage_info = {
                "name": name,
                "type": stype,
                "status": status,
                "total_gb": self._safe_parse_size(total_raw),
                "used_gb": self._safe_parse_size(used_raw),
                "available_gb": self._safe_parse_size(avail_raw),
                "used_percent": None,
                "content": ""
            }
            
            # Parse percent
            percent_match = re.search(r'([\d.,]+)', percent_raw)
            if percent_match:
                try:
                    storage_info["used_percent"] = float(percent_match.group(1).replace(',', '.'))
                except:
                    pass
            
            if storage_info["total_gb"] and storage_info["used_gb"]:
                if storage_info["total_gb"] > 0:
                    storage_info["used_percent"] = round((storage_info["used_gb"] / storage_info["total_gb"]) * 100, 2)
            
            storage_details.append(storage_info)
        
        return storage_details
    
    def _safe_parse_size(self, value: str) -> Optional[float]:
        """Converte byte in GiB"""
        if not value:
            return None
        try:
            numeric = float(value)
            return round(numeric / (1024**3), 2)
        except ValueError:
            return None
    
    async def _get_network_details(
        self,
        hostname: str,
        port: int,
        username: str,
        key_path: str
    ) -> List[Dict[str, Any]]:
        """Ottiene dettagli network via pvesh"""
        try:
            # pvesh per network config
            cmd = "pvesh get /nodes/$(hostname)/network --output-format json 2>/dev/null"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if not result.success or not result.stdout.strip():
                return []
            
            try:
                network_list = json.loads(result.stdout)
                network_details = []
                
                for iface in network_list:
                    iface_info = {
                        "name": iface.get("iface", ""),
                        "type": iface.get("type", ""),
                        "state": "up",  # Default
                        "mac": iface.get("hwaddr", ""),
                        "ipv4": [],
                        "ipv6": [],
                        "bridge": iface.get("bridge", ""),
                        "vlan_id": iface.get("vlan-raw-device", ""),
                        "bond_mode": iface.get("bond_mode", ""),
                        "comment": iface.get("comments", "")
                    }
                    
                    # IP addresses (se disponibili)
                    if iface.get("address"):
                        iface_info["ipv4"].append(iface["address"])
                    
                    network_details.append(iface_info)
                
                return network_details
            except json.JSONDecodeError:
                return []
        except Exception as e:
            logger.error(f"Errore raccolta network: {e}")
            return []
    
    async def _get_temperature_readings(
        self,
        hostname: str,
        port: int,
        username: str,
        key_path: str
    ) -> Optional[Dict[str, Any]]:
        """Ottiene letture temperatura"""
        try:
            # sensors -Aj per JSON
            cmd = "sensors -Aj 2>/dev/null"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            readings = []
            highest = None
            
            if result.success and result.stdout.strip():
                try:
                    data = json.loads(result.stdout)
                    for chip_name, chip_data in data.items():
                        if not isinstance(chip_data, dict):
                            continue
                        for sensor_name, sensor_values in chip_data.items():
                            if not isinstance(sensor_values, dict):
                                continue
                            for key, value in sensor_values.items():
                                if key.endswith("_input"):
                                    try:
                                        temp_val = float(value)
                                        readings.append({
                                            "chip": chip_name,
                                            "sensor": sensor_name,
                                            "temperature_c": round(temp_val, 1)
                                        })
                                        highest = temp_val if highest is None else max(highest, temp_val)
                                    except (TypeError, ValueError):
                                        pass
                except json.JSONDecodeError:
                    pass
            
            if readings:
                return {
                    "readings": readings[:20],  # Limita a 20
                    "highest_c": round(highest, 1) if highest else None
                }
            
            return None
        except Exception as e:
            logger.error(f"Errore raccolta temperatura: {e}")
            return None
    
    async def _get_license_info(
        self,
        hostname: str,
        port: int,
        username: str,
        key_path: str
    ) -> Optional[Dict[str, Any]]:
        """Ottiene informazioni licenza Proxmox"""
        try:
            cmd = "pvesubscription get 2>/dev/null"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if not result.success:
                return None
            
            license_info = {}
            for line in result.stdout.splitlines():
                if ':' in line:
                    key, value = line.split(':', 1)
                    key = key.strip().lower().replace(' ', '_')
                    value = value.strip()
                    
                    if 'status' in key:
                        license_info["status"] = value
                    elif 'level' in key:
                        license_info["level"] = value
                    elif 'productname' in key:
                        license_info["type"] = value
                    elif 'key' in key:
                        license_info["key"] = value[:20] + "..." if len(value) > 20 else value
                    elif 'serverid' in key:
                        license_info["server_id"] = value
                    elif 'sockets' in key:
                        try:
                            license_info["sockets"] = int(value)
                        except:
                            pass
                    elif 'nextduedate' in key:
                        license_info["expires"] = value if value and value != "N/A" else None
            
            return license_info if license_info else None
        except Exception as e:
            logger.error(f"Errore raccolta licenza: {e}")
            return None


# Singleton
host_info_service = HostInfoService()

