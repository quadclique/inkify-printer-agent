import logging
import json
from typing import List
from app.core.local_agent_db import LocalAgentDB
from app.models.queue_model import QueueEventModel

logger = logging.getLogger(__name__)


class QueueRepository:
    """Handles offline queue events."""

    def add_event(self, event: QueueEventModel) -> bool:
        sql = """
            INSERT INTO queue_events (job_id, event_type, payload, synced)
            VALUES (?, ?, ?, 0)
        """
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(
                    sql, (event.job_id, event.event_type, event.get_payload_json())
                )
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save queue event: {e}")
            return False

    def get_unsynced_events(self) -> List[QueueEventModel]:
        sql = "SELECT * FROM queue_events WHERE synced = 0 ORDER BY created_at ASC"
        events = []
        try:
            with LocalAgentDB.get_connection() as conn:
                cursor = conn.execute(sql)
                for row in cursor.fetchall():
                    events.append(
                        QueueEventModel(
                            event_id=row["event_id"],
                            job_id=row["job_id"],
                            event_type=row["event_type"],
                            payload=json.loads(row["payload"]),
                            synced=bool(row["synced"]),
                            created_at=row["created_at"],
                        )
                    )
        except Exception as e:
            logger.error(f"Failed to fetch unsynced events: {e}")
        return events

    def mark_as_synced(self, event_id: int) -> bool:
        sql = "UPDATE queue_events SET synced = 1 WHERE event_id = ?"
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (event_id,))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to mark event {event_id} as synced: {e}")
            return False
