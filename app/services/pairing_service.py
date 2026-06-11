import logging
import socket
from typing import Optional

logger = logging.getLogger(__name__)

class PairingService:
    """Handles initial agent registration and authentication."""

    def __init__(self, api_client, agent_repo):
        self.api_client = api_client
        self.agent_repo = agent_repo

    def ensure_paired(self, cli_token: Optional[str] = None) -> bool:
        """
        Verifies the agent is registered. If not, attempts registration with the
        provided token.

        Returns True if the agent is (or becomes) authenticated.
        """
        agent_config = self.agent_repo.get_config()

        # Already registered
        if agent_config and agent_config.agent_token:
            logger.info(f"Agent already registered (ID: {agent_config.agent_id})")
            return True

        if cli_token:
            logger.info(
                "Agent is not registered. Attempting registration with provided token..."
            )
        
            try:
                hostname = socket.gethostname()
            except Exception:
                hostname = "Unknown-Device"
            
            device_name = f"{hostname} Print Node"

            credentials = self.api_client.register_agent(cli_token, device_name)

            if credentials:
                logger.info(
                    "Registration successful! Saving permanent credentials locally."
                )
                # Build combined bearer token
                agent_uuid = credentials.get("agent_uuid", "")
                agent_secret = credentials.get("agent_secret", "")
                if not agent_uuid or not agent_secret:
                    logger.error("Registration response missing agent_uuid or agent_secret.")
                    return False

                combined_token = f"{agent_uuid}:{agent_secret}"
                
                # Update the AgentModel and save it securely to YAML
                agent_config.agent_id = agent_uuid
                agent_config.agent_token = combined_token
                saved = self.agent_repo.save_config(agent_config)
                if not saved:
                    logger.error("Failed to save credentials to disk.")
                    return False

                # Update the live API client headers
                self.api_client.agent_id = agent_uuid
                self.api_client.update_credentials(combined_token)
                logger.info(f"Registration successful! Agent ID: {agent_uuid}")
                return True
            else:
                logger.error("Registration failed. Token may be invalid or expired.")
                return False
        else:
            logger.warning("No registration token provided and agent is not paired.")
            return False

    def is_paired(self) -> bool:
        """Returns True if the agent has saved credentials."""
        config = self.agent_repo.get_config()
        return bool(config and config.agent_token)
