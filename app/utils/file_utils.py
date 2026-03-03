import hashlib
import shutil
import logging
from pathlib import Path
from app.core.config import config

logger = logging.getLogger(__name__)


def safe_move(source: Path, destination: Path) -> bool:
    """Safely moves a file, catching permission or lock errors."""
    try:
        # shutil.move handles crossing filesystems better than os.rename
        shutil.move(str(source), str(destination))
        return True
    except Exception as e:
        logger.error(f"Failed to move {source.name} to {destination.parent.name}: {e}")
        return False


def safe_delete(file_path: Path) -> bool:
    """Safely deletes a file if it exists."""
    try:
        if file_path.exists():
            file_path.unlink()
        return True
    except Exception as e:
        logger.error(f"Failed to delete {file_path.name}: {e}")
        return False
