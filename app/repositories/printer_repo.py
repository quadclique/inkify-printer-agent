import yaml
import logging
import threading
from datetime import datetime, timezone
from typing import Optional

from app.core.config import config

logger = logging.getLogger(__name__)

# Connection priority for intelligent routing (lower index = higher priority)
CONNECTION_PRIORITY = ["usb", "network", "ipp", "socket", "dnssd", "lpd", "unknown"]


class PrinterRepository:
    """
    Manages the local mapping of physical printers to Cloud UUIDs safely across threads.

    Schema (inkify-printers.yaml):
        printer_map:
          <hardware_signature>:
            cloud_printer_id: <uuid>
            display_name: "HP LaserJet"
            connections:
              usb:
                device_uri: "usb://HP/LaserJet?serial=ABC123"
                queue_name: "HP_LaserJet_USB"
                last_seen: "2026-05-28T01:00:00+00:00"
              wifi:
                device_uri: "ipp://192.168.1.20/ipp/print"
                queue_name: "HP_LaserJet_WiFi"
                last_seen: "2026-05-28T01:00:00+00:00"
    """

    _lock = threading.Lock()

    def _read_map_nolock(self) -> dict:
        """Internal helper to read the map without acquiring the lock."""
        if not config.PRINTERS_CONFIG_FILE.exists():
            return {}
        try:
            with open(config.PRINTERS_CONFIG_FILE, "r") as f:
                data = yaml.safe_load(f) or {}
            raw = data.get("printer_map", {})
            return self._migrate_legacy_map(raw)
        except Exception as e:
            logger.error(f"Failed to read printer map: {e}")
            return {}

    def _save_map_nolock(self, printer_map: dict) -> bool:
        """Internal helper to save the map atomically without acquiring the lock."""
        try:
            config.PRINTERS_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
            # Write to temp file then rename for atomicity
            tmp_path = config.PRINTERS_CONFIG_FILE.with_suffix(".tmp")
            with open(tmp_path, "w") as f:
                yaml.safe_dump({"printer_map": printer_map}, f, default_flow_style=False)
            tmp_path.replace(config.PRINTERS_CONFIG_FILE)
            logger.debug(f"Saved {len(printer_map)} printers to mapping file.")
            return True
        except Exception as e:
            logger.error(f"Failed to save printer map: {e}")
            # Cleanup dangling temp file if replacement failed
            try:
                if 'tmp_path' in locals() and tmp_path.exists():
                    tmp_path.unlink()
            except Exception:
                pass
            return False

    def save_printer_map(self, printer_map: dict) -> bool:
        """Writes the full printer map to disk atomically."""
        with self._lock:
            return self._save_map_nolock(printer_map)

    def get_printer_map(self) -> dict:
        """Reads the printer map from disk, migrating legacy entries if needed."""
        with self._lock:
            return self._read_map_nolock()

    def upsert_connection(
        self,
        signature: str,
        transport: str,
        device_uri: str,
        queue_name: str,
        cloud_printer_id: Optional[str] = None,
        display_name: Optional[str] = None,
    ) -> bool:
        """
        Adds or updates a single transport entry for a printer safely.

        Args:
            signature:        The stable hardware_signature key.
            transport:        Connection type string: "usb", "network", "ipp", etc.
            device_uri:       The full device URI for this transport.
            queue_name:       The OS-level CUPS queue name or Windows printer name.
            cloud_printer_id: Cloud UUID, if already known.
            display_name:     Human-readable printer name for this entry.
        """
        with self._lock:
            printer_map = self._read_map_nolock()
            entry = printer_map.setdefault(signature, {"connections": {}})

        # Preserve existing cloud_printer_id / display_name if already set
            if cloud_printer_id:
                entry["cloud_printer_id"] = cloud_printer_id
            if display_name and not entry.get("display_name"):
                entry["display_name"] = display_name

        # Set the default value for connections if missing
            if "connections" not in entry:
                entry["connections"] = {}

            entry["connections"][transport] = {
                "device_uri": device_uri,
                "queue_name": queue_name,
                "last_seen": datetime.now(timezone.utc).isoformat(),
            }

            logger.debug(
            f"Upserted {transport} connection for {signature} "
            f"(queue: {queue_name}, uri: {device_uri})"
        )
            return self._save_map_nolock(printer_map)

    def get_best_connection(self, signature: str) -> Optional[dict]:
        """
        Returns the highest-priority available connection for a printer.
        Priority: USB → Network → IPP → Socket → mDNS → LPD → unknown
        """
        printer_map = self.get_printer_map()
        entry = printer_map.get(signature)
        if not entry:
            return None

        connections = entry.get("connections", {})
        if not connections:
            return None

        # Walk priority list and return first match
        for transport in CONNECTION_PRIORITY:
            if transport in connections:
                conn = connections[transport]
                return {
                    "transport": transport,
                    "device_uri": conn.get("device_uri", ""),
                    "queue_name": conn.get("queue_name", ""),
                    "last_seen": conn.get("last_seen", ""),
                }

        # Fallback: return whatever exists (first key)
        transport = next(iter(connections))
        conn = connections[transport]
        return {
            "transport": transport,
            "device_uri": conn.get("device_uri", ""),
            "queue_name": conn.get("queue_name", ""),
        }

    def get_cloud_id_by_signature(self, signature: str) -> Optional[str]:
        """Returns the cloud_printer_id for a given hardware signature."""
        entry = self.get_printer_map().get(signature)
        return entry.get("cloud_printer_id") if entry else None

    def _migrate_legacy_map(self, raw: dict) -> dict:
        """Transparently upgrades old flat-schema entries to the new nested schema."""
        migrated = {}
        for sig, data in raw.items():
            if "connections" in data:
                # Already new schema — pass through
                migrated[sig] = data
            else:
                # Old flat schema — lift into nested connections entry
                transport = data.get("connection_type", "unknown")
                device_uri = data.get("device_uri", "")
                queue_name = data.get("local_name", sig)

                migrated[sig] = {
                    "cloud_printer_id": data.get("cloud_printer_id"),
                    "display_name": queue_name,
                    "connections": {
                        transport: {
                            "device_uri": device_uri,
                            "queue_name": queue_name,
                            "last_seen": None,
                        }
                    },
                }
                logger.debug(f"Migrated legacy printer entry for signature: {sig}")
        return migrated
