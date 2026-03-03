import os
import uuid
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables from the .env file at the project root
load_dotenv()


class AppConfig:
    # Application info
    APP_NAME = "Inkify Printer Agent"
    ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
    APP_VERSION = os.getenv("APP_VERSION", "1.0.0")

    # Base directories
    # Path(__file__) = app/core/constants.py
    BASE_DIR = Path(__file__).resolve().parent.parent.parent
    RUNTIME_DIR = BASE_DIR / "runtime"
    LOG_DIR = BASE_DIR / "logs"
    CONFIG_DIR = BASE_DIR / "config"
    SYSTEM_DIR = BASE_DIR / "system"
    SCRIPTS_DIR = BASE_DIR / "scripts"

    # Runtime subdirectories
    QUEUE_DIR = RUNTIME_DIR / "queue"
    JOB_DIR = RUNTIME_DIR / "jobs"
    DB_DIR = RUNTIME_DIR / "db"
    LOCK_DIR = RUNTIME_DIR / "lock"

    # Job directories
    JOB_DOWNLOAD_DIR = JOB_DIR / "download"
    JOB_READY_DIR = JOB_DIR / "ready"
    JOB_PRINTING_DIR = JOB_DIR / "printing"
    JOB_COMPLETED_DIR = JOB_DIR / "completed"
    JOB_FAILED_DIR = JOB_DIR / "failed"

    # Queue directories
    QUEUE_PENDING_DIR = QUEUE_DIR / "pending"
    QUEUE_PROCESSING_DIR = QUEUE_DIR / "processing"
    QUEUE_COMPLETED_DIR = QUEUE_DIR / "completed"
    QUEUE_FAILED_DIR = QUEUE_DIR / "failed"

    # Database file
    DB_FILE = DB_DIR / "inkify-agent.db"

    # Lock file
    LOCK_FILE = LOCK_DIR / "inkify-agent.lock"

    # Version file
    VERSION_FILE = BASE_DIR / "version.txt"

    # Config Files
    AGENT_CONFIG_FILE = CONFIG_DIR / "inkify-agent.yaml"
    PRINTERS_CONFIG_FILE = CONFIG_DIR / "inkify-printers.yaml"

    # Network & App specific rules
    API_URL = os.getenv("API_URL", "http://localhost:8000/api/v1")
    AGENT_TOKEN = os.getenv("AGENT_TOKEN", "")
    API_TIMEOUT_DEFAULT = int(os.getenv("API_TIMEOUT_DEFAULT", 10))
    API_TIMEOUT_DOWNLOAD = int(os.getenv("API_TIMEOUT_DOWNLOAD", 30))
    API_MAX_RETRIES = int(os.getenv("API_MAX_RETRIES", 3))

    # Logs
    AGENT_LOG_FILE = LOG_DIR / "inkify-agent.log"
    ERROR_LOG_FILE = LOG_DIR / "inkify-error.log"
    AUDIT_LOG_FILE = LOG_DIR / "inkify-audit.log"
    LOG_LEVEL = os.getenv("AGENT_LOG_LEVEL", "INFO")
    AGENT_LOG_MAX_BYTES = int(os.getenv("AGENT_LOG_MAX_BYTES", 5 * 1024 * 1024))
    ERROR_LOG_MAX_BYTES = int(os.getenv("ERROR_LOG_MAX_BYTES", 50 * 1024 * 1024))
    LOG_BACKUP_COUNT = int(os.getenv("LOG_BACKUP_COUNT", 3))

    # Default intervals (seconds)
    HEARTBEAT_INTERVAL = int(os.getenv("HEARTBEAT_INTERVAL", 10))
    JOB_POLL_INTERVAL = int(os.getenv("JOB_POLL_INTERVAL", 5))
    ERROR_SLEEP_SECONDS = int(os.getenv("ERROR_SLEEP_SECONDS", 5))
    PRINTER_SYNC_INTERVAL = int(os.getenv("PRINTER_SYNC_INTERVAL", 60))
    RETRY_BASE_DELAY = int(os.getenv("RETRY_BASE_DELAY", 1))
    RETRY_MAX_DELAY = int(os.getenv("RETRY_MAX_DELAY", 10))
    THREAD_JOIN_TIMEOUT = int(os.getenv("THREAD_JOIN_TIMEOUT", 5))
    FILE_CHUNK_SIZE = int(os.getenv("FILE_CHUNK_SIZE", 8192))

    # Cleanup rules
    CLEANUP_RETENTION_DAYS = int(os.getenv("CLEANUP_RETENTION_DAYS", 7))
    CLEANUP_INTERVAL_SECONDS = int(os.getenv("CLEANUP_INTERVAL_SECONDS", 86400))

    # Maintenance window
    UPDATE_WINDOW_START = os.getenv("UPDATE_WINDOW_START", "01:00")
    UPDATE_WINDOW_END = os.getenv("UPDATE_WINDOW_END", "04:00")
    UPDATE_CHECK_INTERVAL = int(
        os.getenv("UPDATE_CHECK_INTERVAL", 21600)
    )  # default 6 hours

    PRINTER_ID = os.getenv("PRINTER_ID", str(uuid.uuid5(uuid.NAMESPACE_DNS, "inkify-default-printer")))# Instantiate a global config object for easy import

config = AppConfig()


