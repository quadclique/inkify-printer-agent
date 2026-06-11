import json
import logging
from typing import Dict, Any

from app.core.config import config
from app.models.queue_model import QueueEventModel

logger = logging.getLogger(__name__)

class QueueService:
    """
    Hybrid Offline Resilience.
    Uses atomic File-Based Queueing for thread-safe execution, 
    and SQLite for a persistent, queryable audit ledger.
    """

    def __init__(self, api_client, storage_service, queue_repo):
        self.api_client = api_client
        self.storage_service = storage_service
        self.queue_repo = queue_repo

    def enqueue_event(
        self, job_id: str, event_type: str, payload: Dict[str, Any]
    ) -> None:
        try:
            event = QueueEventModel(
                job_id=job_id,
                event_type=event_type,
                payload=payload
            )
            [event_id, success] = self.queue_repo.add_event(event)

            if not success:
                logger.error(f"Failed to save event to database for job {job_id}")
                return

            logger.debug(f"Queued '{event_type}' event for job {job_id} offline.")

            # Ensure directory exists before writing
            config.QUEUE_PENDING_DIR.mkdir(parents=True, exist_ok=True)

            # 2. EXECUTION: Write the physical file
            filename = f"{event_id}_{job_id}_{event_type}.json"
            filepath = config.QUEUE_PENDING_DIR / filename

            event_data = {
                "event_id": event_id,
                "job_id": job_id,
                "event_type": event_type,
                "payload": payload
            }

            try:
                with open(filepath, "w") as f:
                    json.dump(event_data, f)
                
                logger.info(f"📥 EVENT QUEUED: {filename} [PENDING]")
            except Exception as e:
                logger.error(f"Failed to write physical queue file {filename}: {e}. Rolling back database entry.")
                self.queue_repo.delete_event(event_id)
            
        except Exception as e:
            logger.error(f"Failed to write queue event for job {job_id}: {e}")

    def process_queue(self) -> None:
        if not config.QUEUE_PENDING_DIR.exists():
            return

        # Sort pending files numerically by event_id to process oldest first
        pending_files = sorted(
            [f for f in config.QUEUE_PENDING_DIR.iterdir() if f.is_file() and f.name.endswith(".json")],
            key=lambda f: int(f.name.split('_')[0]) if f.name.split('_')[0].isdigit() else 0
        )

        if not pending_files:
            return

        for filepath in pending_files:
            filename = filepath.name

            # 1. ATOMIC LOCK: Move to Processing using StorageService
            processing_path = self.storage_service.transition_queue_file(filename, "pending", "processing")
            
            if not processing_path:
                continue # Another thread safely locked it!

            try:
                # 2. Read the payload
                with open(processing_path, "r") as f:
                    data = json.load(f)
                
                event_id = data.get("event_id")
                job_id = data.get("job_id")
                event_type = data.get("event_type")
                payload = data.get("payload")

                # 3. Attempt to dispatch to the cloud
                success = self._dispatch_event(job_id, event_type, payload)

                if success:
                    # Success -> Move file & Update DB
                    self.storage_service.transition_queue_file(filename, "processing", "completed")
                    self.queue_repo.mark_as_synced(event_id)
                else:
                    # Network Down -> Move back to Pending
                    self.storage_service.transition_queue_file(filename, "processing", "pending")
                    logger.warning(f"⏳ EVENT DELAYED: {filename} (Network offline)")
                    break

            except Exception as e:
                # SCENARIO C: File corrupted -> Move to Failed
                logger.error(f"Error processing queued event {filename}: {e}")
                self.storage_service.transition_queue_file(filename, "processing", "failed")

    def _dispatch_event(
        self, job_id: str, event_type: str, payload: Dict[str, Any]
    ) -> bool:
        if event_type == "status_update":
            status = payload.get("status")
            details = payload.get("details", "")
            try:
                return self.api_client.update_job_status(job_id, str(status), details)
            except Exception as e:
                logger.warning(f"Network error dispatching queue event {event_type} for job {job_id}: {e}")
                return False

        logger.error(f"Unknown event type in queue: {event_type}")
        return True
