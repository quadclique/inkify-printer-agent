from dataclasses import dataclass

@dataclass
class PrinterModel:
    id: str
    name: str
    status: str  # "idle" | "printing" | "offline"
    raw_status: str = ""
    connection_type: str = "unknown"
    device_uri: str = ""
    hardware_signature: str = ""
    supports_color: bool = False
    supports_duplex: bool = False

    @property
    def is_ready(self) -> bool:
        return self.status in ("idle", "printing")

    @classmethod
    def from_dict(cls, data: dict) -> "PrinterModel":
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            status=data.get("status", "offline"),
            raw_status=data.get("raw_status", ""),
            connection_type=data.get("connection_type", "unknown"),
            device_uri=data.get("device_uri", ""),
            hardware_signature=data.get("hardware_signature", ""),
            supports_color=bool(data.get("supports_color", False)),
            supports_duplex=bool(data.get("supports_duplex", False)),
        )
