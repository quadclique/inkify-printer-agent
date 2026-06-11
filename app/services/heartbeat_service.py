import time
import logging
import threading
from typing import Dict, Any

from app.core.config import config
from app.utils.system_utils import get_system_metrics

logger = logging.getLogger(__name__)


class HeartbeatService:
    """
    Runs a background thread that periodically pings the Inkify API to
    report that the agent is online, along with basic system health metrics.
    """

    def __init__(self, api_client, printer_service):
        self.api_client = api_client
        self.printer_service = printer_service
        self.interval = config.HEARTBEAT_INTERVAL
        self.join_timeout = config.THREAD_JOIN_TIMEOUT
        # Thread control events
        self._stop_event = threading.Event()
        self._thread = threading.Thread(target=self._run_heartbeat)

    def start(self) -> None:
        """Spawns the background heartbeat thread."""
        if self._thread is not None and self._thread.is_alive():
            logger.warning("Heartbeat thread is already running.")
            return

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run_heartbeat,
            name="HeartbeatThread",
            daemon=True,  # Daemon ensures the thread dies when the main app exits
        )
        self._thread.start()
        logger.info(f"Heartbeat service started (Interval: {self.interval}s).")

    def stop(self) -> None:
        """Signals the background thread to shut down."""
        if self._thread and self._thread.is_alive():
            logger.info("Stopping heartbeat service...")
            self._stop_event.set()
            self._thread.join(timeout=config.THREAD_JOIN_TIMEOUT)
            logger.debug("Heartbeat service stopped.")
            
    def _run_heartbeat(self) -> None:
        """The infinite loop that runs inside the thread."""
        while not self._stop_event.is_set():
            try:
                payload = self._build_heartbeat_payload()
                success = self.api_client.check_in(payload)

                if not success:
                    logger.debug("Heartbeat failed. Will retry on next interval.")
                else:
                    logger.debug("Heartbeat synced successfully.")

            except Exception as e:
                logger.error(f"Unexpected error in heartbeat thread: {e}")

            # Sleep using the stop_event so we can interrupt it immediately during shutdown
            self._stop_event.wait(self.interval)

    def _build_heartbeat_payload(self) -> Dict[str, Any]:
        """Assembles the heartbeat payload with system metrics and printer statuses."""
        metrics = get_system_metrics()

        # Read dynamic version from file (falls back to config constant)
        version = config.APP_VERSION
        try:
            if config.VERSION_FILE.exists():
                file_version = config.VERSION_FILE.read_text().strip()
                if file_version:
                    version = file_version
        except Exception as e:
            logger.debug(f"Failed to read version file: {e}")

        # Gather printer state safely
        try:
            local_printers = self.printer_service.get_available_printers()
            printer_map = self.printer_service.printer_repo.get_printer_map()
        except Exception as e:
            logger.error(f"Heartbeat failed to fetch printer info: {e}")
            local_printers = []
            printer_map = {}

        sig_to_cloud_id = {
            sig: data.get("cloud_printer_id")
            for sig, data in printer_map.items()
            if isinstance(data, dict)
        }

        return {
            "version": version,
            "status": "online",
            "environment": config.ENVIRONMENT,
            "metrics": metrics,
            "printers": [
                {
                    "cloud_printer_id": sig_to_cloud_id.get(p.get("hardware_signature")),
                    "name": p["name"],
                    "status": p["status"],
                    "connection_type": p["connection_type"],
                    "is_online": p["status"] in ["idle", "printing"],
                }
                for p in local_printers
            ],
        }
