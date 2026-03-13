import logging
from pathlib import Path
from typing import Dict, Any

from app.core.config import config
from app.core.local_agent_db import LocalAgentDB
from app.repositories.agent_repo import AgentRepository
from app.services.api_client_service import APIClientService
from app.services.printer_service import PrinterService
from app.services.storage_service import StorageService

logger = logging.getLogger(__name__)


class JobService:
    """
    Orchestrates the complete lifecycle of a print job:
    Cloud API -> Database -> File Download -> Print Dispatch -> Cloud Update
    """

    def __init__(self, api_client=APIClientService()):
        self.api_client = api_client
        self.printer_service = PrinterService()
        self.storage_service = StorageService()

    def process_pending_jobs(self) -> None:
        """Fetches and processes all pending jobs from the cloud."""
        jobs = self.api_client.fetch_pending_jobs()

        if not jobs:
            return  # No jobs to process

        logger.info(f"Found {len(jobs)} pending jobs from the cloud.")

        for job_data in jobs:
            self._handle_single_job(job_data)

    def recover_interrupted_jobs(self) -> None:
        """
        Runs on agent startup. Finds jobs that were interrupted by a power loss
        and checks the cloud to see if they should be resumed or abandoned.
        """
        try:
            with LocalAgentDB.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT * FROM jobs WHERE status IN ('downloading', 'printing')"
                )
                stuck_jobs = cursor.fetchall()

            for row in stuck_jobs:
                job_id = row["job_id"]
                file_path_str = row.get("file_path")

                # 1. Ask the Cloud for the real status
                cloud_job = self.api_client.get_job_details(job_id)

                if not cloud_job:
                    logger.warning(
                        f"Could not verify job {job_id} with cloud. Leaving in queue for next cycle."
                    )
                    continue

                cloud_status = cloud_job.get("status")

                # 2. SCENARIO A: The backend already refunded/failed the job
                if cloud_status in ["failed", "cancelled", "refunded"]:
                    logger.warning(
                        f"Job {job_id} was cancelled by backend during power outage. Scrapping local print."
                    )
                    self._update_db_status(job_id, "failed")

                    # Safely move the file to the failed directory if it exists
                    if file_path_str:
                        Path(file_path_str).rename(
                            config.JOB_FAILED_DIR / Path(file_path_str).name
                        )

                # 3. SCENARIO B: The backend still thinks it's printing (Short power outage)
                elif cloud_status == "printing":
                    logger.info(
                        f"Job {job_id} is still valid in the cloud. Marking as failed to prevent double-prints."
                    )
                    # Safest MVP approach: Fail it and let the user try again.
                    # If we blindly resend to CUPS, CUPS might have also saved it during the outage, causing 2 copies to print!
                    self._fail_job(
                        job_id, "Agent experienced a power loss during processing."
                    )

        except Exception as e:
            logger.error(f"Error recovering interrupted jobs: {e}")

    def _handle_single_job(self, job_data: Dict[str, Any]) -> None:
        """Walks a single job through the entire download and print pipeline."""
        job_id = job_data.get("id")
        printer_name = job_data.get("printer_name")
        file_url = job_data.get("file_url")
        copies = job_data.get("copies", 1)
        is_color = job_data.get("is_color", False)

        if not all([job_id, printer_name, file_url]):
            logger.error(f"Malformed job data received: {job_data}")
            return

        # 1. Register job in local database
        self._register_job_in_db(str(job_id), str(printer_name))

        # 2. Notify cloud we are downloading
        self.api_client.update_job_status(str(job_id), "downloading")

        # 3. Download the file
        if not isinstance(file_url, str) or not job_id or not printer_name:
            logger.error(f"Invalid job data: {job_data}")
            return

        file_ext = file_url.split(".")[-1][:4] if "." in file_url else "pdf"
        download_path = config.JOB_DOWNLOAD_DIR / f"{job_id}.{file_ext}"

        success = self.api_client.download_job_file(str(file_url), str(download_path))
        if not success:
            self._fail_job(str(job_id), "Failed to download file from cloud.")
            return

        # 4. Verify the file isn't corrupted!
        expected_hash = job_data.get(
            "sha256_hash"
        )  # Assuming your cloud API sends this
        if not self.storage_service.verify_download(download_path, str(expected_hash)):
            self.storage_service.cleanup_failed_download(download_path.name)
            self._fail_job(str(job_id), "File download was corrupted.")
            return

        # 5. Move it to the ready folder securely
        ready_path = self.storage_service.transition_job_file(
            download_path.name, "download", "ready"
        )
        if not ready_path:
            self._fail_job(str(job_id), "Failed to prepare file for printing.")
            return

        # 6. Move to 'ready' directory
        ready_path = config.JOB_READY_DIR / download_path.name
        download_path.rename(ready_path)

        # 7. Notify cloud we are printing
        self._update_db_status(str(job_id), "printing")
        self.api_client.update_job_status(str(job_id), "printing")

        # 8. Dispatch to physical printer
        print_success = self.printer_service.dispatch_job(
            str(job_id), str(printer_name), ready_path, copies, is_color
        )

        # 9. Finalize status
        if print_success:
            self._complete_job(str(job_id))
        else:
            self._fail_job(str(job_id), f"Failed to print to {printer_name}.")

    # --- Database & Status Helpers ---

    def _register_job_in_db(self, job_id, printer_id):
        """Inserts a new job record into the local SQLite DB."""
        sql = """
            INSERT OR IGNORE INTO jobs (job_id, printer_id, status) 
            VALUES (?, ?, ?)
        """
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (job_id, printer_id))
                conn.commit()
        except Exception as e:
            logger.error(f"DB Error registering job {job_id}: {e}")

    def _update_db_status(self, job_id: str, status: str) -> None:
        """Updates the local job state."""
        sql = "UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?"
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (status, job_id))
                conn.commit()
        except Exception as e:
            logger.error(f"DB Error updating job {job_id}: {e}")

    def _fail_job(self, job_id: str, reason: str) -> None:
        """Marks a job as failed locally and in the cloud."""
        logger.error(f"Job {job_id} failed: {reason}")
        self._update_db_status(job_id, "failed")
        self.api_client.update_job_status(job_id, "failed", details=reason)

    def _complete_job(self, job_id: str) -> None:
        """Marks a job as completely successful locally and in the cloud."""
        logger.info(f"Job {job_id} completed successfully.")
        self._update_db_status(job_id, "completed")
        self.api_client.update_job_status(job_id, "completed")
