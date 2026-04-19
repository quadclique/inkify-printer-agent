import logging
import os
from pathlib import Path
from typing import Optional
from app.core.config import config

logger = logging.getLogger(__name__)

class PrinterService:
    """
    High-level business logic for handling physical printers.
    Validates files, checks printer availability, and dispatches jobs to the OS.
    """

    def __init__(self, api_client, printer_manager, printer_repo, storage_service):
        self.api_client = api_client
        self.printer_manager = printer_manager
        self.printer_repo = printer_repo
        self.storage_service = storage_service

    def get_available_printers(self) -> list:
        """Fetches a list of all installed printers on the host machine."""
        logger.debug("Fetching local printers...")
        return self.printer_manager.get_printers()
        
    def get_printer_name_by_cloud_uuid(self, cloud_uuid: str) -> Optional[str]:
        """Translates a Cloud UUID back to the printer's physical CUPS name."""
        printer_map = self.printer_repo.get_printer_map()
        # printer_map 
        for printer_name, mapped_uuid in printer_map.items():
            if mapped_uuid == cloud_uuid:
                return printer_name
        return None

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
        cloud_printer_uuid: str,
        file_path: Path,
        copies: int,
        is_color: bool,
        on_success,
        on_failure
    ) -> bool:
        """
        Sends a downloaded file to the local OS printer queue.
        Moves the file through the local state directories (ready -> printing).
        """
        if not file_path.exists():
            logger.error(f"Cannot print job {job_id}: File not found at {file_path}")
            return False
        
        printer_name = self.get_printer_name_by_cloud_uuid(cloud_printer_uuid)

        if not printer_name:
            logger.error(f"Cannot dispatch job: Unknown Cloud UUID '{cloud_printer_uuid}'. Is the printer mapped?")
            return False
        
        if not self.is_printer_ready(printer_name):
            logger.error(
                f"Cannot dispatch job {job_id}: Printer '{printer_name}' is offline."
            )
            return False

        try:
            logger.info(f"Dispatching job {job_id} to printer {printer_name}...")

            # Move file to 'printing' directory
            printing_path = self.storage_service.transition_job_file(file_path.name, "ready", "printing")

            if not printing_path:
                raise Exception("Failed to transition file to printing directory.")
            
            # OS Level Print Command
            success_job_id = self.printer_manager.print_file_async(
                printer_name=printer_name,
                file_path=str(printing_path),
                title=f"Inkify_{job_id}",
                copies=copies,
                is_color=is_color,
                on_success=on_success,
                on_failure=on_failure
            )

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
            if on_failure:
                on_failure(str(e))
                
            return False

    def sync_printers_with_cloud(self):
        """Scans local hardware and registers/updates them on the backend."""
        if not self.api_client:
            logger.error("API Client not provided for sync.")
            return
        
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
        response = self.api_client.sync_printers(payload)
        
        if response and isinstance(response, dict):
            # Handle if backend wraps in "printers" key or returns direct map
            cloud_map = response.get("printers", response) if "printers" in response else response
            self.printer_repo.save_printer_map(cloud_map)
            logger.info(f"Synced {len(cloud_map)} printers.")
            
    def check_for_hardware_changes(self):
        """Point 11: Auto-discovery check"""
        current_local = self.printer_manager.get_printers()
        # If hardware count changed, trigger sync
        if len(current_local) != len(self.printer_repo.get_printer_map()):
            logger.info("New hardware detected. Re-syncing...")
            self.sync_printers_with_cloud()