from datetime import datetime, timezone


def get_utc_now() -> datetime:
    """Returns a timezone-aware UTC datetime."""
    return datetime.now(timezone.utc)


def is_time_between(current_time: str, start_time: str, end_time: str) -> bool:
    """Checks if a given HH:MM time falls within a window (handles overnight windows)."""
    if start_time <= end_time:
        return start_time <= current_time <= end_time
    else:
        return current_time >= start_time or current_time <= end_time
