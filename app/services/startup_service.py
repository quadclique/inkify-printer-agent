import logging
from pathlib import Path

# Adjust the import path based on your exact package structure
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
            try:
                # exist_ok=True prevents errors if the directory already exists
                # parents=True creates any intermediate directories that might be missing
                if not directory.exists():
                    directory.mkdir(parents=True, exist_ok=True)
                    logger.debug(f"Created missing directory: {directory}")
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
            
            # Future expansion: You can add other startup tasks here, such as:
            # - Removing stale .lock files from previous crashes
            # - Running initial SQLite database migrations
            # - Validating the presence of required config files (printers.yaml)
            
        except Exception as e:
            logger.critical(f"Critical failure during startup initialization: {e}")
            # Exit the program completely if we can't build our required environment
            raise SystemExit(1)