import logging
import socket
from typing import Optional

logger = logging.getLogger(__name__)

class PairingService:
    def __init__(self, api_client, agent_repo):
        self.api_client = api_client
        self.agent_repo = agent_repo

    def ensure_paired(self, cli_token: Optional[str] = None) -> bool:
        agent_config = self.agent_repo.get_config()

        # 1. Already registered?
        if agent_config and agent_config.agent_token:
            logger.info(f"Agent already registered as {agent_config.agent_id}")
            return True

        # 2. Not registered, but we have a token from the CLI
        if cli_token:
            logger.info(
                "No local credentials found. Attempting registration with provided token..."
            )

            device_name = socket.gethostname() + " Print Node"
            credentials = self.api_client.register_agent(cli_token, device_name)

            if credentials:
                logger.info(
                    "Registration successful! Saving permanent credentials locally."
                )

                # 1. Construct the combined Bearer token the backend expects
                combined_token = f"{credentials['agent_uuid']}:{credentials['agent_secret']}"
                
                # Update the AgentModel and save it securely to YAML
                agent_config.agent_id = credentials["agent_uuid"]
                agent_config.agent_token = combined_token
                self.agent_repo.save_config(agent_config)

                # Update the live API client headers
                self.api_client.agent_id = credentials["agent_uuid"]
                self.api_client.update_credentials(combined_token)
                return True
            else:
                logger.error("Registration failed. Token may be invalid or expired.")
                return False

        return False
