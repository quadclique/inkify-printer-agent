import sys
import logging
from logging.handlers import RotatingFileHandler
from app.core.config import config


def setup_logging() -> None:
    """
    Configures the global logging setup for the Inkify Printer Agent.
    Routes logs to the console, a general agent log, and a dedicated error log.
    """
    # Create a custom logger
    root_logger = logging.getLogger()

    # Convert string log level from env to logging constant
    log_level_name = config.LOG_LEVEL.upper()
    log_level = getattr(logging, log_level_name, logging.INFO)
    root_logger.setLevel(log_level)

    # Prevent adding duplicate handlers if setup is called multiple times
    if root_logger.handlers:
        return

    # Create formatters
    standard_formatter = logging.Formatter(
        fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 1. Console Handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(standard_formatter)
    root_logger.addHandler(console_handler)

    # 2. General Agent File Handler (Max 5MB per file, keep last 3)
    # Ensure log directory exists before creating file handlers
    config.LOG_DIR.mkdir(parents=True, exist_ok=True)
    try:
        agent_file_handler = RotatingFileHandler(
            filename=config.AGENT_LOG_FILE,
            maxBytes=config.AGENT_LOG_MAX_BYTES,
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        agent_file_handler.setFormatter(standard_formatter)
        root_logger.addHandler(agent_file_handler)
    except Exception as e:
        print(f"Failed to setup agent file logger: {e}")

    # 3. Error-Only File Handler (Max 5MB per file, keep last 3)
    try:
        error_file_handler = RotatingFileHandler(
            filename=config.ERROR_LOG_FILE,
            maxBytes=config.AGENT_LOG_MAX_BYTES,  # 50 MB
            backupCount=config.LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        error_file_handler.setLevel(logging.ERROR)
        error_file_handler.setFormatter(standard_formatter)
        root_logger.addHandler(error_file_handler)
    except Exception as e:
        print(f"Failed to setup error file logger: {e}")

    logging.info(f"Logging initialized at {log_level_name} level.")
