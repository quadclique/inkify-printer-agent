import logging
import json
from typing import List
from app.core.local_agent_db import LocalAgentDB
from app.models.queue_model import QueueEventModel

logger = logging.getLogger(__name__)

class QueueRepository:
    """Handles offline queue events in the local SQLite database."""

    def _row_to_event(self, row) -> QueueEventModel:
        """Helper to safely map a database row to a QueueEventModel."""
        try:
            payload = json.loads(row["payload"])
        except (json.JSONDecodeError, TypeError):
            logger.warning(f"Failed to parse payload JSON for event {row.get('event_id', 'unknown')}")
            payload = {}
            
        return QueueEventModel(
            event_id=row["event_id"],
            job_id=row["job_id"],
            event_type=row["event_type"],
            payload=payload,
            synced=bool(row["synced"]),
            created_at=row["created_at"],
        )

    def add_event(self, event: QueueEventModel) -> List:
        """Inserts a new queue event to be synced later."""
        sql = """
            INSERT INTO queue_events (job_id, event_type, payload, synced)
            VALUES (?, ?, ?, 0)
        """
        try:
            with LocalAgentDB.get_connection() as conn:
                cursor = conn.execute(sql, (event.job_id, event.event_type, event.get_payload_json()))
                event_id = cursor.lastrowid
                conn.commit()
            return [event_id, True]
        except Exception as e:
            logger.error(f"Failed to save queue event: {e}")
            return [None, False]

    def delete_event(self, event_id: int) -> bool:
        """Deletes a queue event from the database."""
        sql = "DELETE FROM queue_events WHERE event_id = ?"
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (event_id,))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to delete event {event_id}: {e}")
            return False

    def get_unsynced_events(self) -> List[QueueEventModel]:
        """Retrieves all events that have not yet been synced to the cloud."""
        sql = "SELECT * FROM queue_events WHERE synced = 0 ORDER BY created_at ASC"
        events = []
        try:
            with LocalAgentDB.get_connection() as conn:
                cursor = conn.execute(sql)
                for row in cursor.fetchall():
                    events.append(self._row_to_event(row))
        except Exception as e:
            logger.error(f"Failed to fetch unsynced events: {e}")
        return events

    def mark_as_synced(self, event_id: int) -> bool:
        """Marks a queue event as successfully synced to the cloud."""
        sql = "UPDATE queue_events SET synced = 1 WHERE event_id = ?"
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (event_id,))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to mark event {event_id} as synced: {e}")
            return False
