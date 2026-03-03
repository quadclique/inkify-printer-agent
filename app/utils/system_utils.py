import logging
import psutil
from typing import Dict, Any

logger = logging.getLogger(__name__)


def get_system_metrics() -> Dict[str, Any]:
    """
    Gathers current system utilization metrics (CPU, Memory, Disk).
    Fails gracefully if psutil encounters permission issues.
    """
    metrics = {
        "cpu_percent": 0.0,
        "ram_mb_used": 0,
        "ram_mb_total": 0,
        "disk_gb_free": 0.0,
    }

    try:
        # CPU: interval=0.1 takes a quick 100ms sample to get an accurate reading
        metrics["cpu_percent"] = psutil.cpu_percent(interval=0.1)

        # Memory (RAM)
        mem = psutil.virtual_memory()
        metrics["ram_mb_used"] = int(mem.used / (1024 * 1024))
        metrics["ram_mb_total"] = int(mem.total / (1024 * 1024))

        # Disk space (Checking the root/working directory)
        disk = psutil.disk_usage("/")
        metrics["disk_gb_free"] = round(disk.free / (1024 * 1024 * 1024), 2)

    except Exception as e:
        logger.warning(f"Could not gather full system metrics: {e}")

    return metrics
