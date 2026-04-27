import logging
from pathlib import Path
from typing import Optional

from app.core.config import config
from app.core.security import verify_checksum
from app.utils.file_utils import safe_move, safe_delete

logger = logging.getLogger(__name__)


class StorageService:
    """
    Manages the lifecycle and location of physical print files on disk.
    """

    def __init__(self):
        # Map logical states to physical directories
        self.state_dirs = {
            "download": config.JOB_DOWNLOAD_DIR,
            "ready": config.JOB_READY_DIR,
            "printing": config.JOB_PRINTING_DIR,
            "completed": config.JOB_COMPLETED_DIR,
            "failed": config.JOB_FAILED_DIR,
        }

        # Map logical states to physical directories for offline Queue JSONs
        self.queue_dirs = {
            "pending": config.QUEUE_PENDING_DIR,
            "processing": config.QUEUE_PROCESSING_DIR,
            "completed": config.QUEUE_COMPLETED_DIR,
            "failed": config.QUEUE_FAILED_DIR,
        }

    def verify_download(self, file_path: Path, expected_hash: str) -> bool:
        """
        Compares the local file's hash against the cloud's expected hash.
        """
        if not expected_hash:
            # If the cloud didn't provide a hash, we assume it's valid,
            # but log a warning that we are flying blind.
            logger.debug(
                f"No expected hash provided for {file_path.name}. Skipping verification."
            )
            return True

        is_valid = verify_checksum(file_path, expected_hash)

        if not is_valid:
            logger.error(
                f"File corruption detected! Hash mismatch for {file_path.name}."
            )

        return is_valid

    def transition_job_file(
        self, filename: str, from_state: str, to_state: str
    ) -> Optional[Path]:
        """
        Moves a file from one lifecycle directory to another.
        Returns the new Path object if successful, or None if it fails.
        """
        source_dir = self.state_dirs.get(from_state)
        dest_dir = self.state_dirs.get(to_state)

        if not source_dir or not dest_dir:
            logger.error(
                f"Invalid state transition requested: {from_state} -> {to_state}"
            )
            return None

        source_path = source_dir / filename
        dest_path = dest_dir / filename

        if not source_path.exists():
            logger.error(
                f"Cannot transition file: Source file not found at {source_path}"
            )
            return None

        logger.debug(f"Moving {filename}: [{from_state}] -> [{to_state}]")
        logger.info(f"📂 FILE MOVED: {filename} [{from_state.upper()}] ➔ [{to_state.upper()}]")
        if safe_move(source_path, dest_path):
            return dest_path
        return None

    def transition_queue_file(self, filename: str, from_state: str, to_state: str) -> Optional[Path]:
        """
        Moves an offline queue JSON file between lifecycle directories.
        Fails silently if the file is missing (meaning another thread already grabbed the lock).
        """
        source_dir = self.queue_dirs.get(from_state)
        dest_dir = self.queue_dirs.get(to_state)

        if not source_dir or not dest_dir:
            logger.error(f"Invalid queue state transition requested: {from_state} -> {to_state}")
            return None

        source_path = source_dir / filename
        dest_path = dest_dir / filename

        # If the file isn't there, another thread already locked it. This is expected.
        if not source_path.exists():
            return None

        # Determine icon based on transition
        icon = "🔄" if to_state == "processing" else "✅" if to_state == "completed" else "❌" if to_state == "failed" else "⏳"
        logger.info(f"{icon} QUEUE EVENT: {filename} [{from_state.upper()}] ➔ [{to_state.upper()}]")
        
        if safe_move(source_path, dest_path):
            return dest_path
        return None

    def cleanup_failed_download(self, filename: str) -> None:
        """Instantly deletes a corrupted or incomplete download."""
        target = config.JOB_DOWNLOAD_DIR / filename
        safe_delete(target)
