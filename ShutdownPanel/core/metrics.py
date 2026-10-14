"""
Real system hardware metrics collector using psutil (v2).
CPU%, RAM, disk, battery, uptime, core count, and thermal readings.
"""

import os
import platform
import socket
import subprocess
import time
from typing import Any, Dict, Optional

import psutil

from core.app_logger import get_logger

TEMP_CACHE_SECS = 30.0


class MetricsCollector:
    def __init__(self):
        self._last_temp_read = 0.0
        self._cached_temp: Optional[float] = None

    # ------------------------------------------------------------------
    def read_thermal_zone(self) -> Optional[float]:
        """Reads a temperature reading (°C) with caching; None if unavailable."""
        now = time.time()
        if now - self._last_temp_read < TEMP_CACHE_SECS and self._cached_temp is not None:
            return self._cached_temp

        self._last_temp_read = now
        temp = self._read_temperature()
        self._cached_temp = temp
        return temp

    def _read_temperature(self) -> Optional[float]:
        system = platform.system().lower()

        if system == "linux":
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    # Prefer typical CPU sensors, else the first available
                    for key in ("coretemp", "k10temp", "cpu_thermal", "acpitz"):
                        if key in temps and temps[key]:
                            return round(temps[key][0].current, 1)
                    first = next(iter(temps.values()))
                    if first:
                        return round(first[0].current, 1)
            except Exception:
                pass
            return None

        if system == "windows":
            try:
                import winreg

                with winreg.OpenKey(
                    winreg.HKEY_LOCAL_MACHINE,
                    r"HARDWARE\DESCRIPTION\System\ThermalZone\0",
                ) as key:
                    deci_k, _ = winreg.QueryValueEx(key, "Temperature")
                    if deci_k and deci_k > 0:
                        return round((float(deci_k) / 10.0) - 273.15, 1)
            except Exception:
                pass
            return None

        # macOS: no standard API without root privileges
        return None

    # ------------------------------------------------------------------
    def sample(self) -> Dict[str, Any]:
        mem = psutil.virtual_memory()
        cpu_percent = psutil.cpu_percent(interval=None)
        used_mb = int(mem.used / (1024 * 1024))
        total_mb = int(mem.total / (1024 * 1024))
        uptime = int(time.time() - psutil.boot_time())

        disk_percent = None
        try:
            disk_percent = round(psutil.disk_usage(os.path.abspath(os.sep)).percent, 1)
        except Exception:
            pass

        battery_percent: Optional[int] = None
        battery_plugged: Optional[bool] = None
        try:
            batt = psutil.sensors_battery()
            if batt is not None:
                battery_percent = round(batt.percent)
                battery_plugged = bool(batt.power_plugged)
        except Exception:
            pass

        return {
            "cpuPercent": round(cpu_percent, 1),
            "ramPercent": round(mem.percent, 1),
            "ramUsedMb": used_mb,
            "ramTotalMb": total_mb,
            "diskPercent": disk_percent,
            "batteryPercent": battery_percent,
            "batteryPlugged": battery_plugged,
            "cores": psutil.cpu_count(logical=True) or 4,
            "uptimeSecs": uptime,
            "host": socket.gethostname(),
            "osName": f"{platform.system()} {platform.release()}",
            "os": platform.system().lower(),
            "tempC": self.read_thermal_zone(),
            "real": True,
        }
