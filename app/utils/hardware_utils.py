import os
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
    """
    Extracts a stable hardware ID on Linux using a best-effort fallback chain:

    1. CPU Serial (/proc/cpuinfo) — reliable on Raspberry Pi, empty on most x86.
    2. Machine ID (/etc/machine-id) — systemd-generated UUID, stable across reboots
       on all modern Linux distros (Ubuntu, Debian, Fedora, RHEL, Arch, etc.).
    3. dmidecode system UUID — requires root, but may be available in production.
    4. Returns empty string to trigger the caller's MAC address fallback.
    """
    # 1. CPU Serial (Raspberry Pi)
    try:
        with open("/proc/cpuinfo", "r") as f:
            for line in f:
                if line.startswith("Serial"):
                    serial = line.split(":")[1].strip()
                    if serial and serial != "0000000000000000":
                        return serial
    except Exception as e:
        logger.debug(f"Could not read /proc/cpuinfo Serial: {e}")

    # 2. /etc/machine-id — systemd stable ID (present on all modern Linux distros)
    try:
        for machine_id_path in ["/etc/machine-id", "/var/lib/dbus/machine-id"]:
            if os.path.exists(machine_id_path):
                with open(machine_id_path, "r") as f:
                    machine_id = f.read().strip()
                if machine_id and len(machine_id) >= 16:
                    logger.debug(f"Using /etc/machine-id as hardware ID: {machine_id[:8]}...")
                    return machine_id
    except Exception as e:
        logger.debug(f"Could not read /etc/machine-id: {e}")

    # 3. dmidecode system UUID (requires root)
    try:
        output = subprocess.check_output(
            ["dmidecode", "-s", "system-uuid"],
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        dmi_uuid = output.strip()
        if dmi_uuid and dmi_uuid.lower() not in ("not specified", "not present", ""):
            logger.debug(f"Using dmidecode system UUID as hardware ID.")
            return dmi_uuid
    except Exception as e:
        logger.debug(f"dmidecode not available or no root access: {e}")

    return ""

def _get_windows_uuid() -> str:
    """Uses Windows Management Instrumentation (WMI) to get the motherboard UUID."""
    try:
        # Runs a silent command line query
        output = subprocess.check_output("wmic csproduct get uuid", shell=True, text=True)
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
            ["/usr/sbin/system_profiler, SPHardwareDataType"], shell=True, text=True
        )
        for line in output.split("\n"):
            if "Hardware UUID" in line:
                return line.split(":",1)[1].strip()
    except Exception as e:
        logger.debug(f"Failed to read Mac UUID: {e}")
    
    return ""