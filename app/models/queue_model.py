from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Any, Optional
import json

@dataclass
class QueueEventModel:
    job_id: str
    event_type: str
    payload: Dict[str, Any]
    event_id: int = 0
    synced: bool = False
    created_at: Optional[datetime] = None

    def get_payload_json(self) -> str:
        """Serializes the dictionary payload for database insertion."""
        return json.dumps(self.payload)