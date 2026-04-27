import time
import logging
from pathlib import Path

from app.core.config import config
from app.core.local_agent_db import LocalAgentDB

logger = logging.getLogger(__name__)


class CleanupService:
    """
    Maintains disk space and database size by purging old files and records.
    Designed to run periodically (e.g., once a day) in the background.
    """

    def __init__(self, retention_days: int = 7):
        self.retention_days = retention_days
        self.retention_seconds = self.retention_days * 24 * 60 * 60

    def run_cleanup(self) -> None:
        """Executes all cleanup routines: files and database."""
        logger.info(
            f"Starting routine cleanup (Retention: {self.retention_days} days)..."
        )

        # 1. Clean up old PDF jobs
        self._cleanup_directory(config.JOB_COMPLETED_DIR)
        self._cleanup_directory(config.JOB_FAILED_DIR)

        # 2. Clean up old offline queue JSON files
        self._cleanup_directory(config.QUEUE_COMPLETED_DIR)
        self._cleanup_directory(config.QUEUE_FAILED_DIR)

        # 3. Clean up old SQLite database records
        self._cleanup_database()

        logger.info("Routine cleanup completed.")

    def _cleanup_directory(self, directory: Path) -> None:
        """
        Deletes files in the specified directory that are older than the retention period.
        """
        if not directory.exists():
            return

        current_time = time.time()
        deleted_count = 0
        freed_bytes = 0

        for filepath in directory.iterdir():
            if not filepath.is_file():
                continue

            try:
                # Get the last modified time of the file
                file_age_seconds = current_time - filepath.stat().st_mtime

                if file_age_seconds > self.retention_seconds:
                    file_size = filepath.stat().st_size
                    filepath.unlink()  # Delete the file

                    deleted_count += 1
                    freed_bytes += file_size
                    logger.debug(f"Deleted old file: {filepath.name}")

            except PermissionError:
                logger.warning(
                    f"Permission denied when trying to delete {filepath.name}."
                )
            except FileNotFoundError:
                pass  # File was already deleted by another process
            except Exception as e:
                logger.error(f"Error checking/deleting file {filepath.name}: {e}")

        if deleted_count > 0:
            freed_mb = freed_bytes / (1024 * 1024)
            logger.info(
                f"Cleaned up {deleted_count} files in {directory.name} (Freed {freed_mb:.2f} MB)."
            )

    def _cleanup_database(self) -> None:
        """
        Removes old completed/failed jobs and synced queue events from the SQLite database
        to prevent the .db file from growing infinitely.
        """
        # SQLite date modifier to subtract days from current time
        cutoff_date_modifier = f"-{self.retention_days} days"

        clean_jobs_sql = """
            DELETE FROM jobs 
            WHERE status IN ('completed', 'failed') 
            AND updated_at <= datetime('now', ?)
        """

        clean_queue_sql = """
            DELETE FROM queue_events 
            WHERE synced = 1 
            AND created_at <= datetime('now', ?)
        """

        try:
            with LocalAgentDB.get_connection() as conn:
                cursor = conn.cursor()

                cursor.execute(clean_jobs_sql, (cutoff_date_modifier,))
                jobs_deleted = cursor.rowcount

                cursor.execute(clean_queue_sql, (cutoff_date_modifier,))
                queue_deleted = cursor.rowcount

                conn.commit()

            if jobs_deleted > 0 or queue_deleted > 0:
                logger.info(
                    f"Database cleanup: Removed {jobs_deleted} old jobs and {queue_deleted} old queue events."
                )

        except Exception as e:
            logger.error(f"Failed to clean up database records: {e}")
