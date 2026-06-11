import os
import time
import logging

from app.core.config import config

logger = logging.getLogger(__name__)

class StartupService:
    """
    Handles all initialization routines required before the agent begins 
    its main lifecycle (checking directories, clearing stale locks, etc.).
    """

    @staticmethod
    def ensure_directories() -> None:
        """
        Ensures all required runtime, configuration, and state directories exist.
        Creates them automatically if they are missing.
        """
        directories_to_create = [
            # Base directories
            config.RUNTIME_DIR,
            config.LOG_DIR,
            config.CONFIG_DIR,
            
            # Runtime subdirectories
            config.QUEUE_DIR,
            config.JOB_DIR,
            config.DB_DIR,
            config.LOCK_DIR,
            
            # Job states
            config.JOB_DOWNLOAD_DIR,
            config.JOB_READY_DIR,
            config.JOB_PRINTING_DIR,
            config.JOB_COMPLETED_DIR,
            config.JOB_FAILED_DIR,
            
            # Queue states
            config.QUEUE_PENDING_DIR,
            config.QUEUE_PROCESSING_DIR,
            config.QUEUE_COMPLETED_DIR,
            config.QUEUE_FAILED_DIR,
        ]

        logger.info("Verifying agent system directories...")
        
        for directory in directories_to_create:
            if not directory.exists():
                try:
                    # exist_ok=True prevents errors if the directory already exists
                    # parents=True creates any intermediate directories that might be missing
                    directory.mkdir(parents=True, exist_ok=True)
                    logger.debug(f"Created missing directory: {directory}")
                    if os.name != 'nt':
                        os.chmod(str(directory), 0o750)
                except PermissionError:
                    logger.error(f"Permission denied: Cannot create directory at {directory}. "
                                f"Check your user privileges.")
                    raise
                except Exception as e:
                    logger.error(f"Unexpected error creating directory {directory}: {e}")
                    raise
                
        logger.info("System directories verified successfully.")

    @classmethod
    def initialize_environment(cls) -> None:
        """
        Main entry point for all startup routines. 
        To be called in main.py before starting the agent loop.
        """
        try:
            cls.ensure_directories()
            cls._cleanup_stale_locks()
        except Exception as e:
            logger.critical(f"Critical failure during startup initialization: {e}")
            raise SystemExit(1)

    @staticmethod
    def _cleanup_stale_locks() -> None:
        """
        Removes orphaned .lock files left by crashes or power failures.
        A lock file is considered stale if it is older than STALE_LOCK_AGE_SECONDS.
        A live process would update its lock file within this window.
        """
        STALE_LOCK_AGE_SECONDS = 60

        if not config.LOCK_DIR.exists():
            return

        lock_files = list(config.LOCK_DIR.glob("*.lock"))
        if not lock_files:
            return

        now = time.time()
        cleaned = 0
        for lock_file in lock_files:
            try:
                age = now - lock_file.stat().st_mtime
                if age > STALE_LOCK_AGE_SECONDS:
                    lock_file.unlink()
                    logger.warning(
                        f"Removed stale lock file: {lock_file.name} "
                        f"(age: {int(age)}s — likely from a crash or power failure)"
                    )
                    cleaned += 1
            except Exception as e:
                logger.debug(f"Could not inspect lock file {lock_file}: {e}")

        if cleaned:
            logger.info(f"Startup cleanup: removed {cleaned} stale lock file(s).")
        else:
            logger.debug("Startup cleanup: no stale lock files found.")