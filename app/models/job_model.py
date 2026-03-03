from dataclasses import dataclass
from datetime import datetime
from typing import Optional


@dataclass
class JobModel:
    job_id: str
    printer_id: str
    status: str
    file_path: Optional[str] = None
    file_url: Optional[str] = None
    expected_hash: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    @classmethod
    def from_api_response(cls, data: dict) -> "JobModel":
        """Safely parses a raw API dictionary into a strict JobModel."""
        return cls(
            job_id=data.get("id", ""),
            printer_id=data.get("printer_name", ""),
            status=data.get("status", "pending"),
            file_url=data.get("file_url"),
            expected_hash=data.get("sha256_hash"),
        )
