import time
import logging
import sys
from app.core.config import config
from app.services.api_client_service import APIClientService
from app.services.job_service import JobService
from app.services.queue_service import QueueManagerService
from app.services.heartbeat_service import HeartbeatService
from app.services.cleanup_service import CleanupService
from app.services.updater_service import UpdaterService
from app.services.pairing_service import PairingService

logger = logging.getLogger(__name__)


class PrinterAgent:
    """
    The main infinite loop for the Inkify Printer Agent.
    Coordinates polling intervals, gracefully handles shutdowns, and delegates work.
    """

    def __init__(self):
        self.is_running = False

        # Inject the shared API Client
        self.api_client = APIClientService()

        self.pairing_service = PairingService(self.api_client)
        self.job_service = JobService()
        self.heartbeat_service = HeartbeatService()
        self.queue_manager_service = QueueManagerService()
        self.cleanup_service = CleanupService(retention_days=7)
        self.last_cleanup_time = 0
        self.updater_service = UpdaterService()

    def run(self) -> None:
        """Starts the agent's main blocking loop."""
        logger.info(f"Starting {config.APP_NAME} in {config.ENVIRONMENT} mode...")

        # --- BLOCKING SETUP PHASE ---
        # The agent cannot proceed until it has a permanent cloud identity.
        is_paired = False
        while not is_paired:
            is_paired = self.pairing_service.ensure_paired()
            if not is_paired:
                logger.critical("Failed to pair with Inkify Cloud. Agent will try again down.")
        # --- OPERATIONAL PHASE ---
        self.is_running = True
        logger.info(
            f"Agent successfully authenticated. Polling for jobs every {config.JOB_POLL_INTERVAL} seconds."
        )

        # Resolve any jobs interrupted by a crash/power-outage
        self.job_service.recover_interrupted_jobs()
        
        # Start background threads
        self.heartbeat_service.start()

        try:
            self._loop()
        except KeyboardInterrupt:
            logger.info("Keyboard interrupt received. Shutting down gracefully...")
            self.stop()
        except Exception as e:
            logger.critical(f"Fatal error in main agent loop: {e}")
            self.stop()

    def _loop(self) -> None:
        """The core polling loop."""
        self.queue_manager_service.process_queue()

        while self.is_running:
            try:
                # 1. Sync any offline events first
                self.queue_manager_service.process_queue()

                # 2. Process new print jobs
                self.job_service.process_pending_jobs()

                # 3. Run disk cleanup once every 24 hours
                current_time = time.time()
                if (
                    current_time - self.last_cleanup_time
                    > config.CLEANUP_INTERVAL_SECONDS
                ):
                    self.cleanup_service.run_cleanup()
                    self.last_cleanup_time = current_time

                # 4. Check for self-updates
                self.updater_service.check_for_updates()
                self.updater_service.apply_update_if_ready()

                # 5. Wait for the configured interval before checking again
                time.sleep(config.JOB_POLL_INTERVAL)

            except Exception as e:
                logger.error(f"Unexpected error during job polling cycle: {e}")
                time.sleep(5)

    def stop(self) -> None:
        """Halts the agent and cleans up resources."""
        self.is_running = False
        self.heartbeat_service.stop()
        logger.info(f"{config.APP_NAME} has shut down.")
