from dataclasses import dataclass

@dataclass
class PrinterModel:
    id: str
    name: str
    status: str  # e.g., "idle", "printing", "offline"
    raw_status: str = ""
    
    @property
    def is_ready(self) -> bool:
        return self.status == "idle"