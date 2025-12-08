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
        
        # Hardware info
        if include_hardware:
            hardware_info = await self._get_hardware_info(hostname, port, username, key_path)
            if hardware_info:
                result["hardware"] = hardware_info
        
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
            
            # Info versione Proxmox (solo numero versione)
            cmd = "pveversion 2>/dev/null | grep -oE '[0-9]+\\.[0-9]+\\.[0-9]+' | head -1"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            proxmox_version = result.stdout.strip() if result.success and result.stdout.strip() else None
            
            # Kernel version (solo numero)
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
            # Prima ottieni configurazione storage per flag shared
            storage_config = {}
            cmd_config = "pvesh get /storage --output-format json 2>/dev/null"
            config_result = await ssh_service.execute(hostname, cmd_config, port, username, key_path)
            if config_result.success and config_result.stdout.strip():
                try:
                    config_list = json.loads(config_result.stdout)
                    for cfg in config_list:
                        name = cfg.get("storage", cfg.get("name", ""))
                        storage_config[name] = {
                            "shared": cfg.get("shared", 0) == 1,
                            "type": cfg.get("type", "")
                        }
                except json.JSONDecodeError:
                    pass
            
            # pvesm status per lista storage
            cmd = "pvesm status --output-format json 2>/dev/null"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if not result.success or not result.stdout.strip():
                # Fallback: pvesm status senza JSON
                cmd = "pvesm status 2>/dev/null"
                result = await ssh_service.execute(hostname, cmd, port, username, key_path)
                storage_list = self._parse_pvesm_text(result.stdout) if result.success else []
                # Aggiungi flag shared dal config
                for s in storage_list:
                    cfg = storage_config.get(s.get("name"), {})
                    s["shared"] = cfg.get("shared", s.get("type") in ["nfs", "cifs", "pbs", "glusterfs", "cephfs", "rbd"])
                return storage_list
            
            try:
                storage_list = json.loads(result.stdout)
                storage_details = []
                
                for storage in storage_list:
                    name = storage.get("storage", storage.get("name", ""))
                    stype = storage.get("type", "")
                    cfg = storage_config.get(name, {})
                    
                    # Determina se è condiviso (da config o da tipo)
                    is_shared = cfg.get("shared", stype in ["nfs", "cifs", "pbs", "glusterfs", "cephfs", "rbd"])
                    
                    storage_info = {
                        "name": name,
                        "type": stype,
                        "status": storage.get("status", ""),
                        "total_gb": None,
                        "used_gb": None,
                        "available_gb": None,
                        "used_percent": None,
                        "content": storage.get("content", ""),
                        "shared": is_shared
                    }
                    
                    # pvesm status restituisce valori in KiB (kibibytes)
                    if storage.get("total"):
                        try:
                            total_val = int(storage.get("total", 0))
                            # Se > 10 PB in KiB (~10 * 1024^4), probabilmente sono bytes
                            if total_val > 10 * (1024**4):
                                storage_info["total_gb"] = round(total_val / (1024**3), 2)
                            else:
                                storage_info["total_gb"] = round(total_val / (1024 * 1024), 2)
                        except (ValueError, TypeError):
                            pass
                    
                    if storage.get("used"):
                        try:
                            used_val = int(storage.get("used", 0))
                            if used_val > 10 * (1024**4):
                                storage_info["used_gb"] = round(used_val / (1024**3), 2)
                            else:
                                storage_info["used_gb"] = round(used_val / (1024 * 1024), 2)
                        except (ValueError, TypeError):
                            pass
                    
                    if storage_info["total_gb"] is not None and storage_info["used_gb"] is not None:
                        storage_info["available_gb"] = round(storage_info["total_gb"] - storage_info["used_gb"], 2)
                        if storage_info["total_gb"] > 0:
                            storage_info["used_percent"] = round((storage_info["used_gb"] / storage_info["total_gb"]) * 100, 2)
                    
                    storage_details.append(storage_info)
                
                return storage_details
            except json.JSONDecodeError:
                # Fallback a parsing testo
                storage_list = self._parse_pvesm_text(result.stdout)
                for s in storage_list:
                    cfg = storage_config.get(s.get("name"), {})
                    s["shared"] = cfg.get("shared", s.get("type") in ["nfs", "cifs", "pbs", "glusterfs", "cephfs", "rbd"])
                return storage_list
        except Exception as e:
            logger.error(f"Errore raccolta storage: {e}")
            return []
    
    def _parse_pvesm_text(self, output: str) -> List[Dict[str, Any]]:
        """Parse output testo pvesm status (valori in KiB)"""
        storage_details = []
        lines = [line.strip() for line in output.splitlines() if line.strip()]
        
        # Skip header
        for line in lines[1:]:
            parts = re.split(r'\s+', line)
            if len(parts) < 7:
                continue
            
            name, stype, status = parts[0], parts[1], parts[2]
            total_raw, used_raw, avail_raw, percent_raw = parts[3], parts[4], parts[5], parts[6]
            
            # pvesm status output è in KiB - converti in GB
            storage_info = {
                "name": name,
                "type": stype,
                "status": status,
                "total_gb": self._kib_to_gb(total_raw),
                "used_gb": self._kib_to_gb(used_raw),
                "available_gb": self._kib_to_gb(avail_raw),
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
    
    def _kib_to_gb(self, value: str) -> Optional[float]:
        """Converte KiB in GB. pvesm status restituisce sempre valori in KiB."""
        if not value:
            return None
        try:
            kib = float(str(value).strip().replace(',', '.'))
            # KiB -> GB: dividi per 1024^2
            return round(kib / (1024 * 1024), 2)
        except ValueError:
            return None
    
    def _safe_parse_size(self, value: str, default_unit: str = 'B') -> Optional[float]:
        """
        Converte valore di storage in GB.
        Gestisce bytes, KB, MB, GB, TB con o senza unità esplicita.
        
        Args:
            value: Valore da convertire
            default_unit: Unità di default se non specificata ('B' per bytes, 'K' per KiB)
        """
        if not value:
            return None
        
        # Rimuovi spazi e converti in stringa
        value = str(value).strip().upper()
        
        # Se contiene unità, estraila
        unit_match = re.search(r'([\d.,]+)\s*([KMGT]?I?B?)$', value)
        if unit_match:
            numeric_str = unit_match.group(1).replace(',', '.')
            unit = unit_match.group(2) or default_unit
            try:
                numeric = float(numeric_str)
                
                # Converti in GB
                if not unit or unit in ['B', 'BYTES']:
                    # Bytes -> GB
                    return round(numeric / (1024**3), 2)
                elif unit.startswith('K'):
                    # KiB -> GB
                    return round(numeric / (1024 * 1024), 2)
                elif unit.startswith('M'):
                    # MiB -> GB
                    return round(numeric / 1024, 2)
                elif unit.startswith('G'):
                    # GiB -> GB (approssimato)
                    return round(numeric, 2)
                elif unit.startswith('T'):
                    # TiB -> GB
                    return round(numeric * 1024, 2)
                else:
                    # Default: usa l'unità di default
                    if default_unit == 'K':
                        return round(numeric / (1024 * 1024), 2)
                    else:
                        return round(numeric / (1024**3), 2)
            except ValueError:
                return None
        else:
            # Nessuna unità esplicita
            try:
                numeric = float(value.replace(',', '.'))
                if default_unit == 'K':
                    # Assume KiB
                    return round(numeric / (1024 * 1024), 2)
                else:
                    # Assume bytes
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
        """Ottiene dettagli network via pvesh e ip/ifconfig"""
        try:
            network_details = []
            
            # Prima ottieni configurazione base da pvesh
            cmd = "pvesh get /nodes/$(hostname)/network --output-format json 2>/dev/null"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            pvesh_interfaces = {}
            if result.success and result.stdout.strip():
                try:
                    network_list = json.loads(result.stdout)
                    for iface in network_list:
                        iface_name = iface.get("iface", "")
                        if iface_name:
                            pvesh_interfaces[iface_name] = iface
                except json.JSONDecodeError:
                    pass
            
            # Ottieni informazioni dettagliate da ip addr
            cmd = "ip -j addr show 2>/dev/null || ip addr show 2>/dev/null"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if not result.success:
                # Fallback a ifconfig
                cmd = "ifconfig 2>/dev/null || ip addr show 2>/dev/null"
                result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if not result.success:
                return []
            
            # Prova a parsare JSON (ip -j)
            try:
                ip_data = json.loads(result.stdout)
                for iface_data in ip_data:
                    iface_name = iface_data.get("ifname", "")
                    if not iface_name or iface_name == "lo":
                        continue
                    
                    iface_info = {
                        "name": iface_name,
                        "type": pvesh_interfaces.get(iface_name, {}).get("type", "ethernet"),
                        "status": "UP" if iface_data.get("operstate") == "UP" else "DOWN",
                        "mac": iface_data.get("address", ""),
                        "ip": None,
                        "netmask": None,
                        "gateway": None,
                        "bridge": pvesh_interfaces.get(iface_name, {}).get("bridge", ""),
                        "vlan_id": pvesh_interfaces.get(iface_name, {}).get("vlan-raw-device", ""),
                        "bond_mode": pvesh_interfaces.get(iface_name, {}).get("bond_mode", ""),
                        "comment": pvesh_interfaces.get(iface_name, {}).get("comments", "")
                    }
                    
                    # Estrai IP e netmask dal primo indirizzo IPv4
                    addr_info = iface_data.get("addr_info", [])
                    for addr in addr_info:
                        if addr.get("family") == "inet":
                            iface_info["ip"] = addr.get("local", "")
                            prefixlen = addr.get("prefixlen", 0)
                            if prefixlen:
                                # Converti prefixlen in netmask
                                iface_info["netmask"] = self._prefixlen_to_netmask(prefixlen)
                            break
                    
                    # Filtra interfacce DOWN
                    if iface_info.get("status", "").upper() == "DOWN":
                        continue
                    
                    # Ottieni gateway per questa interfaccia
                    gateway = await self._get_interface_gateway(hostname, port, username, key_path, iface_name)
                    if gateway:
                        iface_info["gateway"] = gateway
                    
                    network_details.append(iface_info)
                
                return network_details
            except (json.JSONDecodeError, KeyError):
                # Fallback: parsing testo (ifconfig o ip addr senza -j)
                network_details = self._parse_network_text(result.stdout, pvesh_interfaces)
                # Filtra interfacce DOWN e aggiungi gateway per quelle attive
                filtered_details = []
                for iface_info in network_details:
                    status = iface_info.get("status", "").upper()
                    state = iface_info.get("state", "").lower()
                    # Salta interfacce DOWN
                    if status == "DOWN" or state == "down":
                        continue
                    
                    gateway = await self._get_interface_gateway(hostname, port, username, key_path, iface_info["name"])
                    if gateway:
                        iface_info["gateway"] = gateway
                    filtered_details.append(iface_info)
                return filtered_details
        except Exception as e:
            logger.error(f"Errore raccolta network: {e}")
            return []
    
    def _prefixlen_to_netmask(self, prefixlen: int) -> str:
        """Converte prefixlen (CIDR) in netmask"""
        try:
            mask = (0xffffffff >> (32 - prefixlen)) << (32 - prefixlen)
            return f"{mask >> 24 & 0xff}.{mask >> 16 & 0xff}.{mask >> 8 & 0xff}.{mask & 0xff}"
        except:
            return f"/{prefixlen}"
    
    async def _get_interface_gateway(self, hostname: str, port: int, username: str, key_path: str, iface: str) -> Optional[str]:
        """Ottiene il gateway per un'interfaccia"""
        try:
            # Prova a ottenere il gateway dalla route table
            cmd = f"ip route show dev {iface} | grep default | head -1 | awk '{{print $3}}'"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            if result.success and result.stdout.strip():
                return result.stdout.strip()
            
            # Fallback: gateway principale
            cmd = "ip route | grep default | head -1 | awk '{print $3}'"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            if result.success and result.stdout.strip():
                return result.stdout.strip()
        except:
            pass
        return None
    
    def _parse_network_text(self, text: str, pvesh_interfaces: Dict) -> List[Dict[str, Any]]:
        """Parsa output testo di ifconfig o ip addr"""
        network_details = []
        current_iface = None
        
        for line in text.splitlines():
            # ifconfig format: eth0: flags=... mtu 1500
            # ip addr format: 2: eth0: <BROADCAST,MULTICAST,UP,LOWER_UP>
            if ':' in line and not line.strip().startswith('inet'):
                parts = line.split(':')
                iface_name = parts[0].strip()
                if iface_name and iface_name != "lo":
                    current_iface = {
                        "name": iface_name,
                        "type": pvesh_interfaces.get(iface_name, {}).get("type", "ethernet"),
                        "status": "UP" if "UP" in line or "state UP" in line else "DOWN",
                        "mac": "",
                        "ip": None,
                        "netmask": None,
                        "gateway": None,
                        "bridge": pvesh_interfaces.get(iface_name, {}).get("bridge", ""),
                        "vlan_id": pvesh_interfaces.get(iface_name, {}).get("vlan-raw-device", ""),
                        "bond_mode": pvesh_interfaces.get(iface_name, {}).get("bond_mode", ""),
                        "comment": pvesh_interfaces.get(iface_name, {}).get("comments", "")
                    }
                    # Estrai MAC
                    mac_match = re.search(r'([0-9a-fA-F]{2}[:-]){5}([0-9a-fA-F]{2})', line)
                    if mac_match:
                        current_iface["mac"] = mac_match.group(0)
            elif current_iface:
                # IP address line
                # ifconfig: inet 192.168.1.1  netmask 255.255.255.0
                # ip addr: inet 192.168.1.1/24
                ip_match = re.search(r'inet\s+(\d+\.\d+\.\d+\.\d+)', line)
                if ip_match:
                    current_iface["ip"] = ip_match.group(1)
                    # Netmask
                    netmask_match = re.search(r'netmask\s+(\d+\.\d+\.\d+\.\d+)', line)
                    if netmask_match:
                        current_iface["netmask"] = netmask_match.group(1)
                    else:
                        # CIDR format: 192.168.1.1/24
                        cidr_match = re.search(r'/(\d+)', line)
                        if cidr_match:
                            prefixlen = int(cidr_match.group(1))
                            current_iface["netmask"] = self._prefixlen_to_netmask(prefixlen)
                
                # Se abbiamo completato questa interfaccia, aggiungila
                if line.strip() == "" or (line.strip() and not line.startswith(" ") and not line.startswith("\t")):
                    if current_iface.get("name"):
                        network_details.append(current_iface)
                    current_iface = None
        
        # Aggiungi ultima interfaccia se presente
        if current_iface and current_iface.get("name"):
            network_details.append(current_iface)
        
        # Filtra interfacce DOWN prima di restituire
        filtered_details = []
        for iface in network_details:
            status = iface.get("status", "").upper()
            state = iface.get("state", "").lower()
            # Salta interfacce DOWN
            if status != "DOWN" and state != "down":
                filtered_details.append(iface)
        
        return filtered_details
    
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
    
    async def _get_hardware_info(
        self,
        hostname: str,
        port: int,
        username: str,
        key_path: str
    ) -> Optional[Dict[str, Any]]:
        """Ottiene informazioni hardware (DMIDECODE)"""
        try:
            hardware_info = {}
            
            # dmidecode per info hardware
            # Prova prima con dmidecode
            cmd = "dmidecode -t system 2>/dev/null | grep -E 'Manufacturer|Product Name|Version|Serial Number|UUID'"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if result.success:
                for line in result.stdout.splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().lower()
                        value = value.strip()
                        
                        if 'manufacturer' in key:
                            hardware_info["manufacturer"] = value
                        elif 'product name' in key:
                            hardware_info["model"] = value
                        elif 'version' in key:
                            hardware_info["version"] = value
                        elif 'serial number' in key:
                            hardware_info["serial"] = value
                        elif 'uuid' in key:
                            hardware_info["uuid"] = value
            
            # Board info
            cmd = "dmidecode -t baseboard 2>/dev/null | grep -E 'Manufacturer|Product Name|Version|Serial Number'"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if result.success:
                for line in result.stdout.splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().lower()
                        value = value.strip()
                        
                        if 'manufacturer' in key and 'board' not in key:
                            hardware_info["board_manufacturer"] = value
                        elif 'product name' in key:
                            hardware_info["board"] = value
                        elif 'version' in key:
                            hardware_info["board_version"] = value
                        elif 'serial number' in key:
                            hardware_info["board_serial"] = value
            
            # BIOS info
            cmd = "dmidecode -t bios 2>/dev/null | grep -E 'Vendor|Version|Release Date'"
            result = await ssh_service.execute(hostname, cmd, port, username, key_path)
            
            if result.success:
                for line in result.stdout.splitlines():
                    if ':' in line:
                        key, value = line.split(':', 1)
                        key = key.strip().lower()
                        value = value.strip()
                        
                        if 'vendor' in key:
                            hardware_info["bios_vendor"] = value
                        elif 'version' in key:
                            hardware_info["bios_version"] = value
                        elif 'release date' in key:
                            hardware_info["bios_date"] = value
            
            return hardware_info if hardware_info else None
        except Exception as e:
            logger.error(f"Errore raccolta info hardware: {e}")
            return None
    
    async def _get_license_info(
        self,
        hostname: str,
        port: int,
        username: str,
        key_path: str
    ) -> Optional[Dict[str, Any]]:
        """Ottiene informazioni licenza Proxmox complete"""
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
                    elif 'productname' in key or 'product_name' in key:
                        license_info["type"] = value
                    elif 'key' in key and 'serverid' not in key:
                        license_info["key"] = value
                    elif 'serverid' in key or 'subscription' in key:
                        license_info["subscription"] = value
                    elif 'sockets' in key:
                        try:
                            license_info["sockets"] = int(value)
                        except:
                            license_info["sockets"] = value
                    elif 'checktime' in key or 'check_time' in key:
                        license_info["check_time"] = value
                    elif 'nextduedate' in key or 'next_due_date' in key or 'validuntil' in key or 'valid_until' in key:
                        license_info["valid_until"] = value
                    elif 'regdate' in key or 'reg_date' in key:
                        license_info["reg_date"] = value
            
            return license_info if license_info else None
        except Exception as e:
            logger.error(f"Errore raccolta info licenza: {e}")
            return None
    
    async def get_node_metrics(
        self,
        hostname: str,
        port: int = 22,
        username: str = "root",
        key_path: str = "/root/.ssh/id_rsa"
    ) -> Dict[str, Any]:
        """
        Raccolta metriche di performance in tempo reale:
        - CPU usage (%)
        - RAM usage (%)
        - Network I/O (bytes in/out)
        - Disk I/O (read/write)
        """
        metrics = {
            "timestamp": datetime.utcnow().isoformat(),
            "cpu": {
                "usage_percent": 0.0,
                "load_1min": 0.0,
                "load_5min": 0.0,
                "load_15min": 0.0
            },
            "memory": {
                "usage_percent": 0.0,
                "used_gb": 0.0,
                "total_gb": 0.0,
                "available_gb": 0.0
            },
            "network": {
                "interfaces": []
            },
            "disk": {
                "io_read_bytes": 0,
                "io_write_bytes": 0,
                "io_read_ops": 0,
                "io_write_ops": 0
            }
        }
        
        try:
            # Script batch per raccogliere tutte le metriche in una chiamata
            metrics_cmd = '''
# CPU usage e load
cpu_info=$(top -bn1 | grep "Cpu(s)" | sed "s/.*, *\\([0-9.]*\\)%* id.*/\\1/" | awk '{print 100 - $1}')
load_avg=$(uptime | awk -F'load average:' '{print $2}' | awk '{print $1","$2","$3}' | tr -d ' ')
load_1=$(echo "$load_avg" | cut -d',' -f1)
load_5=$(echo "$load_avg" | cut -d',' -f2)
load_15=$(echo "$load_avg" | cut -d',' -f3)

# Memory usage
mem_info=$(free -g | grep "^Mem:")
mem_total=$(echo "$mem_info" | awk '{print $2}')
mem_used=$(echo "$mem_info" | awk '{print $3}')
mem_avail=$(echo "$mem_info" | awk '{print $7}')
mem_percent=$(echo "scale=2; ($mem_used / $mem_total) * 100" | bc)

# Network I/O (bytes in/out per interfaccia principale)
net_dev=$(ip route | grep default | awk '{print $5}' | head -1)
if [ -n "$net_dev" ] && [ -f "/sys/class/net/$net_dev/statistics/rx_bytes" ]; then
    net_rx=$(cat /sys/class/net/$net_dev/statistics/rx_bytes)
    net_tx=$(cat /sys/class/net/$net_dev/statistics/tx_bytes)
    net_rx_packets=$(cat /sys/class/net/$net_dev/statistics/rx_packets)
    net_tx_packets=$(cat /sys/class/net/$net_dev/statistics/tx_packets)
else
    net_rx=0
    net_tx=0
    net_rx_packets=0
    net_tx_packets=0
fi

# Disk I/O (somma di tutti i dischi)
disk_read=0
disk_write=0
disk_read_ops=0
disk_write_ops=0
for disk in /sys/block/sd* /sys/block/nvme* /sys/block/vd*; do
    if [ -f "$disk/stat" ]; then
        read_bytes=$(awk '{print $3}' "$disk/stat" 2>/dev/null || echo "0")
        write_bytes=$(awk '{print $7}' "$disk/stat" 2>/dev/null || echo "0")
        read_ops=$(awk '{print $1}' "$disk/stat" 2>/dev/null || echo "0")
        write_ops=$(awk '{print $5}' "$disk/stat" 2>/dev/null || echo "0")
        disk_read=$((disk_read + read_bytes * 512))
        disk_write=$((disk_write + write_bytes * 512))
        disk_read_ops=$((disk_read_ops + read_ops))
        disk_write_ops=$((disk_write_ops + write_ops))
    fi
done

echo "CPU|$cpu_info|$load_1|$load_5|$load_15"
echo "MEM|$mem_total|$mem_used|$mem_avail|$mem_percent"
echo "NET|$net_dev|$net_rx|$net_tx|$net_rx_packets|$net_tx_packets"
echo "DISK|$disk_read|$disk_write|$disk_read_ops|$disk_write_ops"
'''
            
            result = await ssh_service.execute(
                hostname=hostname,
                command=metrics_cmd,
                port=port,
                username=username,
                key_path=key_path,
                timeout=30
            )
            
            if result.success:
                for line in result.stdout.splitlines():
                    if line.startswith("CPU|"):
                        parts = line.split("|")
                        if len(parts) >= 5:
                            metrics["cpu"]["usage_percent"] = float(parts[1] or 0)
                            metrics["cpu"]["load_1min"] = float(parts[2] or 0)
                            metrics["cpu"]["load_5min"] = float(parts[3] or 0)
                            metrics["cpu"]["load_15min"] = float(parts[4] or 0)
                    elif line.startswith("MEM|"):
                        parts = line.split("|")
                        if len(parts) >= 5:
                            metrics["memory"]["total_gb"] = float(parts[1] or 0)
                            metrics["memory"]["used_gb"] = float(parts[2] or 0)
                            metrics["memory"]["available_gb"] = float(parts[3] or 0)
                            metrics["memory"]["usage_percent"] = float(parts[4] or 0)
                    elif line.startswith("NET|"):
                        parts = line.split("|")
                        if len(parts) >= 6:
                            metrics["network"]["interfaces"] = [{
                                "name": parts[1] or "unknown",
                                "rx_bytes": int(parts[2] or 0),
                                "tx_bytes": int(parts[3] or 0),
                                "rx_packets": int(parts[4] or 0),
                                "tx_packets": int(parts[5] or 0)
                            }]
                    elif line.startswith("DISK|"):
                        parts = line.split("|")
                        if len(parts) >= 5:
                            metrics["disk"]["io_read_bytes"] = int(parts[1] or 0)
                            metrics["disk"]["io_write_bytes"] = int(parts[2] or 0)
                            metrics["disk"]["io_read_ops"] = int(parts[3] or 0)
                            metrics["disk"]["io_write_ops"] = int(parts[4] or 0)
            
            return metrics
        except Exception as e:
            logger.error(f"Errore raccolta metriche per {hostname}: {e}")
            return metrics


# Singleton
host_info_service = HostInfoService()

