import sqlite3
import logging
from contextlib import contextmanager
from typing import Generator
from app.core.config import config

logger = logging.getLogger(__name__)


class LocalAgentDB:
    """
    Manages the local SQLite database for the Inkify Printer Agent.
    Handles connections and initial schema setup.
    """

    @staticmethod
    @contextmanager
    def get_connection() -> Generator[sqlite3.Connection, None, None]:
        """
        Context manager for database connections.
        Ensures connections are properly closed after use.

        Usage:
            with LocalAgentDB.get_connection() as conn:
                conn.execute("SELECT * FROM jobs")
        """
        conn = None
        try:
            # check_same_thread=False allows multiple threads (like the heartbeat) to use the DB safely
            # as long as we aren't sharing the exact same connection object concurrently.
            conn = sqlite3.connect(
                config.DB_FILE,
                detect_types=sqlite3.PARSE_DECLTYPES,
                check_same_thread=False,
            )
            # Returns dictionary-like rows instead of tuples
            conn.row_factory = sqlite3.Row
            yield conn
        except sqlite3.Error as e:
            logger.error(f"Database connection error: {e}")
            raise
        finally:
            if conn:
                conn.close()

    @classmethod
    def initialize_schema(cls) -> None:
        """
        Creates the necessary database tables if they do not already exist.
        Called during application startup.
        """
        logger.info("Verifying local database schema...")

        # Example schema: You can expand these as you build your models
        create_jobs_table_sql = """
        CREATE TABLE IF NOT EXISTS jobs (
            job_id TEXT PRIMARY KEY,
            printer_id TEXT NOT NULL,
            status TEXT NOT NULL,
            file_path TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        create_queue_table_sql = """
        CREATE TABLE IF NOT EXISTS queue_events (
            event_id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            payload TEXT,
            synced BOOLEAN DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """

        try:
            with cls.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute(create_jobs_table_sql)
                cursor.execute(create_queue_table_sql)
                conn.commit()
            logger.info("Local database schema initialized successfully.")
        except sqlite3.Error as e:
            logger.critical(f"Failed to initialize database schema: {e}")
            raise SystemExit(1)
