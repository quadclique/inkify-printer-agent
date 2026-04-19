import subprocess
import logging
import time
import threading
from typing import List, Dict, Optional, Callable
from app.platform.base import BasePrinterManager

logger = logging.getLogger(__name__)


class UnixPrinterManager(BasePrinterManager):
    """CUPS implementation for Linux and macOS."""
    """
    Low-level interface for interacting with the local OS printing system (CUPS).
    Uses native shell commands (`lp`, `lpstat`) for maximum compatibility on Unix.
    """

    def get_printers(self) -> List[Dict[str, str]]:
        """
        Queries the OS for all available printers and their current status.
        Uses `lpstat -p` which outputs lines like: 'printer HP_LaserJet is idle...'
        """
        printers = []
        try:
            # Run the lpstat command and capture the output
            result = subprocess.run(
                ["lpstat", "-p"], capture_output=True, text=True, check=True
            )
            lines = result.stdout.splitlines()

            for line in lines:
                if line.startswith("printer"):
                    parts = line.split()
                    if len(parts) >= 4:
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

                        caps = self.get_printer_capabilities(printer_name)

                        printers.append(
                            {
                                "id": printer_name,
                                "name": printer_name,
                                "status": status,
                                "raw_status": status_str,
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

    def get_printer_capabilities(self, printer_name: str) -> Dict[str, bool]:
        try:
            result = subprocess.run(
                ["lpoptions", "-p", printer_name, "-l"],
                capture_output=True,
                text=True,
            )

            output = result.stdout.lower()

            return {
                "supports_color": "color" in output,
                "supports_duplex": "duplex" in output,
            }

        except Exception:
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
    ) -> bool:
        """
        Runs invisibly in the background. Executes callbacks based on hardware states.
        """
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check if job is still in the queue
            result = subprocess.run(
                ["lpstat", "-W", "completed"],
                capture_output=True,
                text=True,
            )

            if os_job_id in result.stdout.lower():
                logger.info(f"Job {os_job_id} finished printing successfully.")
                if on_success:
                    on_success()
                return True

            # Check for errors/jams in the active queue
            active = subprocess.run(["lpstat", "-p"], capture_output=True, text=True)
            if (
                "out of paper" in active.stdout.lower()
                or "jam" in active.stdout.lower()
            ):
                logger.warning(
                    f"Printer attention required for {os_job_id} (Jam/Empty). Waiting for resolution..."
                )
                return False

            time.sleep(2)  # Poll every 2 seconds

        error_msg = f"Job {os_job_id} timed out after {timeout} seconds in OS queue."
        logger.error(error_msg)
        if on_failure:
            on_failure(error_msg)
        return False  # Timeout

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

            result = subprocess.run(cmd, capture_output=True, text=True, check=True)

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
                )
                monitor_thread.start()

                return os_job_id

            error_msg = f"Job failed to complete in OS queue (Timeout or Jam)."

            if on_failure:
                logger.error(error_msg)
            return None

        except subprocess.CalledProcessError as e:
            error_msg = f"OS failed to print file {file_path} to {printer_name}. Error: {e.stderr}"
            logger.error(error_msg)
            # Instantly trigger the failure callback if the command aborts
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
            subprocess.run(
                ["cancel", "-a", printer_name], check=True, capture_output=True
            )
            logger.info(f"Successfully cleared print queue for {printer_name}.")
            return True
        except subprocess.CalledProcessError as e:
            # This often triggers simply because the queue is already empty, which is fine.
            logger.debug(
                f"Queue clear skipped or failed for {printer_name} (Queue might already be empty)."
            )
            return False
