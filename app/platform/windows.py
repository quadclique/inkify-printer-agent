import os
import time
import logging
import threading
from typing import List, Dict, Optional, Callable
from app.platform.base import BasePrinterManager

logger = logging.getLogger(__name__)

class WindowsPrinterManager(BasePrinterManager):
    """Windows Spooler implementation."""
    
    def get_printers(self) -> List[Dict[str, str]]:
        printers = []
        try:
            import win32print  # type: ignore
            # EnumPrinters(2) gets local and mapped printers
            flags = win32print.PRINTER_ENUM_LOCAL | win32print.PRINTER_ENUM_CONNECTIONS
            for p in win32print.EnumPrinters(flags):
                printer_name = p[2]
                printers.append({
                    "id": printer_name,
                    "name": printer_name,
                    "status": "idle", # Deep status polling requires OpenPrinter on Windows
                    "raw_status": "Ready",
                    "supports_color": True,   
                    "supports_duplex": False,
                })
            return printers
        except ImportError:
            logger.error("pywin32 is not installed. Run: pip install pywin32")
            return []
        except Exception as e:
            logger.error(f"Failed to query Windows printers: {e}")
            return []

    def get_printer_capabilities(self, printer_name: str) -> Dict[str, bool]:
        # Advanced DeviceCapabilities queries can be added here later
        return {"supports_color": True, "supports_duplex": False}

    def _monitor_windows_job(self, job_id: str, printer_name: str, on_success: Optional[Callable], on_failure: Optional[Callable], timeout: int = 300):
        # Simplified monitor: on Windows, ShellExecute fire-and-forgets to the default viewer/spooler.
        logger.info(f"Windows job {job_id} dispatched. Assuming success after 10 seconds.")
        time.sleep(10)
        if on_success: on_success()

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
                # FIXED: Passed "" instead of None for the parameters argument
                win32api.ShellExecute(0, "print", abs_path, "", ".", 0)
                time.sleep(1) # Give spooler time to ingest
                
            # Restore default
            win32print.SetDefaultPrinter(old_default)
            
            job_id = f"WIN-{int(time.time())}"
            monitor_thread = threading.Thread(target=self._monitor_windows_job, args=(job_id, printer_name, on_success, on_failure), daemon=True)
            monitor_thread.start()
            
            return job_id
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