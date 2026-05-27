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
    """Windows Spooler implementation."""

    def get_printers(self) -> List[Dict[str, str]]:
        """
        Queries Windows for available printers using WMI via PowerShell.
        This provides the necessary PortName and PNPDeviceID for hardware matching.
        """
        printers = []
        try:
            # 1. Use WMI via PowerShell to get detailed printer data
            # PortName helps identify USB vs Network. PNPDeviceID contains hardware signatures.
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-WmiObject -Class Win32_Printer | Select-Object Name, PrinterStatus, PortName, PNPDeviceID, Network | ConvertTo-Json -Compress",
            ]
            
            # Use creationflags=subprocess.CREATE_NO_WINDOW to prevent popup flashes on Windows
            creationflags = 0
            if os.name == 'nt':
                creationflags = subprocess.CREATE_NO_WINDOW
                
            result = subprocess.run(cmd, capture_output=True, text=True, check=True, creationflags=creationflags)

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
                    
                printers.append(
                    {
                        "id": printer_name,
                        "name": printer_name,
                        "status": status,
                        "raw_status": f"WMI_Code_{status_code}",
                        "connection_type": connection_type,
                        "device_uri": port_name,
                        "hardware_signature": hardware_signature, # Deep querying requires DeviceCapabilities via pywin32
                        "supports_color": True,
                        "supports_duplex": False,
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
        # Advanced DeviceCapabilities queries can be added here later
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
                    jobs = svc.ExecQuery(query)
                    job_list = list(jobs)

                    if not job_list:
                        if job_found_at_least_once:
                            # Job disappeared from spooler — it was printed or deleted
                            # Check if we saw it complete gracefully
                            logger.info(
                                f"Windows job for '{printer_name}' left the spooler. "
                                f"Assuming success."
                            )
                            if on_success:
                                on_success()
                            return
                        else:
                            # Job hasn't appeared yet — wait a moment
                            time.sleep(2)
                            continue

                    # Process the first matching job
                    wmi_job = job_list[0]
                    job_found_at_least_once = True
                    status = (wmi_job.JobStatus or "").strip().lower()
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

    def print_file_async(self, printer_name: str, file_path: str, title: str = "Inkify_Job", copies: int = 1, is_color: bool = False, on_success: Optional[Callable] = None, on_failure: Optional[Callable] = None) -> Optional[str]:
        try:
            import win32api  # type: ignore
            import win32print  # type: ignore
            
            # Convert to absolute path for Windows API
            abs_path = os.path.abspath(file_path)
            
            # Temporary set default printer so ShellExecute targets it
            old_default = win32print.GetDefaultPrinter()
            win32print.SetDefaultPrinter(printer_name)

            for _ in range(copies):
                win32api.ShellExecute(0, "print", abs_path, "", ".", 0)
                time.sleep(1)  # Give spooler time to ingest
                
            # Restore default
            win32print.SetDefaultPrinter(old_default)
            
            job_id = f"WIN-{int(time.time())}"
            monitor_thread = threading.Thread(target=self._monitor_windows_job, args=(job_id, printer_name, on_success, on_failure), daemon=True)
            monitor_thread.start()
            
            return job_id
        
        except ImportError:
            error_msg = "pywin32 is required for printing on Windows. Run: pip install pywin32"
            logger.error(error_msg)
            if on_failure: on_failure(error_msg)
            return None
        except Exception as e:
            error_msg = f"Windows ShellExecute failed: {e}"
            logger.error(error_msg)
            if on_failure: on_failure(error_msg)
            return None

    def clear_queue(self, printer_name: str) -> bool:
        try:
            import win32print  # type: ignore
            handle = win32print.OpenPrinter(printer_name)
            win32print.SetPrinter(handle, 0, None, win32print.PRINTER_CONTROL_PURGE)
            win32print.ClosePrinter(handle)
            return True
        except Exception as e:
            logger.error(f"Failed to clear Windows queue: {e}")
            return False