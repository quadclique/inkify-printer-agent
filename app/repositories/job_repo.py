import logging
from typing import Optional
from app.core.local_agent_db import LocalAgentDB
from app.models.job_model import JobModel

logger = logging.getLogger(__name__)

class JobRepository:
    """Handles all database operations for print jobs."""
    
    def save(self, job: JobModel) -> bool:
        """Inserts a new job or ignores if it already exists."""
        sql = """
            INSERT OR IGNORE INTO jobs (job_id, printer_id, status, file_path) 
            VALUES (?, ?, ?, ?)
        """
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (job.job_id, job.printer_id, job.status, job.file_path))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to save job {job.job_id}: {e}")
            return False

    def update_status(self, job_id: str, status: str) -> bool:
        """Updates the status and timestamp of a specific job."""
        sql = "UPDATE jobs SET status = ?, updated_at = CURRENT_TIMESTAMP WHERE job_id = ?"
        try:
            with LocalAgentDB.get_connection() as conn:
                conn.execute(sql, (status, job_id))
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Failed to update status for job {job_id}: {e}")
            return False

    def get_job(self, job_id: str) -> Optional[JobModel]:
        """Retrieves a single job by its ID."""
        sql = "SELECT * FROM jobs WHERE job_id = ?"
        try:
            with LocalAgentDB.get_connection() as conn:
                cursor = conn.execute(sql, (job_id,))
                row = cursor.fetchone()
                
                if row:
                    return JobModel(
                        job_id=row["job_id"],
                        printer_id=row["printer_id"],
                        status=row["status"],
                        file_path=row["file_path"],
                        created_at=row["created_at"],
                        updated_at=row["updated_at"]
                    )
        except Exception as e:
            logger.error(f"Failed to retrieve job {job_id}: {e}")
        return None