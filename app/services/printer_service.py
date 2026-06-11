import logging
from pathlib import Path
from typing import Optional, List, Dict, Any, Callable

from app.core.config import config

logger = logging.getLogger(__name__)

class PrinterService:
    """
    High-level business logic for handling physical printers.
    Validates files, checks printer availability, and dispatches jobs to the OS.
    """

    def __init__(self, api_client, printer_manager, printer_repo, storage_service):
        self.api_client = api_client
        self.printer_manager = printer_manager
        self.printer_repo = printer_repo
        self.storage_service = storage_service

    def get_available_printers(self) -> List[Dict[str, Any]]:
        """Returns all printers detected by the OS."""
        logger.debug("Fetching local printers from OS...")
        return self.printer_manager.get_printers()

    def get_printer_name_by_cloud_uuid(self, cloud_uuid: str) -> Optional[str]:
        """
        Translates a Cloud UUID back to the printer's best available OS queue name.
        Uses priority routing: USB > Network > IPP.
        """
        printer_map = self.printer_repo.get_printer_map()
        for signature, data in printer_map.items():
            if isinstance(data, dict) and data.get("cloud_printer_id") == cloud_uuid:
                best = self.printer_repo.get_best_connection(signature)
                if best:
                    return best["queue_name"]
        return None

    def is_printer_ready(self, printer_name: str) -> bool:
        """Checks if a specific printer is currently online and ready to accept jobs."""
        printers = self.get_available_printers()
        for p in printers:
            if p["name"] == printer_name:
                return p["status"] in ["idle", "printing"]
        logger.warning(f"Printer '{printer_name}' not found or not ready.")
        return False

    def dispatch_job(
        self,
        job_id: str,
        cloud_printer_uuid: str,
        file_path: Path,
        copies: int,
        is_color: bool,
        on_success: Callable,
        on_failure: Callable,
    ) -> bool:
        """
        Sends a downloaded file to the local OS printer queue.
        Resolves Cloud UUID → OS queue name before dispatching.
        """
        if not file_path.exists():
            msg = f"Print file not found: {file_path}"
            logger.error(msg)
            on_failure(msg)
            return False

        printer_name = self.get_printer_name_by_cloud_uuid(cloud_printer_uuid)
        if not printer_name:
            msg = f"Cloud UUID '{cloud_printer_uuid}' not mapped to any local printer."
            logger.error(msg)
            on_failure(msg)
            return False

        if not self.is_printer_ready(printer_name):
            msg = f"Printer '{printer_name}' is offline or not ready."
            logger.error(msg)
            on_failure(msg)
            return False

        try:
            logger.info(f"Dispatching job {job_id} to printer {printer_name}...")

            # OS Level Print Command
            success_job_id = self.printer_manager.print_file_async(
                printer_name=printer_name,
                file_path=str(file_path),
                title=f"Inkify_{job_id}",
                copies=copies,
                is_color=is_color,
                on_success=on_success,
                on_failure=on_failure,
            )

            if success_job_id:
                logger.info(
                    f"Successfully sent job {job_id} to {printer_name} (OS Job ID: {success_job_id})"
                )
                return True
            return False
        except Exception as e:
            msg = f"Unexpected dispatch error for job {job_id}: {e}"
            logger.error(msg)
            on_failure(msg)
            return False

    def sync_printers_with_cloud(self):
        """Scans local hardware and registers/updates them on the backend."""
        if not self.api_client:
            logger.error("API Client not provided for sync.")
            return

        local_printers = self.get_available_printers()
        existing_map = self.printer_repo.get_printer_map()

        # List of dicts with name and capabilities

        payload: List[Dict] = []
        detected_signatures: set = set()

        # Add detected printers
        for p in local_printers:
            signature = p["hardware_signature"]  
            if not signature:
                continue
                
            if signature in detected_signatures:
                continue
            detected_signatures.add(signature)

            known_data = existing_map.get(signature, {})
            if not isinstance(known_data, dict):
                known_data = {}
            known_cloud_id = known_data.get("cloud_printer_id")

            if known_cloud_id:
                logger.debug(f"Known printer detected: {p['name']} -> {known_cloud_id}")
            else:
                logger.info(f"New Printer discovered: {p['name']} (Sig: {signature}). Ready for secure handshake.")

            # Build all-transport connections for this signature
            [connections, _] = self._build_connections_payload(local_printers, signature)

            payload.append(
                {
                    "cloud_printer_id": known_cloud_id,
                    "name": p["name"],
                    "hardware_id": p["hardware_signature"],
                    "hardware_signature": p["hardware_signature"],
                    "status": p["status"],
                    "raw_status": p.get("raw_status", ""),
                    "is_online": p["status"] in ["idle", "printing"],
                    "connection_type": p["connection_type"],
                    "device_uri": p["device_uri"],
                    "supports_color": p.get("supports_color", False),
                    "supports_duplex": p.get("supports_duplex", False),
                    "connections": connections,
                }
            )

        # Report offline printers (in map but not detected)
        for sig, data in existing_map.items():
            if not isinstance(data, dict):
                continue
                
            if sig not in detected_signatures:
                display_name = data.get("display_name") or data.get("local_name", sig)
                logger.warning(f"Printer offline/unplugged: {display_name} ({sig})")
                payload.append(
                    {
                        "cloud_printer_id": data.get("cloud_printer_id"),
                        "name": display_name,
                        "hardware_signature": sig,
                        "status": "offline",
                        "raw_status": "unplugged",
                        "is_online": False,
                        "connection_type": "unknown",
                        "device_uri": "offline",
                        "supports_color": False,
                        "supports_duplex": False,
                        "connections": [],
                    }
                )

        if not payload:
            logger.info("No printers to sync.")
            return

        # Call the sync endpoint
        response = self.api_client.sync_printers(payload)
        if not response or not isinstance(response, dict):
            logger.warning("Printer sync: no valid response from backend.")
            return

        cloud_printers = response.get("synced_printers", [])
        if not isinstance(cloud_printers, list):
            logger.warning("Printer sync: synced_printers is not a list.")
            return
            
        updated_map: Dict = {}

        for cp in cloud_printers:
            if not isinstance(cp, dict):
                continue
            
            sig = cp["hardware_signature"]
            
            if not sig:
                continue

            connections: Dict = {}
            for conn in cp.get("connections", []):
                if not isinstance(conn, dict):
                    continue
                transport = conn.get("transport", "unknown")
                connections[transport] = {
                    "device_uri": conn.get("device_uri", ""),
                    "queue_name": conn.get("queue_name", cp.get("local_name", sig)),
                    "last_seen": conn.get("last_seen"),
                }

            # Fallback if backend doesn't return connections array
            if not connections:
                transport = cp.get("connection_type", "unknown")
                connections[transport] = {
                    "device_uri": cp.get("device_uri", ""),
                    "queue_name": cp.get("local_name", sig),
                    "last_seen": None,
                }

            updated_map[sig] = {
                "cloud_printer_id": cp["cloud_printer_id"],
                "display_name": cp["name"],
                "connections": connections,
            }

        self.printer_repo.save_printer_map(updated_map)
        logger.info(f"Synced {len(updated_map)} printers. Multi-connection routing map updated.")

    def _build_connections_payload(self, local_printers: list, signature: str) -> List[Dict]:
        """
        Builds the connections array for a given hardware signature,
        collecting all transport variants detected for the same physical printer.
        """
        connections = []
        seen_uris: set = set()
        for p in local_printers:
            if p["hardware_signature"] != signature:
                continue
            uri = p["device_uri"]
            if uri in seen_uris:
                continue
            seen_uris.add(uri)
            connections.append({
                "transport": p["connection_type"],
                "device_uri": uri,
                "queue_name": p["name"],
            })
        return connections

    def check_for_hardware_changes(self) -> None:
        """
        Event-driven sync trigger — called by DiscoveryService on OS printer events.
        Only triggers a cloud sync if the hardware state has actually changed.
        """
        current_local = self.printer_manager.get_printers()
        saved_map = self.printer_repo.get_printer_map()

        # Trigger sync if the physical printer count changes

        current_signatures = {p["hardware_signature"] for p in current_local if "hardware_signature" in p}
        saved_signatures = set(saved_map.keys())

        # Check if signatures changed or connection counts changed
        needs_sync = current_signatures != saved_signatures
        if not needs_sync:
            saved_conn_count = 0
            for data in saved_map.values():
                if isinstance(data, dict):
                    saved_conn_count += len(data.get("connections", {}))
            if len(current_local) != saved_conn_count:
                needs_sync = True

        if needs_sync:
            logger.info("Hardware environment changed. Triggering cloud sync...")
            self.sync_printers_with_cloud()
        else:
            logger.debug("Hardware check complete — no changes detected.")