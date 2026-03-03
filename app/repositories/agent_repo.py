import os
import yaml
import logging
from typing import Optional
from pathlib import Path
from app.core.config import config
from app.models.agent_model import AgentModel

logger = logging.getLogger(__name__)

class AgentRepository:
    """Reads and writes agent configuration from the local YAML file."""
    
    def get_config(self) -> AgentModel:
        """Gets current config, or returns a blank one if it doesn't exist."""
        if not config.AGENT_CONFIG_FILE.exists():
            return AgentModel()
            
        try:
            with open(config.AGENT_CONFIG_FILE, "r") as f:
                data = yaml.safe_load(f) or {}
                return AgentModel.from_dict(data)
        except Exception as e:
            logger.error(f"Failed to parse agent config: {e}")
            return AgentModel()

    def save_config(self, agent_model: AgentModel) -> bool:
        """Writes the agent configuration to the local YAML file securely."""
        try:
            # Ensure the config directory exists
            config.AGENT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            
            file_path = config.AGENT_CONFIG_FILE
            with open(config.AGENT_CONFIG_FILE, "w") as f:
                yaml.safe_dump(agent_model.to_dict(), f, default_flow_style=False)
            os.chmod(file_path, 0o600)    
            logger.debug("Successfully saved agent configuration to disk.")
            return True
        except Exception as e:
            logger.error(f"Failed to save agent config: {e}")
            return False