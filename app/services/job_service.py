import logging
from pathlib import Path
from typing import Dict, Any
from concurrent.futures import ThreadPoolExecutor

from app.core.config import config
from app.models.job_model import JobModel

logger = logging.getLogger(__name__)


class JobService:
    """
    Orchestrates the complete lifecycle of a print job:
    Cloud Pull → DB Register → File Download → Integrity Check →
    File Staging → Print Dispatch → Cloud Update
    """

    def __init__(self, api_client, printer_service, storage_service, queue_service, job_repo):
        self.api_client = api_client
        self.printer_service = printer_service
        self.storage_service = storage_service
        self.queue_service = queue_service
        self.job_repo = job_repo
        self.executor = ThreadPoolExecutor(
            max_workers=config.MAX_WORKERS, thread_name_prefix="JobWorker"
        )

    def process_pending_jobs(self) -> int:
        """
        Pulls and processes jobs one-by-one from the cloud queue.
        The backend atomically locks each job so no other agent can grab it.
        Returns the number of jobs submitted for processing.
        """
        jobs_processed = 0

        while True:
            try:
                response = self.api_client.pull_next_job()
            except Exception as e:
                logger.error(f"Error pulling next job: {e}")
                break

            if not response or response.get("status") == "idle":
                break  # Queue is empty. Exit the loop until the next polling cycle.

            job_data = response.get("job")
            if job_data:
                logger.info(f"Locked job {job_data['id']} from cloud queue.")
                # Pass to the thread pool so we can instantly pull the next job!
            self.executor.submit(self._handle_single_job, job_data)
            jobs_processed += 1

        return jobs_processed

    def recover_interrupted_jobs(self) -> None:
        """
        Runs on agent startup. Finds jobs that were interrupted by a power loss
        and checks the cloud to see if they should be resumed or abandoned.
        """
        stuck_jobs = self.job_repo.get_interrupted_jobs()

        if not stuck_jobs:
            return

        logger.info(f"Recovering {len(stuck_jobs)} interrupted job(s)...")

        for job in stuck_jobs:
            job_id = job.job_id
            file_path_str = job.file_path

            cloud_job = self.api_client.get_job_details(job_id)

            if not cloud_job:
                logger.warning(
                    f"Could not verify job {job_id} with cloud. Leaving in queue for next cycle."
                )
                continue

            cloud_status = cloud_job.get("status")

            # The backend already refunded/failed the job during outage
            if cloud_status in ("failed", "cancelled", "refunded"):
                logger.warning(
                        f"Job {job_id} was cancelled by backend during power outage. Scrapping local print."
                 
                )
                self.job_repo.update_status(job_id, cloud_status)
                # Safely move the file to the failed directory if it exists
                if file_path_str and Path(file_path_str).exists():
                    try:
                        Path(file_path_str).rename(
                            config.JOB_FAILED_DIR / Path(file_path_str).name
                        )
                    except PermissionError:
                        logger.error(f"Permission denied when trying to move job file {job_id}.")
                        continue
                    except Exception as e:
                        logger.warning(f"Failed to move job file to failed directory: {e}")
                        continue
                if file_path_str:
                    fp = Path(file_path_str)
                    if fp.exists():
                        try:
                            fp.rename(config.JOB_FAILED_DIR / fp.name)
                        except Exception:
                            pass

            elif cloud_status in ("printing", "downloading", "pending"):
                logger.info(
                    f"Job {job_id} is still valid in the cloud. Marking as failed to prevent double-prints."
                    )
                    # Safest MVP approach: Fail it and let the user try again.
                    # If we blindly resend to CUPS, CUPS might have also saved it during the outage, causing 2 copies to print!
                self._fail_job(
                    job_id, "Agent experienced a power loss during processing."
                )

    def _handle_single_job(self, job_data: Dict[str, Any]) -> None:
        """Walks a single job through the entire download and print pipeline."""
        # Map the dictionary to our strict model
        job = JobModel.from_api_response(job_data)

        # Validation: Ensure all required IDs are present
        if not job.is_valid():
            logger.error(f"Malformed job data received: {job_data}")
            return

        if not getattr(job, "file_url", None):
            logger.error(f"Job {job.job_id} has no file_url. Cannot download.")
            self._fail_job(job.job_id, "No file URL provided by backend.")
            return

        # Register job in local database
        self.job_repo.save(job)

        # Mark as downloading in local database
        self.job_repo.update_status(job.job_id, "downloading")

        # Notify cloud we are downloading
        self.api_client.update_job_status(str(job.job_id), "downloading")

        # Download the file
        download_path = config.JOB_DOWNLOAD_DIR / f"{job.job_id}.pdf"
        success = self.api_client.download_job_file(job.file_url, str(download_path))
        if not success:
            self._fail_job(str(job.job_id), "Failed to download file from cloud.")
            return

        # Verify file integrity
        if getattr(job, "expected_hash", None):
            if not self.storage_service.verify_download(download_path, job.expected_hash):
                self.storage_service.cleanup_failed_download(f"{job.job_id}.pdf")
                self._fail_job(job.job_id, "File integrity check failed (hash mismatch).")
                return

        # Move it to the ready folder securely
        filename = f"{job.job_id}.pdf"
        ready_path = self.storage_service.transition_job_file(filename, "download", "ready")
        if not ready_path:
            self._fail_job(str(job.job_id), "Failed to move file to ready directory.")
            return
        # Explicitly move to printing folder before dispatching
        printing_path = self.storage_service.transition_job_file(filename, "ready", "printing")
        if not printing_path:
            self._fail_job(job.job_id, "Failed to stage file to printing directory.")
            return

        # Update local database
        self.job_repo.update_status(job.job_id, "printing")
        self.job_repo.update_file_path(job.job_id, str(printing_path))

        # Update cloud and queue event if status update fails
        cloud_job_status_update = self.api_client.update_job_status(job.job_id, "printing")
        if not cloud_job_status_update:
            self.queue_service.enqueue_event(
                job.job_id, "status_update", {"status": "printing"}
            )

        # Dispatch to printer with callbacks
        def on_print_success():
            self.storage_service.transition_job_file(filename, "printing", "completed")
            self._complete_job(str(job.job_id))

        def on_print_failure(reason: str):
            self.storage_service.transition_job_file(filename, "printing", "failed")
            self._fail_job(str(job.job_id), reason)

        # Dispatch to physical printer
        self.printer_service.dispatch_job(
            job_id=job.job_id,
            cloud_printer_uuid=job.printer_id,
            file_path=printing_path,
            copies=getattr(job, "copies", 1),
            is_color=getattr(job, "is_color", False),
            on_success=on_print_success,
            on_failure=on_print_failure,
        )

    # Cloud helpers
    def _fail_job(self, job_id: str, reason: str) -> None:
        """Marks a job as failed locally and in the cloud."""
        logger.error(f"Job {job_id} failed: {reason}")
        self.job_repo.update_status(job_id, "failed")
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
        self.job_repo.update_status(job_id, "completed")
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
        self.executor.shutdown(wait=True, cancel_futures=False) 
        logger.info("JobService shutdown complete.")