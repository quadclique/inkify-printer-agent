import os
import time
import json
import logging
import threading
import subprocess
from typing import List, Dict, Optional, Callable
from app.platform.base import BasePrinterManager

logger = logging.getLogger(__name__)

class WindowsPrinterManager(BasePrinterManager):
    """Windows Print Spooler implementation using WMI via PowerShell."""

    def _run_ps_cmd(self, command: str, timeout: int = 30) -> subprocess.CompletedProcess:
        """Helper to run PowerShell commands with standard options to avoid window flashes."""
        
        cmd = ["powershell", "-NoProfile", "-Command", command]
        
        # Use creationflags=subprocess.CREATE_NO_WINDOW to prevent popup flashes on Windows
        creationflags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=True,
            creationflags=creationflags,
            timeout=timeout,
        )

    def get_printers(self) -> List[Dict[str, str]]:
        """
        Queries Windows for available printers using WMI via PowerShell.
        This provides the necessary PortName and PNPDeviceID for hardware matching.
        """
        printers = []
        try:
            # 1. Use WMI via PowerShell to get detailed printer data
            # PortName helps identify USB vs Network. PNPDeviceID contains hardware signatures.
            command = (
                "Get-WmiObject -Class Win32_Printer | "
                "Select-Object Name, PrinterStatus, PortName, PNPDeviceID, Network | "
                "ConvertTo-Json -Compress"
            )
            
            result = self._run_ps_cmd(command, timeout=30)
            output = result.stdout.strip()
            if not output:
                logger.warning("WMI query returned empty output.")
                return []

            # PowerShell might return a single object or an array
            wmi_printers = json.loads(output)
            if not isinstance(wmi_printers, list):
                wmi_printers = [wmi_printers]

            for p in wmi_printers:
                printer_name = p.get("Name")
                if not printer_name:
                    continue

                port_name = p.get("PortName", "").upper()
                pnp_id = p.get("PNPDeviceID", "")
                is_network = p.get("Network", False)

                # 2. Determine Connection Type
                if (
                    is_network
                    or port_name.startswith("IP_")
                    or port_name.startswith("WSD-")
                    or port_name.startswith("TCP")
                ):
                    connection_type = "network"
                elif port_name.startswith("USB") or port_name.startswith("DOT4"):
                    connection_type = "usb"
                else:
                    connection_type = "unknown"

                # 3. Determine Hardware Signature
                # Use the PNPDeviceID (Plug and Play ID) as the hardware signature (contains VID/PID and serials) for USB devices.
                # If missing (often true for pure network printers initially), fallback to the printer name.
                hardware_signature = pnp_id if pnp_id else printer_name

                # 4. Map WMI PrinterStatus codes to basic statuses
                # WMI Codes: 3 = Idle, 4 = Printing, 1 = Other, 2 = Unknown, 5 = Warming Up, 6 = Stopped, 7 = Offline                status_code = p.get("PrinterStatus", 3)
                status_code = p.get("PrinterStatus", 3)
                if status_code == 3:
                    status = "idle"
                elif status_code == 4:
                    status = "printing"
                else:
                    status = "offline"

                caps = self.get_printer_capabilities(printer_name)

                printers.append(
                    {
                        "id": printer_name,
                        "name": printer_name,
                        "status": status,
                        "raw_status": f"WMI_Code_{status_code}",
                        "connection_type": connection_type,
                        "device_uri": port_name,
                        "hardware_signature": hardware_signature,# Deep querying requires DeviceCapabilities via pywin32
                        "supports_color": caps["supports_color"],
                        "supports_duplex": caps["supports_duplex"],
                    }
                )

            return printers

        except subprocess.CalledProcessError as e:
            logger.error(f"PowerShell command failed: {e.stderr}")
            return []
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse WMI JSON output: {e}")
            return []
        except Exception as e:
            logger.error(f"Failed to query Windows WMI printers: {e}")
            return []

    def get_printer_capabilities(self, printer_name: str) -> Dict[str, bool]:
        """
        Queries DeviceCapabilities via PowerShell.
        Falls back to conservative defaults if unavailable.
        """
        try:
            command = (
                f"$p = Get-WmiObject Win32_Printer | Where-Object {{$_.Name -eq '{printer_name}'}}; "
                "$caps = @{supports_color=$false;supports_duplex=$false}; "
                "if ($p.CapabilityDescriptions -contains 'Color') {$caps.supports_color=$true}; "
                "if ($p.CapabilityDescriptions -contains 'Duplex') {$caps.supports_duplex=$true}; "
                "$caps | ConvertTo-Json -Compress"
            )
            result = self._run_ps_cmd(command, timeout=10)
            if result.stdout.strip():
                data = json.loads(result.stdout.strip())
                return {
                    "supports_color": bool(data.get("supports_color", False)),
                    "supports_duplex": bool(data.get("supports_duplex", False)),
                }
        except Exception:
            pass
        return {"supports_color": True, "supports_duplex": False}

    def _monitor_windows_job(
        self,
        job_id: str,
        printer_name: str,
        on_success: Optional[Callable],
        on_failure: Optional[Callable],
        timeout: int = 300,
    ) -> None:
        """
        Monitors a Windows print job using WMI Win32_PrintJob queries.
        Polls every 2 seconds until the job completes, errors, or times out.

        WMI JobStatus codes of interest:
          "Printing"    → in progress
          "Printed"     → success (job left the spooler successfully)
          "Error"       → hardware/driver error
          "Offline"     → printer offline
          "Paper Out"   → needs attention
          "Paused"      → user-paused
          "Deleting"    → job was cancelled
        """
        try:
            import win32com.client  # type: ignore
            import pythoncom  # type: ignore

            pythoncom.CoInitialize()
            wmi = win32com.client.Dispatch("WbemScripting.SWbemLocator")
            svc = wmi.ConnectServer(".", "root\\cimv2")

            start_time = time.time()
            job_found_at_least_once = False

            while time.time() - start_time < timeout:
                try:
                    # Query for our specific job by Document name (title we set)
                    query = (
                        f"SELECT * FROM Win32_PrintJob "
                        f"WHERE Name LIKE '%{printer_name}%'"
                    )
                    jobs = list(svc.ExecQuery(query))

                    if not jobs:
                        if job_found_at_least_once:
                            # Job disappeared from spooler — it was printed or deleted
                            # Check if we saw it complete gracefully
                            logger.info(
                                f"Windows job for '{printer_name}' left spooler. Assuming success."
                            )
                            if on_success:
                                on_success()
                            return
                        time.sleep(2)
                        continue
                    
                    # Process the first matching job
                    wmi_job = jobs[0]
                    job_found_at_least_once = True
                    status = (getattr(wmi_job, "JobStatus", "") or "").strip().lower()
                    pages_printed = getattr(wmi_job, "PagesPrinted", 0) or 0

                    logger.debug(
                        f"Windows job '{printer_name}' status: {status}, "
                        f"pages printed: {pages_printed}"
                    )

                    if status == "printed" or (status == "" and pages_printed > 0):
                        logger.info(f"Windows job for '{printer_name}' printed successfully.")
                        if on_success:
                            on_success()
                        return

                    if status in ("error", "offline", "paper out", "deleting"):
                        error_msg = (
                            f"Windows print job failed for '{printer_name}': "
                            f"status='{status}'"
                        )
                        logger.error(error_msg)
                        if on_failure:
                            on_failure(error_msg)
                        return

                    # Still printing — wait and poll again
                    time.sleep(2)

                except Exception as poll_err:
                    logger.debug(f"WMI poll error (transient): {poll_err}")
                    time.sleep(2)

            # Timeout reached
            timeout_msg = (
                f"Windows job for '{printer_name}' timed out after {timeout}s."
            )
            logger.error(timeout_msg)
            if on_failure:
                on_failure(timeout_msg)

        except ImportError:
            # pywin32 not available — fall back to conservative wait
            logger.warning(
                "pywin32 not available for WMI job monitoring. "
                "Waiting 15s and assuming success."
            )
            time.sleep(15)
            if on_success:
                on_success()
        except Exception as e:
            logger.error(f"WMI job monitor failed unexpectedly: {e}")
            if on_failure:
                on_failure(str(e))
        finally:
            try:
                import pythoncom  # type: ignore
                pythoncom.CoUninitialize()
            except Exception:
                pass

    def print_file_async(
        self,
        printer_name: str,
        file_path: str,
        title: str = "Inkify_Job",
        copies: int = 1,
        is_color: bool = False,
        on_success: Optional[Callable] = None,
        on_failure: Optional[Callable] = None,
    ) -> Optional[str]:
        try:
            import win32api  # type: ignore
            import win32print  # type: ignore

            # Convert to absolute path for Windows API
            abs_path = os.path.abspath(file_path)
            
            # Temporary set default printer so ShellExecute targets it
            old_default = win32print.GetDefaultPrinter()
            win32print.SetDefaultPrinter(printer_name)

            try:
                for _ in range(copies):
                    win32api.ShellExecute(0, "print", abs_path, f'/d:"{printer_name}"', ".", 0)
                    time.sleep(0.5) # Give spooler time to ingest
            finally:
                # Always restore old default printer
                try:
                    win32print.SetDefaultPrinter(old_default)
                except Exception:
                    pass

            job_id = f"WIN-{int(time.time())}"
            monitor_thread = threading.Thread(
                target=self._monitor_windows_job,
                args=(job_id, printer_name, on_success, on_failure),
                daemon=True,
                name=f"WinMonitor-{job_id}",
            )
            monitor_thread.start()
            return job_id

        except ImportError:
            error_msg = "pywin32 is required for printing on Windows. Run: pip install pywin32"
            logger.error(error_msg)
            if on_failure:
                on_failure(error_msg)
            return None
        except Exception as e:
            error_msg = f"Windows ShellExecute failed: {e}"
            logger.error(error_msg)
            if on_failure:
                on_failure(error_msg)
            return None

    def clear_queue(self, printer_name: str) -> bool:
        try:
            import win32print  # type: ignore

            handle = win32print.OpenPrinter(printer_name)
            try:
                win32print.SetPrinter(handle, 0, None, win32print.PRINTER_CONTROL_PURGE)
            finally:
                win32print.ClosePrinter(handle)
            logger.info(f"Cleared Windows print queue for {printer_name}.")
            return True
        except ImportError:
            logger.error("pywin32 not available for queue clearing.")
            return False
        except Exception as e:
            logger.error(f"Failed to clear Windows queue for {printer_name}: {e}")
            return False