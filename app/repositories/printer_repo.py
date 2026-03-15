# app/repositories/local_printer_repo.py
import yaml
import logging
from app.core.config import config

logger = logging.getLogger(__name__)


class PrinterRepository:
    """Manages the local mapping of hardware printers to Cloud UUIDs."""

    def save_printer_map(self, printer_map: dict) -> bool:
        """Writes the mapping of local hardware names to Cloud UUIDs."""
        try:
            config.PRINTERS_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)

            with open(config.PRINTERS_CONFIG_FILE, "w") as f:
                yaml.safe_dump(
                    {"printer_map": printer_map}, f, default_flow_style=False
                )

            logger.debug(
                f"Successfully saved {len(printer_map)} printers to mapping file."
            )
            return True
        except Exception as e:
            logger.error(f"Failed to save printer map: {e}")
            return False

    def get_printer_map(self) -> dict:
        """Reads the printer mapping from disk."""
        if not config.PRINTERS_CONFIG_FILE.exists():
            return {}

        try:
            with open(config.PRINTERS_CONFIG_FILE, "r") as f:
                data = yaml.safe_load(f) or {}
                return data.get("printer_map", {})
        except Exception as e:
            logger.error(f"Failed to read printer map: {e}")
            return {}
