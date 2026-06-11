import subprocess
import logging
import time
import urllib.parse
import threading
from typing import List, Dict, Optional, Callable
from app.platform.base import BasePrinterManager

logger = logging.getLogger(__name__)


class UnixPrinterManager(BasePrinterManager):
    """
    CUPS implementation for Linux and macOS.
    Low-level interface for interacting with the local OS printing system (CUPS).
    Uses native shell commands (`lp`, `lpstat`) for maximum compatibility on Unix.
    """

    def _run_cmd(self, cmd: List[str], timeout: int = 10, check: bool = False) -> subprocess.CompletedProcess:
        """Helper to run shell commands with standard options."""
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=check
        )

    def get_printers(self) -> List[Dict[str, str]]:
        """
        Queries the OS for all available printers and their current status.
        """
        printers = []
        try:
            # 1. Get URIs (lpstat -v outputs: "device for PrinterName: usb://...")
            uri_map: Dict[str, str] = {}
            try:
                uri_result = self._run_cmd(["lpstat", "-v"], check=True)
                for line in uri_result.stdout.splitlines():
                    if line.startswith("device for"):
                        parts = line.split(":", 1) # Split only on the first colon
                        if len(parts) == 2:
                            name = parts[0].replace("device for ", "").strip()
                            uri = parts[1].strip()
                            uri_map[name] = uri
            except subprocess.CalledProcessError:
                logger.warning("Failed to get printer URIs. Continuing without device URIs.")
            except Exception as e:
                logger.debug(f"Could not read URIs via lpstat -v: {e}")
                
            # 2. Get Statuses (lpstat -p) 
            status_result = self._run_cmd(["lpstat", "-p"], check=True)

            for line in status_result.stdout.splitlines():
                if not line.startswith("printer"):
                    continue
                
                parts = line.split()
                if len(parts) < 4:
                    continue
                    
                printer_name = parts[1]
                # "is idle.", "now printing", "disabled"
                status_str = " ".join(parts[3:]).strip().lower()

                # Normalize status
                if "idle" in status_str:
                    status = "idle"
                elif "printing" in status_str:
                    status = "printing"
                else:
                    status = "offline"
                
                uri = uri_map.get(printer_name, "")
                
                # 3. Extract Connection Type & Hardware Signature
                connection_type = "unknown"
                hardware_signature = printer_name  # Fallback
                
                if uri.startswith("usb"):
                    connection_type = "usb"
                elif uri.startswith(("socket", "ipp", "http", "dnssd", "lpd")):
                    connection_type = "network"

                # Parse the URI to find serial numbers or UUIDs for better hardware identification
                try:
                    parsed_uri = urllib.parse.urlparse(uri)
                    query_params = urllib.parse.parse_qs(parsed_uri.query)
                    
                    if "serial" in query_params:
                        hardware_signature = query_params["serial"][0]
                    elif "uuid" in query_params:
                        hardware_signature = query_params["uuid"][0]
                    elif parsed_uri.netloc:
                        hardware_signature = f"net_{parsed_uri.netloc}_{printer_name}"
                except Exception as e:
                    logger.debug(f"Failed to parse URI {uri}: {e}")
                    
                caps = self.get_printer_capabilities(printer_name)

                printers.append(
                    {
                        "id": printer_name,
                        "name": printer_name,
                        "status": status,
                        "raw_status": status_str,
                        "connection_type": connection_type,
                        "device_uri": uri,
                        "hardware_signature": hardware_signature,
                        "supports_color": caps["supports_color"],
                        "supports_duplex": caps["supports_duplex"],
                    }
                )
            return printers

        except FileNotFoundError:
            logger.error("CUPS commands not found. Is CUPS installed on this system?")
            return []
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to query printers: {e.stderr}")
            return []
        except Exception as e:
            logger.error(f"Unexpected error querying printers: {e}")
            return []

    def get_printer_capabilities(self, printer_name: str) -> Dict[str, bool]:
        """Queries CUPS for printer capabilities (color, duplex)."""
        try:
            result = self._run_cmd(["lpoptions", "-p", printer_name, "-l"], timeout=5)
            output = result.stdout.lower()
            return {
                "supports_color": "color" in output,
                "supports_duplex": "duplex" in output,
            }

        except Exception as e:
            logger.debug(f"Failed to fetch capabilities for {printer_name}: {e}")
            return {
                "supports_color": False,
                "supports_duplex": False,
            }

    def wait_for_job_completion(
        self,
        os_job_id: str,
        on_success: Optional[Callable[[], None]],
        on_failure: Optional[Callable[[str], None]],
        timeout: int = 300,
    ) -> None:
        """
        Background thread: polls CUPS until the job finishes, errors out, or times out.
        """

        start_time = time.time()
        while time.time() - start_time < timeout:
            try:
                # Check if job is still in the queue
                result = self._run_cmd(["lpstat", "-W", "completed"], timeout=5)
                if os_job_id in result.stdout.lower():
                    logger.info(f"Job {os_job_id} completed successfully.")
                    if on_success:
                        on_success()
                    return 

                # Check for errors/jams in the active queue
                active = self._run_cmd(["lpstat", "-p"], timeout=5)
                if (
                    "out of paper" in active.stdout.lower()
                    or "jam" in active.stdout.lower()
                ):
                    logger.warning(
                        f"Printer attention required for {os_job_id} (Jam/Empty). Waiting for resolution..."
                    )
                    time.sleep(5)
                    continue 
                
                # Check if job left the queue without errors
                active_jobs = self._run_cmd(["lpstat"], timeout=5)
                if os_job_id not in active_jobs.stdout:
                    logger.info(f"CUPS job {os_job_id} left the queue. Assuming success.")
                    if on_success:
                        on_success()
                    return
            except Exception as e:
                logger.debug(f"CUPS poll error (transient): {e}")

            time.sleep(2)  # Poll every 2 seconds

        error_msg = f"Job {os_job_id} timed out after {timeout} seconds in OS queue."
        logger.error(error_msg)
        if on_failure:
            on_failure(error_msg)

    def print_file_async(
        self,
        printer_name: str,
        file_path: str,
        title: str = "Inkify_Job",
        copies: int = 1,
        is_color: bool = False,
        on_success: Optional[Callable[[], None]] = None,
        on_failure: Optional[Callable[[str], None]] = None,
    ) -> Optional[str]:
        """
        Dispatches a file to a specific printer using the `lp` command.
        Returns the OS-level Job ID if successful, or None if it fails.
        """
        try:
            # lp -d <printer_name> -t <title> <file_path>
            cmd = ["lp", "-d", printer_name, "-t", title, "-n", str(copies)]

            logger.debug(f"Executing print command: {' '.join(cmd)}")

            # Apply Color or Black & White enforcement
            if is_color:
                # Tell CUPS to print in Color
                cmd.extend(["-o", "ColorModel=Color"])
            else:
                # Force Grayscale. We pass both common flags to ensure
                # maximum compatibility across different printer drivers.
                cmd.extend(["-o", "ColorModel=Gray", "-o", "monochrome"])

            cmd.append(file_path)

            logger.debug(f"Executing print command: {' '.join(cmd)}")

            result = self._run_cmd(cmd, timeout=30, check=True)

            # lp output usually looks like: "request id is HP_LaserJet-123 (1 file(s))"
            output = result.stdout.strip()

            if "request id is" in output:
                # Extract just the job ID part (e.g., "HP_LaserJet-123")
                os_job_id = output.split()[3]
                logger.info(f"Job {os_job_id} dispatched. Starting background monitor.")

                # Check if it actually printed!
                # Spin up a background thread, passing the callbacks
                monitor_thread = threading.Thread(
                    target=self.wait_for_job_completion,
                    args=(os_job_id, on_success, on_failure),
                    daemon=True,
                    name=f"CUPSMonitor-{os_job_id}",

                )
                monitor_thread.start()

                return os_job_id

            error_msg = f"Job failed to complete in OS queue (Timeout or Jam). Unexpected lp output: {output}"
            logger.error(error_msg)

            if on_failure:
                on_failure(error_msg)
            return None

        except subprocess.CalledProcessError as e:
            error_msg = f"OS failed to print file {file_path} to {printer_name}. Error: {e.stderr}"
            logger.error(error_msg)
            # Instantly trigger the failure callback if the command aborts
            if on_failure:
                on_failure(error_msg)
            return None
        except Exception as e:
            error_msg = f"Unexpected error printing to {printer_name}: {e}"
            logger.error(error_msg)
            if on_failure:
                on_failure(error_msg)
            return None

    def clear_queue(self, printer_name: str) -> bool:
        """
        Cancels all pending jobs in the CUPS queue for the specified printer.
        Useful for flushing expired setup codes or stuck jobs.
        """
        try:
            # 'cancel -a <printer>' clears all jobs for that destination
            self._run_cmd(["cancel", "-a", printer_name], timeout=10, check=True)

            logger.info(f"Successfully cleared print queue for {printer_name}.")
            return True
        except subprocess.CalledProcessError as e:
            # This often triggers simply because the queue is already empty, which is fine.
            logger.debug(
                f"Queue clear skipped or failed for {printer_name} (Queue might already be empty)."
            )
            return False
        except Exception as e:
            logger.error(f"Error clearing queue for {printer_name}: {e}")
            return False

