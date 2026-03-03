import unittest
from unittest.mock import MagicMock, patch
from app.services.pairing_service import PairingService


class TestPairingFlow(unittest.TestCase):
    def setUp(self):
        # Create mocks for dependencies
        self.mock_api = MagicMock()
        self.mock_cups = MagicMock()

        # Initialize service with mocked API
        self.pairing_service = PairingService(api_client=self.mock_api)
        # Manually swap the cups manager with our mock
        self.pairing_service.cups = self.mock_cups

    @patch("app.services.pairing_service.AgentRepository")
    @patch("app.services.pairing_service.time.sleep", return_value=None)
    @patch("app.services.pairing_service.config") # Patch the instance from config.py
    @patch("app.services.pairing_service.AgentRepository")
    @patch("app.services.pairing_service.time.sleep", return_value=None)
    def test_successful_pairing_flow(self, mock_sleep, mock_repo_class, mock_config):
        # Setup mocks
        mock_repo = mock_repo_class.return_value
        agent_config = MagicMock()
        agent_config.agent_id = None
        mock_repo.get_config.return_value = agent_config
        
        mock_api = MagicMock()
        service = PairingService(api_client=mock_api)

        # 1. Mock initiate_setup
        mock_api.initiate_setup.return_value = {"setup_code": "1234"}

        # 2. Mock polling (Success on second try)
        # Note the key "agent_uuid" must match your code exactly
        mock_api.check_setup_status.side_effect = [
            {"status": "pending"},
            {"status": "claimed", "agent_uuid": "permanent-uuid-555"}
        ]

        # Run
        result = service.ensure_paired()

        # Assert
        self.assertTrue(result)
        self.assertEqual(agent_config.agent_id, "permanent-uuid-555")
        # Ensure the global config object was updated
        self.assertEqual(mock_config.PRINTER_ID, "permanent-uuid-555")

if __name__ == "__main__":
    unittest.main()
