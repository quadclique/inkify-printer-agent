import os
import yaml
import logging
import threading
from app.core.config import config
from app.models.agent_model import AgentModel

logger = logging.getLogger(__name__)

class AgentRepository:
    """Reads and writes agent configuration from the local YAML file securely and thread-safely."""
    
    # Class-level lock to prevent concurrent read/write corruption 
    # across background threads and API requests.
    _lock = threading.Lock()
    
    def get_config(self) -> AgentModel:
        """Gets current config, or returns a blank one if it doesn't exist."""
        with self._lock:
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
        with self._lock:
            try:
                config.AGENT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
                file_path = config.AGENT_CONFIG_FILE
                
                # Write to a temporary file first (atomic write pattern)
                # This prevents the config file from becoming empty/corrupted if the app crashes mid-write.
                temp_path = file_path.with_suffix(".tmp")
                
                with open(temp_path, "w") as f:
                    yaml.safe_dump(agent_model.to_dict(), f, default_flow_style=False)
                
                # Apply restrictive permissions safely (chmod 600 is POSIX-specific)
                try:
                    if os.name != 'nt':
                        os.chmod(temp_path, 0o600)
                except Exception as chmod_err:
                    logger.debug(f"Could not apply restrictive permissions: {chmod_err}")
                
                # Atomically replace the original file
                temp_path.replace(file_path)
                
                logger.debug("Successfully saved agent configuration to disk.")
                return True
            except Exception as e:
                logger.error(f"Failed to save agent config: {e}")
                # Attempt to clean up temp file on failure
                try:
                    if 'temp_path' in locals() and temp_path.exists():
                        temp_path.unlink()
                except Exception:
                    pass
                return False