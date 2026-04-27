import logging
from pathlib import Path
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor

from app.core.config import config
from app.core.local_agent_db import LocalAgentDB

from app.models.job_model import JobModel

logger = logging.getLogger(__name__)


class JobService:
    """
    Orchestrates the complete lifecycle of a print job:
    Cloud API -> Database -> File Download -> Print Dispatch -> Cloud Update
    """

    def __init__(self, api_client, printer_service, storage_service, queue_service):
        self.api_client = api_client
        self.printer_service = printer_service
        self.storage_service = storage_service
        self.queue_service = queue_service
        self.executor = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)

    # def process_pending_jobs(self) -> None:
    #     """Fetches and processes all pending jobs from the cloud."""
    #     jobs = self.api_client.fetch_pending_jobs()

    #     if not jobs:
    #         return  # No jobs to process

    #     logger.info(f"Found {len(jobs)} pending jobs from the cloud.")

    #     for job_data in jobs:
    #         self.executor.submit(self._handle_single_job, job_data)

    def process_pending_jobs(self) -> None:
        """Pulls and locks jobs one-by-one from the cloud until the queue is empty."""
        while True:
            response = self.api_client.pull_next_job()

            if not response or response.get("status") == "idle":
                break  # Queue is empty. Exit the loop until the next polling cycle.

            job_data = response.get("job")
            if job_data:
                logger.info(f"Locked job {job_data['id']} from cloud queue.")
                # Pass to the thread pool so we can instantly pull the next job!
                self.executor.submit(self._handle_single_job, job_data)
                
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
                file_path_str = row["file_path"]

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
        # Map the dictionary to our strict model
        job = JobModel.from_api_response(job_data)

        # Validation: Ensure all required IDs are present
        if not all([job.job_id, job.printer_id, job.document_id]):
            logger.error(
                f"Malformed job data: Required IDs missing",
                extra={"job_data": job_data},
            )
            return

        
        # Notify cloud we are downloading
        # self.api_client.update_job_status(str(job.job_id), "downloading")

        # Download the file using document_id
        download_path = config.JOB_DOWNLOAD_DIR / f"{job.job_id}.pdf"

        # success = self.api_client.download_job_file(
        #     str(job.document_id), str(download_path)
        # )
        
        # Register job in local database
        self._register_job_in_db(str(job.job_id), str(job.printer_id), str(download_path))
        
        success = self.api_client.download_job_file(job.file_url, str(download_path))

        if not success:
            self._fail_job(str(job.job_id), "Failed to download file from cloud.")
            return

        # Verify the file isn't corrupted!
        expected_hash = job_data.get(
            "sha256_hash"
        )  # Assuming your cloud API sends this
        if job.expected_hash and not self.storage_service.verify_download(download_path, str(expected_hash)):
            self.storage_service.cleanup_failed_download(download_path.name)
            self._fail_job(str(job.job_id), "File download was corrupted.")
            return

        # Move it to the ready folder securely
        ready_path = self.storage_service.transition_job_file(
            download_path.name, "download", "ready"
        )
        if not ready_path:
            self._fail_job(str(job.job_id), "Failed to prepare file for printing.")
            return

        # Explicitly move to printing folder before dispatching
        printing_path = self.storage_service.transition_job_file(
            download_path.name, "ready", "printing"
        )
        if not printing_path:
            self._fail_job(str(job.job_id), "Failed to move file to printing directory.")
            return

        # Notify cloud we are printing
        self._update_db_status(str(job.job_id), "printing")
        self._update_db_filepath(str(job.job_id), str(printing_path))
        
        success = self.api_client.update_job_status(str(job.job_id), "printing")

        if not success:
            self.queue_service.enqueue_event(
                job.job_id, "status_update", {"status": "printing"}
            )
            
        def on_print_success():
            self.storage_service.transition_job_file(download_path.name, "printing", "completed")
            self._complete_job(str(job.job_id))
            
        def on_print_failure(reason):
            self.storage_service.transition_job_file(download_path.name, "printing", "failed")
            self._fail_job(str(job.job_id), reason)
            
        # Dispatch to physical printer
        self.printer_service.dispatch_job(
            str(job.job_id), str(job.printer_id), printing_path, job.copies, job.is_color, on_success=on_print_success, on_failure=on_print_failure
        )


    # --- Database & Status Helpers ---

    def _register_job_in_db(self, job_id, printer_id, file_path):
        """Inserts a new job record into the local SQLite DB."""
        sql = """
            INSERT OR IGNORE INTO jobs (job_id, printer_id, status, file_path) 
            VALUES (?, ?, ?, ?)
        """
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (job_id, printer_id, "pending", file_path))
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
    
    def _update_db_filepath(self, job_id: str, file_path: str) -> None:
        sql = "UPDATE jobs SET file_path = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?"
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (file_path, job_id))
                conn.commit()
        except Exception as e:
            logger.error(f"DB Error updating filepath for job {job_id}: {e}") 
            
    def _fail_job(self, job_id: str, reason: str) -> None:
        """Marks a job as failed locally and in the cloud."""
        logger.error(f"Job {job_id} failed: {reason}")
        self._update_db_status(job_id, "failed")
        
        try:
            # This will retry 3 times, then raise an Exception if the network is dead
            success = self.api_client.update_job_status(job_id, "failed", details=reason)
        except Exception as e:
            logger.warning(f"Network offline. Deferring failure status to offline queue.")
            success = False # Force success to False so the queue triggers
        
        if not success:
            self.queue_service.enqueue_event(
                job_id, "status_update", {"status": "failed", "details": reason}
            )
            
    def _complete_job(self, job_id: str) -> None:
        """Marks a job as completely successful locally and in the cloud."""
        logger.info(f"Job {job_id} completed successfully.")
        self._update_db_status(job_id, "completed")
        try: 
            # This will retry 3 times, then raise an Exception if the network is dead
            success = self.api_client.update_job_status(job_id, "completed")
        except Exception as e:
            logger.warning(f"Network offline. Deferring completion status to offline queue.")
            success = False # Force success to False so the queue triggers

        if not success:
            self.queue_service.enqueue_event(
                job_id, "status_update", {"status": "completed"}
            )

    def shutdown(self) -> None:
        """
        Gracefully shuts down the thread pool. 
        Waits for active downloads/dispatches to finish before exiting.
        """
        logger.info("Shutting down JobService. Waiting for active jobs to wrap up...")
        # wait=True ensures we don't sever active network connections mid-download
        self.executor.shutdown(wait=True, cancel_futures=True) 
        logger.info("JobService shutdown complete.")