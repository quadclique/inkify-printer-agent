import logging
import requests
from requests.structures import CaseInsensitiveDict
from requests.adapters import HTTPAdapter
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
        self.agent_id = agent_config.agent_id

        self.token = agent_config.agent_token or config.AGENT_TOKEN

        self.session = requests.Session()
        
        # Increase connection pool size for multithreading
        adapter = HTTPAdapter(pool_connections=10, pool_maxsize=10)
        self.session.mount('http://', adapter)
        self.session.mount('https://', adapter)
        
        self._set_session_headers()

    def _set_session_headers(self):
        """Updates headers dynamically. Used on boot and immediately after pairing."""
        headers = {
            "Content-Type": "application/json",
            "User-Agent": f"{config.APP_NAME}/{config.APP_VERSION}",
            "Connection": "close"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        self.session.headers = CaseInsensitiveDict(headers)

    def update_credentials(self, token: str):
        """Called by PairingService once a permanent UUID is acquired."""
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
                f"{self.base_url}/agent/register", json=payload, timeout=15
            )
            res.raise_for_status()

            data = res.json()

            combined_token = f"{data['agent_uuid']}:{data['agent_secret']}"

            self.update_credentials(combined_token)

            return data
        except requests.exceptions.HTTPError as e:
            logger.error(
                f"Registration failed [{e.response.status_code}]: {e.response.text}"
            )
            return None
        except Exception as e:
            logger.error(f"Failed to connect to registration server: {e}")
            return None

    def sync_printers(self, printers: List[Dict]) -> Optional[Dict]:
        """POST /agent/{agent_id}/printers/sync"""
        return self._request(
            "POST", f"/agent/printers/sync", json={"printers": printers}
        )

    def check_in(self, agent_status: Dict[str, Any]) -> bool:
        """Sends the periodic heartbeat to let the backend know the agent is alive."""
        response = self._request("POST", f"/agent/heartbeat", json=agent_status)
        return response is not None

    def fetch_pending_jobs(self) -> List[Dict[str, Any]]:
        """Polls the backend for new print jobs assigned to this agent."""
        """GET /agent/{agent_id}/jobs/pending"""
        response = self._request("GET", f"/agent/jobs/pending")
        if response and "jobs" in response:
            return response["jobs"]
        return []

    def update_job_status(self, job_id: str, status: str, details: str = "") -> bool:
        """Updates the cloud regarding the progress of a specific job."""
        payload = {"status": status, "details": details}
        response = self._request("PATCH", f"/agent/jobs/{job_id}/status", json=payload)
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

    @with_retries(
        max_retries=config.API_MAX_RETRIES,
        exceptions=(requests.exceptions.ConnectionError, requests.exceptions.Timeout),
    )
    def _request(
        self, method: str, endpoint: str, **kwargs
    ) -> Optional[Dict[str, Any]]:
        """Internal helper to execute requests and catch standard errors."""
        url = f"{self.base_url}/{endpoint.lstrip('/')}"

        # Ensure the header is actually present before the request goes out
        if self.token and "Authorization" not in self.session.headers:
            self.session.headers["Authorization"] = f"Bearer {self.token}"

        req_kwargs: Dict[str, Any] = {"timeout": float(config.API_TIMEOUT_DEFAULT)}
        req_kwargs.update(kwargs)

        try:
            response = self.session.request(method, url, **req_kwargs)
            response.raise_for_status()

            # Return JSON if content exists, else an empty dict for 204 No Content
            return response.json() if response.content else {}

        except requests.exceptions.HTTPError as e:
            logger.error(
                f"HTTP Error [{e.response.status_code}] on {url}: {e.response.text}"
            )
            return None
