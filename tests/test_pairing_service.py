"""
Tests for app.services.pairing_service.PairingService covering:
  ensure_paired
  is_paired
"""
from unittest.mock import MagicMock, call

import pytest

from app.models.agent_model import AgentModel
from app.services.pairing_service import PairingService


def _make_svc(api_mock, agent_model=None, save_ok=True):
    """Helper: creates a PairingService with a fully mocked AgentRepository."""
    mock_repo = MagicMock()
    mock_repo.get_config.return_value = agent_model or AgentModel()
    mock_repo.save_config.return_value = save_ok
    return PairingService(api_mock, mock_repo), mock_repo


# is_paired
class TestIsPaired:
    def test_returns_true_when_token_present(self, mock_api_client):
        svc, _ = _make_svc(
            mock_api_client,
            AgentModel(agent_id="id", agent_token="tok"),
        )
        assert svc.is_paired() is True

    def test_returns_false_when_no_token(self, mock_api_client):
        svc, _ = _make_svc(mock_api_client)
        assert svc.is_paired() is False

    def test_returns_false_empty_token(self, mock_api_client):
        svc, _ = _make_svc(mock_api_client, AgentModel(agent_id="id", agent_token=""))
        assert svc.is_paired() is False


# ensure_paired
class TestEnsurePaired:
    def test_already_paired_returns_true_without_api_call(self, mock_api_client):
        """Agent already has credentials — no need to call register."""
        svc, _ = _make_svc(
            mock_api_client,
            AgentModel(agent_id="existing-id", agent_token="existing-token"),
        )
        assert svc.ensure_paired("ignored_token") is True
        mock_api_client.register_agent.assert_not_called()

    def test_no_token_returns_false(self, mock_api_client):
        svc, _ = _make_svc(mock_api_client)
        assert svc.ensure_paired(None) is False

    def test_empty_string_token_returns_false(self, mock_api_client):
        svc, _ = _make_svc(mock_api_client)
        assert svc.ensure_paired("") is False

    def test_successful_registration(self, mock_api_client):
        mock_api_client.register_agent.return_value = {
            "agent_uuid": "new-uuid",
            "agent_secret": "new-secret",
        }
        svc, mock_repo = _make_svc(mock_api_client)
        assert svc.ensure_paired("tkn_test123") is True

    def test_credentials_saved_after_success(self, mock_api_client):
        mock_api_client.register_agent.return_value = {
            "agent_uuid": "new-uuid",
            "agent_secret": "new-secret",
        }
        svc, mock_repo = _make_svc(mock_api_client)
        svc.ensure_paired("tkn_test123")
        mock_repo.save_config.assert_called_once()

    def test_api_client_credentials_updated_after_success(self, mock_api_client):
        mock_api_client.register_agent.return_value = {
            "agent_uuid": "new-uuid",
            "agent_secret": "new-secret",
        }
        svc, _ = _make_svc(mock_api_client)
        svc.ensure_paired("tkn_test123")
        mock_api_client.update_credentials.assert_called_once_with("new-uuid:new-secret")

    def test_combined_token_format(self, mock_api_client):
        """Token passed to update_credentials must be uuid:secret."""
        mock_api_client.register_agent.return_value = {
            "agent_uuid": "uuid-abc",
            "agent_secret": "secret-xyz",
        }
        svc, _ = _make_svc(mock_api_client)
        svc.ensure_paired("tkn_abc")
        mock_api_client.update_credentials.assert_called_once_with("uuid-abc:secret-xyz")

    def test_api_returns_none_returns_false(self, mock_api_client):
        mock_api_client.register_agent.return_value = None
        svc, _ = _make_svc(mock_api_client)
        assert svc.ensure_paired("tkn_bad") is False

    def test_api_missing_agent_uuid_returns_false(self, mock_api_client):
        """Partial API response missing agent_uuid — should return False, not crash."""
        mock_api_client.register_agent.return_value = {"agent_secret": "secret-only"}
        svc, _ = _make_svc(mock_api_client)
        result = svc.ensure_paired("tkn_partial")
        assert result is False

    def test_api_missing_agent_secret_returns_false(self, mock_api_client):
        """Partial API response missing agent_secret — should return False, not crash."""
        mock_api_client.register_agent.return_value = {"agent_uuid": "uuid-only"}
        svc, _ = _make_svc(mock_api_client)
        result = svc.ensure_paired("tkn_partial")
        assert result is False

    def test_save_config_failure_returns_false(self, mock_api_client):
        """If disk write fails, pairing should fail cleanly."""
        mock_api_client.register_agent.return_value = {
            "agent_uuid": "new-uuid",
            "agent_secret": "new-secret",
        }
        svc, mock_repo = _make_svc(mock_api_client, save_ok=False)
        mock_repo.save_config.return_value = False
        result = svc.ensure_paired("tkn_diskfail")
        assert result is False

    def test_api_id_stored_on_client_after_success(self, mock_api_client):
        mock_api_client.register_agent.return_value = {
            "agent_uuid": "stored-uuid",
            "agent_secret": "stored-secret",
        }
        svc, _ = _make_svc(mock_api_client)
        svc.ensure_paired("tkn_store")
        assert svc.api_client.agent_id == "stored-uuid"
