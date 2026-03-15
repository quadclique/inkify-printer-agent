import logging
import time
from datetime import datetime
from pathlib import Path
import subprocess

from app.core.config import config

logger = logging.getLogger(__name__)


class UpdaterService:
    """
    Checks the cloud for new agent versions and schedules self-updates
    during the designated maintenance window.
    """

    def __init__(self, api_client):
        self.api_client = api_client
        self.current_version = self._get_current_version()
        self.last_check_time = 0
        self.pending_update_url = None

    def _get_current_version(self) -> str:
        """Reads the current version from the version.txt file."""
        try:
            if config.VERSION_FILE.exists():
                file_version = config.VERSION_FILE.read_text().strip()
                if file_version:  # Ensure it's not just an empty string
                    return file_version
            return config.APP_VERSION
        except Exception as e:
            logger.error(f"Failed to read version file: {e}")
            return config.APP_VERSION

    def check_for_updates(self) -> None:
        """
        Polls the API to see if a newer version is available.
        Should be called periodically (e.g., every 6 hours).
        """
        current_time = time.time()
        if current_time - self.last_check_time < config.UPDATE_CHECK_INTERVAL:
            return

        self.last_check_time = current_time
        logger.info(
            f"Checking for agent updates (Current version: {self.current_version})..."
        )

        try:
            # Assuming your API has an endpoint like GET /agent/version
            update_data = self.api_client._request("GET", "/agent/version")

            if not update_data:
                return

            latest_version = update_data.get("latest_version")
            download_url = update_data.get("download_url")

            if latest_version and latest_version != self.current_version:
                logger.info(f"New version {latest_version} is available!")
                self.pending_update_url = download_url
            else:
                logger.debug("Agent is up to date.")

        except Exception as e:
            logger.error(f"Failed to check for updates: {e}")

    def apply_update_if_ready(self) -> None:
        """
        If an update is pending AND we are inside the maintenance window,
        trigger the update process.
        """
        if not self.pending_update_url:
            return

        if self._is_maintenance_window():
            logger.critical(
                "Maintenance window active. Initiating self-update process..."
            )
            self._trigger_update_script(self.pending_update_url)

    def _is_maintenance_window(self) -> bool:
        """Checks if the current local time falls within the safe update window."""
        now = datetime.now()
        current_time = now.strftime("%H:%M")

        # Simple string comparison works for HH:MM 24-hour format
        # e.g., "01:00" <= "02:30" <= "04:00"
        start = config.UPDATE_WINDOW_START
        end = config.UPDATE_WINDOW_END

        if start <= end:
            return start <= current_time <= end
        else:
            # Handles overnight windows (e.g., 23:00 to 02:00)
            return current_time >= start or current_time <= end

    def _trigger_update_script(self, url: str) -> None:
        """
        Downloads and executes the system update script (bash/batch).
        This will likely kill the current Python process.
        """
        try:
            # Example: Download a bash script and execute it
            script_path = config.RUNTIME_DIR / "update.sh"
            success = self.api_client.download_job_file(url, str(script_path))

            if success:
                logger.info("Update script downloaded. Executing system update...")
                # Make script executable and run it in the background
                script_path.chmod(0o755)
                subprocess.Popen([str(script_path)])

                # Exit this current python process so the script can overwrite files
                import sys

                sys.exit(0)
            else:
                logger.error("Failed to download update script.")

        except Exception as e:
            logger.error(f"Failed to trigger update: {e}")
