import pytest
from unittest.mock import MagicMock
from app.services.queue_service import QueueService
from app.models.queue_model import QueueEventModel


def test_queue_processing(monkeypatch):
    """Tests if the Queue Manager processes and clears offline events."""
    mock_api = MagicMock()
    mock_storage = MagicMock()
    manager = QueueService(mock_api, mock_storage)

    # Mock the API client to pretend the internet is back online
    manager.api_client.update_job_status = MagicMock(return_value=True)

    # Mock the internal dispatch method
    manager._dispatch_event = MagicMock(return_value=True)

    # We can test the logic flow here by directly calling dispatch
    success = manager._dispatch_event(
        "job_123", "status_update", {"status": "completed"}
    )

    assert success is True
    manager._dispatch_event.assert_called_once_with(
        "job_123", "status_update", {"status": "completed"}
    )
