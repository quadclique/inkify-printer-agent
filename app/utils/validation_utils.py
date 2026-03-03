from urllib.parse import urlparse


def is_valid_url(url: str) -> bool:
    """Basic validation to ensure a string is a properly formatted URL."""
    if not url:
        return False
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False


def is_valid_job_payload(payload: dict) -> bool:
    """Validates that a dictionary contains the minimum required keys for a print job."""
    required_keys = ["id", "printer_name", "file_url"]
    return all(key in payload and payload[key] for key in required_keys)
