import sys
import threading
import logging

logger = logging.getLogger(__name__)

class QRScannerService:
    """
    Listens on stdin for USB barcode scanner input.
    A USB HID scanner acts as a keyboard that types scanned text + Enter.
    """

    QR_PREFIX = "inkify_job_release:"

    def __init__(self, api_client):
        self.api_client = api_client
        self._is_running = False
        self._thread: threading.Thread

    def start(self) -> None:
        # Prevent starting if stdin is completely unavailable (e.g., some headless daemons)
        if not sys.stdin or not sys.stdin.isatty():
            logger.debug("No interactive TTY detected. QR Scanner listener will not start.")
            # Note: We don't fully exit here because some barcode scanners map to dev/input 
            # instead of a pure TTY depending on the host OS. 
            # However, for stdin-based listening, being defensive is key.
        """Starts the background listener for the USB Barcode Scanner."""
        self._is_running = True
        self._thread = threading.Thread(
            target=self._listen_loop,
            name="QRScannerThread",
            daemon=True,
        )
        self._thread.start()
        logger.info("USB QR Scanner listener started. Waiting for scans...")
    def stop(self) -> None:
        self._is_running = False
        # Note: input() is blocking, so the thread will linger until next input or app exit.
        # Since it's daemon=True, it will cleanly die when the main thread exits.

    def _listen_loop(self) -> None:
        while self._is_running:
            try:
                # The built-in input() function catches the scanner's output 
                # because the scanner simulates a keyboard typing + hitting "Enter"
                scanned_qr = input().strip()
                if not scanned_qr:
                    continue

                if scanned_qr.startswith(self.QR_PREFIX):
                    logger.info("Secure QR Code scanned! Sending to cloud...")
                    self._send_to_cloud(scanned_qr)
                elif scanned_qr:
                    logger.warning("Unrecognized QR code scanned. Ignoring: {scanned[:40]}...")

            except EOFError:
                # Handle environment where stdin is closed
                logger.debug("EOF reached on stdin. Stopping QR scanner loop.")
                break
            except Exception as e:
                logger.error(f"Scanner listener encountered an error: {e}")

    def _send_to_cloud(self, qr_token: str) -> None:
        """Passes the raw token to the backend for validation and release."""
        try:
            # We hit the exact route we built in FastAPI earlier
            success = self.api_client.submit_qr_release(qr_token)
            
            if success:
                logger.info("Cloud validated scan! Job released and will be pulled on next poll.")
            else:
                logger.error(f"Cloud rejected QR Code. QR code may be corrupt/invalid or wrong printer.")
                
        except Exception as e:
            logger.error(f"Failed to submit QR Code: {e}")