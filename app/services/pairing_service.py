import time
import logging
from typing import Optional, Dict, Any
from app.core.config import config
from app.services.api_client_service import APIClientService
from app.repositories.agent_repo import AgentRepository
from app.services.cups_service import CUPSManager

logger = logging.getLogger(__name__)

class PairingService:
    def __init__(self, api_client: APIClientService):
        self.api_client = api_client
        self.repo = AgentRepository()
        self.cups = CUPSManager()

    def ensure_paired(self) -> bool:
        agent_config = self.repo.get_config()
        
        if agent_config.agent_token and agent_config.agent_id:
            logger.info(f"Agent already securely paired. (ID: {agent_config.agent_id})")
            config.PRINTER_ID = agent_config.agent_id
            return True

        return self._run_physical_pairing_flow(agent_config)

    def _run_physical_pairing_flow(self, agent_config) -> bool:
        logger.warning("Agent has no identity. Initiating physical setup flow...")
        
        setup_data = self.api_client.initiate_setup()
        
        # 1. Validate the API response structure
        if not setup_data or not isinstance(setup_data.get("setup_code"), str):
            logger.error("Could not get a valid setup code from cloud. Retrying in 30s...")
            time.sleep(30)
            return False

        # Now we know setup_code is definitely a string
        setup_code: str = setup_data["setup_code"]
        
        # 2. Output the code to the physical world
        self._print_setup_receipt(setup_code)
        
        # 3. Enter polling loop
        logger.info(f"Waiting for shop owner to enter code {setup_code} at dashboard.inkify.com...")
        
        while True:
            time.sleep(5)
            status_data = self.api_client.check_setup_status(setup_code)
            
            if not status_data:
                continue

            status = status_data.get("status")
            
            if status == "claimed":
                permanent_uuid = status_data.get("agent_uuid")
                
                # Check that we actually got a UUID back
                if not isinstance(permanent_uuid, str):
                    logger.error("Server reported 'claimed' but sent no UUID.")
                    continue

                logger.info("✅ SUCCESS: Shop owner claimed device!")
                
                # 4. Save permanent identity
                agent_config.agent_id = permanent_uuid
                agent_config.agent_token = permanent_uuid 
                self.repo.save_config(agent_config)
                
                # 5. Update runtime services
                self.api_client.update_credentials(permanent_uuid)
                config.PRINTER_ID = permanent_uuid
                return True
                
            elif status == "expired":
                logger.error("Setup code expired. Restarting pairing flow...")
                # Return False and let agent_lifecycle.py handle the retry
                return False

    def _print_setup_receipt(self, setup_code: str):
        """Generates a text file and sends it to the default physical printer."""
        # Ensure the directory exists
        config.RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
        filename = config.RUNTIME_DIR / "inkify_setup_receipt.txt"
        
        try:
            with open(filename, "w") as f:
                f.write("\n=================================\n")
                f.write("      WELCOME TO INKIFY\n")
                f.write("=================================\n\n")
                f.write("To activate this printer, go to:\n")
                f.write("      dashboard.inkify.com\n\n")
                f.write(f"Enter Setup Code:  {setup_code}\n\n")
                f.write("=================================\n\n")
                
            printers = self.cups.get_printers()
            if not printers:
                logger.error("No printers found in CUPS!")
                print(f"\n>>>> SETUP CODE: {setup_code} <<<<\n")
                return

            default_printer = printers[0]["name"]
            logger.info(f"Sending physical setup receipt to: {default_printer}")
            self.cups.print_file(default_printer, str(filename), title="Inkify Setup")
            
        except Exception as e:
            logger.error(f"Failed to print: {e}")
            print(f"\n>>>> SETUP CODE: {setup_code} <<<<\n")
        finally:
            if filename.exists():
                filename.unlink()