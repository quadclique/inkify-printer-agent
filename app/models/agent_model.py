from dataclasses import dataclass, field
from typing import Dict


@dataclass
class AgentModel:
    """Represents the agent's core configuration and identity."""

    agent_id: str = ""
    agent_token: str = ""
    location: str = "unassigned"
    printer_map: Dict[str, str] = field(default_factory=dict)
    features_enabled: Dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentModel":
        return cls(
            agent_id=data.get("agent_id", ""),
            agent_token=data.get("agent_token", ""),
            location=data.get("location", "unassigned"),
            printer_map=data.get("printer_map", {}),
            features_enabled=data.get("features", {}),
        )

    def to_dict(self) -> dict:
        """Serializes the model to save back to YAML."""
        return {
            "agent_id": self.agent_id,
            "agent_token": self.agent_token,
            "location": self.location,
            "printer_map": self.printer_map,
            "features": self.features_enabled,
        }
