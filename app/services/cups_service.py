import subprocess
import logging
import time
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)


class CUPSManager:
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

                        printers.append(
                            {
                                "id": printer_name,
                                "name": printer_name,
                                "status": status,
                                "raw_status": status_str,
                            }
                        )
            return printers

        except FileNotFoundError:
            logger.error("CUPS commands not found. Is CUPS installed on this system?")
            return []
        except subprocess.CalledProcessError as e:
            logger.error(f"Failed to query printers: {e.stderr}")
            return []

    def wait_for_job_completion(self, os_job_id: str, timeout: int = 300) -> bool:
        start_time = time.time()
        while time.time() - start_time < timeout:
            # Check if job is still in the queue
            result = subprocess.run(
                ["lpstat", "-W", "completed", "-j", os_job_id],
                capture_output=True,
                text=True,
            )
            if "completed" in result.stdout.lower():
                return True

            # Check for errors/jams in the active queue
            active = subprocess.run(["lpstat", "-p"], capture_output=True, text=True)
            if (
                "out of paper" in active.stdout.lower()
                or "jam" in active.stdout.lower()
            ):
                return False

            time.sleep(2)  # Poll every 2 seconds
        return False  # Timeout

    def print_file(
        self,
        printer_name: str,
        file_path: str,
        title: str = "Inkify_Job",
        copies: int = 1,
        is_color: bool = False,
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
                # Check if it actually printed!
                success = self.wait_for_job_completion(os_job_id, 300)

                if success:
                    return os_job_id
                else:
                    logger.error(
                        f"Job {os_job_id} failed to complete in OS queue (Timeout or Jam)."
                    )
                    return None

            return "unknown_job_id"

        except subprocess.CalledProcessError as e:
            logger.error(
                f"OS failed to print file {file_path} to {printer_name}. Error: {e.stderr}"
            )
            return None
