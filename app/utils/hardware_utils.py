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
    system = platform.system().lower()
    hardware_id = ""
    
    if system == "linux":
        hardware_id = _get_linux_hw_id()
    elif system == "windows":
        hardware_id = _get_windows_uuid()
    elif system == "darwin":
        hardware_id = _get_mac_uuid()

    if not hardware_id:
        # Fallback to the network MAC address (UUID node)
        hardware_id = str(uuid.getnode())
        logger.debug(f"Using MAC-based fallback ID: {hardware_id}")
    else:
        logger.debug(f"Using physical hardware ID for {system}: {hardware_id}")
    
    return hardware_id


def _get_linux_hw_id() -> str:
    """Extracts the CPU serial number from /proc/cpuinfo on Linux systems."""
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    # Looks like: "Serial      : 1000000021b3a4f"
                    return line.split(":")[1].strip()
    except Exception as e:
        logger.warning(f"Failed to read Linux CPU serial: {e}")
    
    return ""

def _get_windows_uuid() -> str:
    """Uses Windows Management Instrumentation (WMI) to get the motherboard UUID."""
    try:
        # Runs a silent command line query
        output = subprocess.check_output("wmic csproduct get uuid", shell=True, text=True)
        # Output looks like:
        # UUID
        # 12345678-1234-1234-1234-1234567890AB
        lines = output.strip().split("\n")
        if len(lines) > 1:
            return lines[1].strip()
    except Exception as e:
        logger.debug(f"Failed to read Windows UUID: {e}")
    
    return ""

def _get_mac_uuid() -> str:
    """Uses Apple's system_profiler to extract the Hardware UUID."""
    try:
        output = subprocess.check_output(
            "/usr/sbin/system_profiler SPHardwareDataType", shell=True, text=True
        )
        for line in output.split("\n"):
            if "Hardware UUID" in line:
                # Looks like: "      Hardware UUID: 12345678-1234-1234-1234-1234567890AB"
                return line.split(":")[1].strip()
    except Exception as e:
        logger.debug(f"Failed to read Mac UUID: {e}")
    
    return ""