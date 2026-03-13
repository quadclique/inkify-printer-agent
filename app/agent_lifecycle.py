import sys
import time
import logging
from app.core.config import config
from app.services.api_client_service import APIClientService
from app.services.job_service import JobService
from app.services.queue_service import QueueManagerService
from app.services.heartbeat_service import HeartbeatService
from app.services.cleanup_service import CleanupService
from app.services.updater_service import UpdaterService
from app.services.pairing_service import PairingService
from app.services.printer_service import PrinterService

logger = logging.getLogger(__name__)


class PrinterAgent:

    def __init__(self):
        self.is_running = False

        # Inject the shared API Client
        self.api_client = APIClientService()
        self.pairing_service = PairingService(self.api_client)
        self.job_service = JobService(self.api_client)
        self.heartbeat_service = HeartbeatService(self.api_client)
        
        self.queue_manager_service = QueueManagerService()
        self.cleanup_service = CleanupService(retention_days=7)
        self.last_cleanup_time = 0
        self.updater_service = UpdaterService()

    def run(self, registration_token: str = None) -> None:
        logger.info(f"Starting {config.APP_NAME} in {config.ENVIRONMENT} mode...")

        # --- 1. SETUP & AUTHENTICATION PHASE ---
        is_paired = self.pairing_service.ensure_paired(registration_token)
        if not is_paired:
            logger.critical(
                "Agent is not authenticated. Please run the agent with: python app/main.py --token <your_token>"
            )
            sys.exit(1)
        logger.info("Agent successfully authenticated.")

        # --- 2. HARDWARE SYNC PHASE ---
        logger.info("Syncing local printers with Inkify Cloud...")
        PrinterService().sync_printers_with_cloud(self.api_client)

        # --- 3. OPERATIONAL PHASE ---
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
