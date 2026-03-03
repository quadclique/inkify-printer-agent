import hashlib
import hmac
import logging
from pathlib import Path
from app.core.config import config

logger = logging.getLogger(__name__)

def calculate_file_hash(file_path: Path, chunk_size: int = config.FILE_CHUNK_SIZE) -> str:
    """Calculates the SHA-256 hash of a file efficiently in chunks."""
    if not file_path.exists():
        logger.error(f"Cannot calculate hash: File not found at {file_path}")
        return ""

    sha256_hash = hashlib.sha256()
    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                sha256_hash.update(chunk)
        return sha256_hash.hexdigest()
    except Exception as e:
        logger.error(f"Failed to calculate hash for {file_path.name}: {e}")
        return ""

def verify_checksum(file_path: Path, expected_hash: str) -> bool:
    """Securely compares the actual file hash against the expected cloud hash."""
    actual_hash = calculate_file_hash(file_path)
    # Using hmac.compare_digest prevents timing attacks!
    return hmac.compare_digest(actual_hash, expected_hash)