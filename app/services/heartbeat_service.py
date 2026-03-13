import time
import logging
import threading
from typing import Dict, Any

from app.core.config import config
from app.services.api_client_service import APIClientService
from app.services.printer_service import PrinterService
from app.utils.system_utils import get_system_metrics

logger = logging.getLogger(__name__)


class HeartbeatService:
    """
    Runs a background thread that periodically pings the Inkify API to
    report that the agent is online, along with basic system health metrics.
    """

    def __init__(self, api_client=APIClientService()):
        self.api_client = api_client
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
            self._thread.join(timeout=5)
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
        """Gathers data about the agent to send to the cloud."""
        metrics = get_system_metrics()  # Example: { "cpu": 45.2, "ram_mb": 1024 }
        # metrics = {"cpu": 0.0, "ram_mb": 0}  # Mock for now

        printer_service = PrinterService()
        local_printers = printer_service.get_available_printers()

        return {
            "version": "1.0.0",  # You could read this from constants.VERSION_FILE
            "status": "online",
            "environment": config.ENVIRONMENT,
            "metrics": metrics,
            "printers": [
                {"name": p["name"], "status": p["status"]} for p in local_printers
            ],
        }
