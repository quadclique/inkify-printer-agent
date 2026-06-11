import time
import logging
from functools import wraps
from typing import Callable, Any, Type

from app.core.config import config

logger = logging.getLogger(__name__)


def with_retries(
    max_retries: int = config.API_MAX_RETRIES,
    base_delay: float = config.RETRY_BASE_DELAY,
    max_delay: float = config.RETRY_MAX_DELAY,
    exceptions: tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    """
    A decorator that retries a function if it raises specific exceptions.
    Uses exponential backoff for the delay between retries.

    :param max_retries: Maximum number of times to retry before giving up.
    :param base_delay: Starting delay in seconds.
    :param max_delay: Maximum delay in seconds.
    :param exceptions: A tuple of exception classes to catch and retry on.
    """

    def decorator(func: Callable) -> Callable:
        @wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            retries = 0
            delay = base_delay

            while True:
                try:
                    return func(*args, **kwargs)
                except exceptions as e:
                    retries += 1
                    if retries > max_retries:
                        logger.error(
                            f"Max retries ({max_retries}) reached for '{func.__name__}'. Failing."
                        )
                        raise  # Re-raise the exception if we're out of retries

                    logger.warning(
                        f"Attempt {retries}/{max_retries} failed for '{func.__name__}': {e}. "
                        f"Retrying in {delay:.2f} seconds..."
                    )

                    time.sleep(delay)

                    # Exponential backoff with a cap
                    delay = min(delay * 2, max_delay)

        return wrapper

    return decorator
