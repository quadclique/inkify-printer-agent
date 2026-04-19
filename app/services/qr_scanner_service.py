import threading
import logging
from app.services.api_client_service import APIClientService

logger = logging.getLogger(__name__)

class QRScannerService:
    def __init__(self, api_client: APIClientService):
        self.api_client = api_client
        self.is_running = False

    def start(self):
        """Starts the background listener for the USB Barcode Scanner."""
        self.is_running = True
        # Run in a daemon thread so it doesn't block the main polling loop
        listener_thread = threading.Thread(target=self._listen_loop, daemon=True)
        listener_thread.start()
        logger.info("USB QR Scanner listener started. Waiting for scans...")

    def _listen_loop(self):
        while self.is_running:
            try:
                # The built-in input() function catches the scanner's output 
                # because the scanner simulates a keyboard typing + hitting "Enter"
                scanned_text = input().strip()
                
                if scanned_text.startswith("inkify_job_release:"):
                    logger.info("Secure QR Code scanned! Sending to cloud...")
                    self._send_to_cloud(scanned_text)
                elif scanned_text:
                    logger.warning("Unrecognized QR code scanned. Ignoring.")
                    
            except EOFError:
                # Handle environment where stdin is closed
                pass
            except Exception as e:
                logger.error(f"Scanner listener encountered an error: {e}")

    def _send_to_cloud(self, qr_token: str):
        """Passes the raw token to the backend for validation and release."""
        try:
            # We hit the exact route we built in FastAPI earlier
            success = self.api_client.submit_qr_release(qr_token)
            
            if success:
                logger.info("Cloud validated scan! Job released and will be pulled on next poll.")
            else:
                logger.error(f"Cloud rejected scan. Token may be invalid or wrong printer.")
                
        except Exception as e:
            logger.error(f"Failed to communicate with cloud: {e}")

    def stop(self):
        self.is_running = False