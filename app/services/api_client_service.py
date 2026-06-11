import logging
import threading
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from typing import Dict, Any, Optional, List

from app.core.config import config
from app.utils.retry_utils import with_retries
from app.utils.hardware_utils import get_hardware_id

logger = logging.getLogger(__name__)


class APIClientService:
    """Handles all outbound HTTP communication with the Inkify backend."""

    def __init__(self, agent_repo):
        self.base_url = config.API_URL.rstrip("/")

        # Pull token from YAML file instead of just env
        agent_config = agent_repo.get_config()
        self.agent_id = agent_config.agent_id

        self.token = agent_config.agent_token or config.AGENT_TOKEN

        self._lock = threading.Lock()

        # Session with connection pooling
        self.session = requests.Session()
        
        # Increase connection pool size for multithreading
        adapter = HTTPAdapter(
            pool_connections=10,
            pool_maxsize=20,
            max_retries=Retry(
                total=0,  # We handle retries ourselves via with_retries decorator
                raise_on_status=False,
            ),
        )
        self.session.mount("http://", adapter)
        self.session.mount("https://", adapter)
        self._set_session_headers()

    def _set_session_headers(self) -> None:
        """Updates headers dynamically. Used on boot and immediately after pairing."""
        self.session.headers.update({
            "Content-Type": "application/json",
            "User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}",
        })
        if self.token:
            self.session.headers.update({"Authorization": f"Bearer {self.token}"})

    def update_credentials(self, token: str) -> None:
        """Called by PairingService after successful registration."""
        with self._lock:
            self.token = token
            self._set_session_headers()
        logger.info("API Client credentials securely updated in memory.")

    def register_agent(
        self, registration_token: str, device_name: str
    ) -> Optional[Dict[str, Any]]:
        """Exchanges a dashboard registration token for a permanent agent secret."""
        try:
            payload = {
                "registration_token": registration_token,
                "device_name": device_name,
                "hardware_id": get_hardware_id(),
            }
            res = requests.post(
                f"{self.base_url}/agent/register",
                json=payload,
                timeout=15,
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}",
                },
            )
            res.raise_for_status()
            return res.json()
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"Registration failed [{e.response.status_code}]: {e.response.text}"
            )
            return None
        except requests.exceptions.ConnectionError:
            logger.error("Registration failed: Cannot connect to server.")
            return None
        except Exception as e:
            logger.error(f"Failed to connect to registration server: {e}")
            return None

    def sync_printers(self, printers: List[Dict]) -> Optional[Dict]:
        """POST /agent/printers/sync"""
        return self._request("POST", "/agent/printers/sync", json={"printers": printers})

    def check_in(self, agent_status: Dict[str, Any]) -> bool:
        """Sends the periodic heartbeat to let the backend know the agent is alive."""
        response = self._request("POST", "/agent/heartbeat", json=agent_status)
        return response is not None

    def pull_next_job(self) -> Optional[Dict[str, Any]]:
        """
        Polls the backend for the next available print job. 
        The backend automatically locks this job so no other agent can grab it.
        """
        return self._request("POST", "/agent/jobs/next")

    def update_job_status(self, job_id: str, status: str, details: str = "") -> bool:
        """Updates the cloud regarding the progress of a specific job."""
        payload = {"status": status, "details": details}
        response = self._request("PATCH", f"/agent/jobs/{job_id}/status", json=payload)
        return response is not None

    def submit_qr_release(self, qr_token: str) -> bool:
        """Sends a scanned QR token to the cloud to release a print job."""
        # _request returns a dict on success, or None on HTTP error
        response = self._request(
            "POST",
            "/print-jobs/agent/scan-release",
            json={"qr_token": qr_token},
        )
        return response is not None

    @with_retries(
        max_retries=config.API_MAX_RETRIES,
        exceptions=(requests.exceptions.ConnectionError, requests.exceptions.Timeout, requests.exceptions.ChunkedEncodingError),
    )
    def download_job_file(self, file_url: str, destination_path: str) -> bool:
        """Downloads the actual print payload (PDF/image) to the local disk."""
        # Check if the backend gave us a full URL (like S3) or a relative path
        url = file_url if file_url.startswith("http") else f"{self.base_url}{file_url}"
        
        try:
            with self.session.get(
                url, stream=True, timeout=config.API_TIMEOUT_DOWNLOAD
            ) as r:
                r.raise_for_status()
                with open(destination_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=config.FILE_CHUNK_SIZE):
                        if chunk:
                            f.write(chunk)
            return True
            
        except (
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
            requests.exceptions.ChunkedEncodingError,
        ) as e:
            logger.warning(f"Network error during download from {url}: {e}. Retrying...")            raise
        except requests.exceptions.HTTPError as e:
            logger.error(f"HTTP error downloading file: {e.response.status_code}")
            return False
        except Exception as e:
            logger.error(f"Failed to download document from {url}: {e}")
            return False
        finally:
            # Always ensure broken incomplete partial downloads are cleaned up
            try:
                if destination_path.exists():
                    destination_path.unlink()
            except Exception:
                pass

    def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetches the current cloud state for a specific job."""
        return self._request("GET", f"/agent/jobs/{job_id}/status")

    @with_retries(
        max_retries=config.API_MAX_RETRIES,
        exceptions=(
            requests.exceptions.ConnectionError,
            requests.exceptions.Timeout,
        ),
    )
    def _request(
        self, method: str, endpoint: str, **kwargs
    ) -> Optional[Dict[str, Any]]:
        
        """Internal helper to execute requests and catch standard errors."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        # Acquire lock ONLY to safely read/modify shared headers
        with self._lock:
            # Ensure the header is actually present before the request goes out
            if self.token and "Authorization" not in self.session.headers:
                self.session.headers.update({"Authorization": f"Bearer {self.token}"})

        # Multiple threads can execute this slow network call simultaneously.
        req_kwargs: Dict[str, Any] = {"timeout": float(config.API_TIMEOUT_DEFAULT)}
        req_kwargs.update(kwargs)

        try:
            response = self.session.request(method, url, **req_kwargs)
            response.raise_for_status()

            # Return JSON if content exists, else an empty dict for 204 No Content
            return response.json() if response.content else {}

        except requests.exceptions.ConnectionError as e:
            logger.warning(f"Connection error to {url}: {e}")
            raise
        except requests.exceptions.Timeout as e:
            logger.warning(f"Timeout on {url}: {e}")
            raise
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP {e.response.status_code} on {method} {url}: {e.response.text[:200]}"
            )
            return None
        except Exception as e:
            logger.error(f"Unexpected error on {method} {url}: {e}")
            return None
