import json
import logging
from typing import Dict, Any

from app.core.local_agent_db import LocalAgentDB

logger = logging.getLogger(__name__)


class QueueService:
    """
    Handles offline resilience. If the cloud cannot be reached, events
    (like job completion statuses) are queued locally and re-attempted later.
    """

    def __init__(self, api_client):
        self.api_client = api_client

    def enqueue_event(
        self, job_id: str, event_type: str, payload: Dict[str, Any]
    ) -> None:
        """
        Saves an event to the local database to be synced with the cloud later.
        """
        try:
            payload_str = json.dumps(payload)
            sql = """
                INSERT INTO queue_events (job_id, event_type, payload, synced)
                VALUES (?, ?, ?, 0)
            """
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (job_id, event_type, payload_str))
                conn.commit()
            logger.debug(f"Queued '{event_type}' event for job {job_id} offline.")
        except Exception as e:
            logger.error(f"Failed to enqueue event for job {job_id}: {e}")

    def process_queue(self) -> None:
        """
        Reads all unsynced events from the database and attempts to send them
        to the cloud. If successful, marks them as synced.
        """
        try:
            with LocalAgentDB.get_connection() as conn:
                # Fetch all unsynced events
                cursor = conn.execute(
                    "SELECT * FROM queue_events WHERE synced = 0 ORDER BY created_at ASC"
                )
                unsynced_events = cursor.fetchall()

            if not unsynced_events:
                return  # Nothing to sync

            logger.info(
                f"Attempting to sync {len(unsynced_events)} offline events to the cloud..."
            )

            for event in unsynced_events:
                event_id = event["event_id"]
                job_id = event["job_id"]
                event_type = event["event_type"]
                payload = json.loads(event["payload"])

                success = self._dispatch_event(job_id, event_type, payload)

                if success:
                    # Mark as synced in DB
                    with LocalAgentDB.get_connection() as conn:
                        conn.execute(
                            "UPDATE queue_events SET synced = 1 WHERE event_id = ?",
                            (event_id,),
                        )
                        conn.commit()
                    logger.debug(
                        f"Successfully synced event {event_id} for job {job_id}."
                    )
                else:
                    logger.warning(
                        f"Failed to sync event {event_id}. Will retry on next pass."
                    )
                    # Stop processing the queue if the network is still down to avoid spamming failures
                    break

        except Exception as e:
            logger.error(f"Error processing offline queue: {e}")

    def _dispatch_event(
        self, job_id: str, event_type: str, payload: Dict[str, Any]
    ) -> bool:
        """Routes the queued event to the correct API endpoint."""
        if event_type == "status_update":
            status = payload.get("status")
            details = payload.get("details", "")
            return self.api_client.update_job_status(job_id, str(status), details)

        # Add other event types here in the future (e.g., "printer_error_alert")
        logger.error(f"Unknown event type in queue: {event_type}")
        return (
            True  # Return true so we mark it as "synced" and don't get stuck in a loop
        )
