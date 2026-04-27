import json
import logging
from typing import Dict, Any

from app.core.config import config
from app.core.local_agent_db import LocalAgentDB

logger = logging.getLogger(__name__)

class QueueService:
    """
    Hybrid Offline Resilience.
    Uses atomic File-Based Queueing for thread-safe execution, 
    and SQLite for a persistent, queryable audit ledger.
    """

    def __init__(self, api_client, storage_service):
        self.api_client = api_client
        self.storage_service = storage_service

    def enqueue_event(
        self, job_id: str, event_type: str, payload: Dict[str, Any]
    ) -> None:
        try:
            payload_str = json.dumps(payload)
            """
            Saves an event to the local database to be synced with the cloud later.
            """
            sql = """
                INSERT INTO queue_events (job_id, event_type, payload, synced)
                VALUES (?, ?, ?, 0)
            """
            with LocalAgentDB.get_connection() as conn:
                cursor = conn.execute(sql, (job_id, event_type, payload_str))
                event_id = cursor.lastrowid
                conn.commit()
            logger.debug(f"Queued '{event_type}' event for job {job_id} offline.")

            # 2. EXECUTION: Write the physical file
            filename = f"{event_id}_{job_id}_{event_type}.json"
            filepath = config.QUEUE_PENDING_DIR / filename

            event_data = {
                "event_id": event_id,
                "job_id": job_id,
                "event_type": event_type,
                "payload": payload
            }

            with open(filepath, "w") as f:
                json.dump(event_data, f)
            
            logger.info(f"📥 EVENT QUEUED: {filename} [PENDING]")
            
        except Exception as e:
            logger.error(f"Failed to write queue event for job {job_id}: {e}")

    def process_queue(self) -> None:
        if not config.QUEUE_PENDING_DIR.exists():
            return

        pending_files = [f for f in config.QUEUE_PENDING_DIR.iterdir() if f.is_file() and f.name.endswith(".json")]

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
                    # SCENARIO A: Success -> Move file & Update DB
                    self.storage_service.transition_queue_file(filename, "processing", "completed")
                    with LocalAgentDB.get_connection() as conn:
                        conn.execute("UPDATE queue_events SET synced = 1 WHERE event_id = ?", (event_id,))
                        conn.commit()
                else:
                    # SCENARIO B: Network Down -> Move back to Pending
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
            return self.api_client.update_job_status(job_id, str(status), details)

        logger.error(f"Unknown event type in queue: {event_type}")
        return True
