import logging
import os
from pathlib import Path
from app.core.config import config

# Assuming you have a lower-level wrapper for CUPS or Windows Spooler
from app.services.cups_service import CUPSManager
from app.repositories.agent_repo import AgentRepository

logger = logging.getLogger(__name__)


class PrinterService:
    """
    High-level business logic for handling physical printers.
    Validates files, checks printer availability, and dispatches jobs to the OS.
    """

    def __init__(self):
        self.cups = CUPSManager()
        pass

    def get_available_printers(self) -> list:
        """Fetches a list of all installed printers on the host machine."""
        logger.debug("Fetching local printers...")
        # Mocking the response for now
        return self.cups.get_printers()
        

    def is_printer_ready(self, printer_name: str) -> bool:
        """Checks if a specific printer is currently online and ready to accept jobs."""
        printers = self.get_available_printers()
        for p in printers:
            if p["name"] == printer_name:
                return p["status"] == "idle"
        logger.warning(f"Printer '{printer_name}' not found or not ready.")
        return False

    def dispatch_job(
        self,
        job_id: str,
        printer_name: str,
        file_path: Path,
        copies: int,
        is_color: bool,
    ) -> bool:
        """
        Sends a downloaded file to the local OS printer queue.
        Moves the file through the local state directories (ready -> printing).
        """
        if not file_path.exists():
            logger.error(f"Cannot print job {job_id}: File not found at {file_path}")
            return False

        if not self.is_printer_ready(printer_name):
            logger.error(
                f"Cannot dispatch job {job_id}: Printer '{printer_name}' is offline."
            )
            return False

        try:
            logger.info(f"Dispatching job {job_id} to printer {printer_name}...")

            # Move file to 'printing' directory
            printing_path = config.JOB_PRINTING_DIR / file_path.name
            os.rename(file_path, printing_path)

            # --- OS Level Print Command Goes Here ---
            success_job_id = self.cups.print_file(
                printer_name, str(printing_path), title=f"Inkify_{job_id}"
            )
            # success_job_id = 12345  # Mock CUPS job ID

            if success_job_id:
                logger.info(
                    f"Successfully sent job {job_id} to {printer_name} (OS Job ID: {success_job_id})"
                )

                # Move to completed directory
                completed_path = config.JOB_COMPLETED_DIR / file_path.name
                os.rename(printing_path, completed_path)
                return True
            else:
                raise Exception("OS rejected the print command.")

        except Exception as e:
            logger.error(f"Failed to print job {job_id}: {e}")

            # Move to failed directory so it isn't lost, but isn't stuck in processing
            if "printing_path" in locals() and printing_path.exists():
                failed_path = config.JOB_FAILED_DIR / file_path.name
                os.rename(printing_path, failed_path)

            return False

    def sync_printers_with_cloud(self, api_client):
        """Scans local hardware and registers/updates them on the backend."""
        local_printers = self.get_available_printers() 
        
        # Format for API: List of dicts with name and capabilities
        payload = []
        for p in local_printers:
            payload.append({
                "name": p["name"],
                "hardware_id": p["name"],  # For CUPS, the queue name is the hardware ID
                "is_online": p["status"] in ["idle", "printing"],
                "supports_color": p.get("supports_color", False),
                "supports_duplex": p.get("supports_duplex", False)
            })
        
        # Call the new sync endpoint (to be added to APIClientService)
        cloud_map = api_client.sync_printers(payload)
        
        if cloud_map:
            # Update the AgentRepository with the new mapping
            from app.repositories.agent_repo import AgentRepository
            repo = AgentRepository()
            config = repo.get_config()
            config.printer_map = cloud_map
            repo.save_config(config)
            logger.info(f"Synced {len(cloud_map)} printers with cloud.")