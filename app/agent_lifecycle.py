import sys
import time
import logging
import threading
from typing import Optional
from app.core.config import config
from app.repositories.agent_repo import AgentRepository
from app.repositories.printer_repo import PrinterRepository

from app.services.api_client_service import APIClientService
from app.services.job_service import JobService
# from app.services.cups_service import CUPSManager
from app.services.queue_service import QueueService
from app.services.cleanup_service import CleanupService
from app.services.updater_service import UpdaterService
from app.services.pairing_service import PairingService
from app.services.printer_service import PrinterService
from app.services.storage_service import StorageService
from app.services.heartbeat_service import HeartbeatService

from app.platform.factory import get_printer_manager

logger = logging.getLogger(__name__)


class PrinterAgent:

    def __init__(self):
        # Initialize Shared Base Services
        self.agent_repo = AgentRepository()
        self.printer_repo = PrinterRepository()
        self.api_client = APIClientService(self.agent_repo)
        # self.cups_manager = CUPSManager()
        self.printer_manager = get_printer_manager()
        self.storage_service = StorageService()

        # Inject the shared API Client
        self.queue_service = QueueService(self.api_client, self.storage_service)
        self.pairing_service = PairingService(self.api_client, self.agent_repo)
        self.printer_service = PrinterService(self.api_client,self.printer_manager,self.printer_repo, self.storage_service)
        self.heartbeat_service = HeartbeatService(self.api_client, self.printer_service)
        self.job_service = JobService(self.api_client, self.printer_service, self.storage_service,self.queue_service)
        
        self.cleanup_service = CleanupService(retention_days=7)
        self.updater_service = UpdaterService(self.api_client)
        
        self.last_cleanup_time = time.time() 
        self.stop_event = threading.Event()
        self.is_running = False

    def run(self, ) -> None:
        logger.info(f"Starting {config.APP_NAME} in {config.ENVIRONMENT} mode...")

        # --- 1. SETUP & AUTHENTICATION PHASE ---
        # is_paired = self.pairing_service.ensure_paired(registration_token)
        agent_config = self.agent_repo.get_config()
        if not agent_config or not agent_config.agent_token:
            # logger.critical(
            #     "Agent is not authenticated. Please run the agent with: python app/main.py --token <your_token>"
            # )
            logger.critical(
                "Agent is not authenticated. The background service cannot start. "
                "Please run the installer to pair the device."
            )
            sys.exit(1)
        logger.info("Agent successfully authenticated.")

        # --- 2. HARDWARE SYNC PHASE ---
        logger.info("Syncing local printers with Inkify Cloud...")
        self.printer_service.sync_printers_with_cloud()

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
        self.queue_service.process_queue()

        while not self.stop_event.is_set():
            try:
                # 1. Sync any offline events first
                self.queue_service.process_queue()

                # 2. Process new print jobs
                self.job_service.process_pending_jobs()

                # 3. Run disk cleanup once every 24 hours
                current_time = time.time()
                if (
                    current_time - self.last_cleanup_time
                    > config.CLEANUP_INTERVAL_SECONDS
                ):
                    self.cleanup_service.run_cleanup()
                    self.printer_service.sync_printers_with_cloud()
                    self.last_cleanup_time = current_time

                # 4. Check for self-updates
                self.updater_service.check_for_updates()
                self.updater_service.apply_update_if_ready()

                # 5. Wait for the configured interval before checking again
                self.stop_event.wait(config.JOB_POLL_INTERVAL)
            except Exception as e:
                logger.error(f"Unexpected error during job polling cycle: {e}")
                self.stop_event.wait(5)
    def stop(self) -> None:
        """Halts the agent and cleans up resources."""
        logger.info("Initiating graceful shutdown...")
        self.stop_event.set()
        self.is_running = False
        self.heartbeat_service.stop()
        self.job_service.shutdown()
        logger.info(f"{config.APP_NAME} has shut down.")
