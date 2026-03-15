from dataclasses import dataclass, field
from typing import Dict


@dataclass
class AgentModel:
    """Represents the agent's core configuration and identity."""

    agent_id: str = ""
    agent_token: str = ""
    location: str = "unassigned"
    features_enabled: Dict[str, bool] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict) -> "AgentModel":
        return cls(
            agent_id=data.get("agent_id", ""),
            agent_token=data.get("agent_token", ""),
            location=data.get("location", "unassigned"),
            features_enabled=data.get("features", {}),
        )

    def to_dict(self) -> dict:
        """Serializes the model to save back to YAML."""
        return {
            "agent_id": self.agent_id,
            "agent_token": self.agent_token,
            "location": self.location,
            "features": self.features_enabled,
        }
