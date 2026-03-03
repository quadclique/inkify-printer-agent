import uuid
import logging
import platform
import subprocess

logger = logging.getLogger(__name__)


def get_hardware_id() -> str:
    """
    Attempts to extract a unique, unchangeable hardware ID from the physical device.
    Tries CPU Serial first (Raspberry Pi/Linux), falls back to MAC address.
    """
    hardware_id = _get_linux_cpu_serial()

    if not hardware_id:
        # Fallback to the network MAC address (UUID node)
        hardware_id = str(uuid.getnode())
        logger.debug(f"Using MAC-based hardware ID: {hardware_id}")
    else:
        logger.debug(f"Using CPU Serial hardware ID: {hardware_id}")

    return hardware_id


def _get_linux_cpu_serial() -> str:
    """Extracts the CPU serial number from /proc/cpuinfo on Linux systems."""
    if platform.system().lower() != "linux":
        return ""

    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    # Looks like: "Serial      : 1000000021b3a4f"
                    return line.split(":")[1].strip()
    except Exception as e:
        logger.warning(f"Could not read CPU serial: {e}")

    return ""
