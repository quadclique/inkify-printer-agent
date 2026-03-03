import logging
import requests
from typing import Dict, Any, Optional, List
from app.core.config import config
from app.utils.retry_utils import with_retries
from app.utils.hardware_utils import get_hardware_id
from app.repositories.agent_repo import AgentRepository

logger = logging.getLogger(__name__)


class APIClientService:
    """Handles all outbound HTTP communication with the Inkify backend."""

    def __init__(self):
        self.base_url = config.API_URL.rstrip("/")

        # Pull token from YAML file instead of just env
        agent_config = AgentRepository().get_config()
        self.token = agent_config.agent_token or config.AGENT_TOKEN

        self.session = requests.Session()
        self._set_session_headers()

    def _set_session_headers(self):
        """Updates headers dynamically. Used on boot and immediately after pairing."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}",
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers.update(headers)

    def update_credentials(self, token: str):
        """Called by PairingService once a permanent UUID is acquired."""
        self.token = token
        self._set_session_headers()
        logger.info("API Client credentials securely updated in memory.")

    # --- SETUP & ONBOARDING ENDPOINTS (Unauthenticated) ---

    def initiate_setup(self) -> Optional[Dict[str, Any]]:
        """Asks the cloud for a temporary 4-digit pairing code."""
        try:
            # Define the payload you want to send
            payload = {"hardware_id": get_hardware_id()}

            # Pass the payload into the 'json' parameter of the POST request
            res = requests.post(
                f"{self.base_url}/agent/setup/initiate",
                json=payload, 
                timeout=10,
            )
            res.raise_for_status()

            # Call .json() without arguments to get the response from the server
            return res.json()

        except Exception as e:
            logger.error(f"Failed to initiate setup: {e}")
            return None

    def check_setup_status(self, setup_code: str) -> Optional[Dict[str, Any]]:
        """Polls to see if the human has typed the 4-digit code into the dashboard."""
        try:
            res = requests.get(
                f"{self.base_url}/agent/setup/status/{setup_code}", timeout=10
            )
            res.raise_for_status()
            return res.json()
        except Exception as e:
            logger.debug(f"Setup status check failed or pending: {e}")
            return None

    @with_retries(
        max_retries=config.API_MAX_RETRIES,
        exceptions=(requests.exceptions.ConnectionError, requests.exceptions.Timeout),
    )
    def _request(
        self, method: str, endpoint: str, **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Internal helper to execute requests and catch standard errors."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        req_kwargs = {"timeout": config.API_TIMEOUT_DEFAULT}
        req_kwargs.update(kwargs)

        try:
            response = self.session.request(method, url, **kwargs)
            response.raise_for_status()

            # Return JSON if content exists, else an empty dict for 204 No Content
            return response.json() if response.content else {}

        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP Error [{response.status_code}] on {url}: {response.text}"
            )
        except requests.exceptions.ConnectionError:
            logger.error(
                f"Connection Error: Could not reach {self.base_url}. Are we offline?"
            )
        except requests.exceptions.Timeout:
            logger.error(f"Timeout Error: The request to {url} took too long.")
        except Exception as e:
            logger.error(f"Unexpected API error: {e}")

        return None

    def check_in(self, agent_status: Dict[str, Any]) -> bool:
        """Sends the periodic heartbeat to let the backend know the agent is alive."""
        printer_id = config.PRINTER_ID
        response = self._request(
            "POST", f"/agent/{printer_id}/connect", json=agent_status
        )
        return response is not None

    def fetch_pending_jobs(self) -> List[Dict[str, Any]]:
        """Polls the backend for new print jobs assigned to this agent."""
        printer_id = config.PRINTER_ID
        response = self._request("GET", f"/agent/{printer_id}/jobs/pending")
        if response and "jobs" in response:
            return response["jobs"]
        return []

    def update_job_status(self, job_id: str, status: str, details: str = "") -> bool:
        """Updates the cloud regarding the progress of a specific job."""
        payload = {"status": status, "details": details}
        response = self._request("PATCH", f"/jobs/{job_id}/status", json=payload)
        return response is not None

    def download_job_file(self, file_url: str, destination_path: str) -> bool:
        """Downloads the actual print payload (PDF/image) to the local disk."""
        try:
            with self.session.get(
                file_url, stream=True, timeout=config.API_TIMEOUT_DOWNLOAD
            ) as r:
                r.raise_for_status()
                with open(destination_path, "wb") as f:
                    for chunk in r.iter_content(chunk_size=config.FILE_CHUNK_SIZE):
                        f.write(chunk)
            return True
        except Exception as e:
            logger.error(f"Failed to download job file from {file_url}: {e}")
            return False


    def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Fetches the current truth from the cloud for a specific job."""
        response = self._request("GET", f"/jobs/{job_id}")
        return response