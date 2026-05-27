import logging
import os
from pathlib import Path
from typing import Optional
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

    def get_available_printers(self) -> list:
        """Fetches a list of all installed printers on the host machine."""
        logger.debug("Fetching local printers...")
        return self.printer_manager.get_printers()
        
    def get_printer_name_by_cloud_uuid(self, cloud_uuid: str) -> Optional[str]:
        """
        Translates a Cloud UUID back to the printer's best available OS queue name.
        Uses priority routing: USB > Network > IPP.
        """
        printer_map = self.printer_repo.get_printer_map()
        for signature, data in printer_map.items():
            if data.get("cloud_printer_id") == cloud_uuid:
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
        on_success,
        on_failure
    ) -> bool:
        """
        Sends a downloaded file to the local OS printer queue.
        Moves the file through the local state directories (ready -> printing).
        """
        if not file_path.exists():
            logger.error(f"Cannot print job {job_id}: File not found at {file_path}")
            if on_failure: on_failure("File missing from disk.")
            return False
        
        printer_name = self.get_printer_name_by_cloud_uuid(cloud_printer_uuid)

        if not printer_name:
            logger.error(f"Cannot dispatch job: Unknown Cloud UUID '{cloud_printer_uuid}'. Is the printer mapped?")
            if on_failure: on_failure("Printer not mapped locally.")
            return False
        
        if not self.is_printer_ready(printer_name):
            logger.error(
                f"Cannot dispatch job {job_id}: Printer '{printer_name}' is offline."
            )
            if on_failure: on_failure("Physical printer is offline or jammed.")
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
                on_failure=on_failure
            )

            if success_job_id:
                logger.info(
                    f"Successfully sent job {job_id} to {printer_name} (OS Job ID: {success_job_id})"
                )
                return True
            else:
                return False

        except Exception as e:
            logger.error(f"Failed to submit print job {job_id} to printer service: {e}")
            if on_failure:
                on_failure(f"Internal wrapper error: {str(e)}")
                
            return False

    def sync_printers_with_cloud(self):
        """Scans local hardware and registers/updates them on the backend."""
        if not self.api_client:
            logger.error("API Client not provided for sync.")
            return
        
        local_printers = self.get_available_printers() 
        existing_map = self.printer_repo.get_printer_map()
        
        # Format for API: List of dicts with name and capabilities
        payload = []
        detected_signatures = set()
        for p in local_printers:
            signature = p["hardware_signature"]
            if signature in detected_signatures:
                continue
            detected_signatures.add(signature)
            
            known_data = existing_map.get(signature, {})
            known_cloud_id = known_data.get("cloud_printer_id")

            if known_cloud_id:
                logger.debug(f"Known printer detected: {p['name']} -> {known_cloud_id}")
            else:
                logger.info(f"New Printer discovered: {p['name']} (Sig: {signature}). Ready for secure handshake.")
            
            # Build all-transport connections for this signature
            connections = self._build_connections_payload(local_printers, signature)

            payload.append({
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
            })
        
        for sig, data in existing_map.items():
            if sig not in detected_signatures:
                display_name = data.get("display_name") or data.get("local_name", sig)
                logger.warning(f"Printer offline/unplugged: {display_name} ({sig})")
                payload.append({
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
                })
        
        # Call the sync endpoint
        response = self.api_client.sync_printers(payload)
        
        if response and isinstance(response, dict):
            cloud_printers = response.get("synced_printers", [])
            updated_map = {}
            
            for cp in cloud_printers:
                sig = cp["hardware_signature"]
                # Build the new nested connection entry from the sync response
                # The backend echoes back what connections it knows about
                connections = {}
                for conn in cp.get("connections", []):
                    transport = conn.get("transport", "unknown")
                    connections[transport] = {
                        "device_uri": conn.get("device_uri", ""),
                        "queue_name": conn.get("queue_name", cp.get("local_name", sig)),
                        "last_seen": conn.get("last_seen"),
                    }
                
                # Fallback: if backend doesn't return connections array, build from top-level fields
                if not connections:
                    transport = cp.get("connection_type", "unknown")
                    connections[transport] = {
                        "device_uri": cp.get("device_uri", ""),
                        "queue_name": cp.get("local_name", sig),
                        "last_seen": None,
                    }

                updated_map[sig] = {
                    "cloud_printer_id": cp["cloud_printer_id"],
                    "display_name": cp.get("local_name", sig),
                    "connections": connections,
                }

            self.printer_repo.save_printer_map(updated_map)
            logger.info(f"Synced {len(updated_map)} printers. Multi-connection routing map updated.")
            
    def _build_connections_payload(self, local_printers: list, signature: str) -> list:
        """
        Builds the connections array for a given hardware signature,
        collecting all transport variants detected for the same physical printer.
        """
        connections = []
        seen_uris = set()
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

    def check_for_hardware_changes(self):
        """
        Event-driven sync trigger — called by DiscoveryService on OS printer events.
        Compares detected signatures against the saved map and triggers a cloud sync
        if anything has changed (new printer, removed printer, new transport).
        """
        current_local = self.printer_manager.get_printers()
        saved_map = self.printer_repo.get_printer_map()

        needs_sync = False

        # Trigger sync if the physical printer count changes
        current_signatures = {p["hardware_signature"] for p in current_local}
        saved_signatures = set(saved_map.keys())

        if current_signatures != saved_signatures:
            # A printer was added or fully removed
            needs_sync = True
        elif len(current_local) != sum(
            len(e.get("connections", {})) for e in saved_map.values()
        ):
            # Same printers, but a new transport (e.g. USB + WiFi now) was detected
            needs_sync = True

        if needs_sync:
            logger.info("Hardware environment changed. Triggering cloud sync...")
            self.sync_printers_with_cloud()
        else:
            logger.debug("Hardware check complete — no changes detected.")