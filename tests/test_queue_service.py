"""
Tests for app.services.queue_service.QueueService covering:
  enqueue_event
  process_queue
  _dispatch_event
"""
import json
from pathlib import Path
from unittest.mock import MagicMock, call

import pytest

from app.core import config as cfg_module
from app.services.queue_service import QueueService


# _dispatch_event
class TestDispatchEvent:
    def test_status_update_calls_api(self, mock_api_client, mock_storage_service, mock_queue_repo):
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        result = svc._dispatch_event("job_123", "status_update", {"status": "completed"})
        assert result is True
        mock_api_client.update_job_status.assert_called_once_with(
            "job_123", "completed", ""
        )

    def test_status_update_with_details(self, mock_api_client, mock_storage_service, mock_queue_repo):
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        svc._dispatch_event(
            "job_456", "status_update", {"status": "failed", "details": "Paper jam"}
        )
        mock_api_client.update_job_status.assert_called_once_with(
            "job_456", "failed", "Paper jam"
        )

    def test_unknown_event_type_returns_true(self, mock_api_client, mock_storage_service, mock_queue_repo):
        """Unknown events should be dropped (True) so they don't block the queue."""
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        result = svc._dispatch_event("j1", "unknown_event", {})
        assert result is True
        mock_api_client.update_job_status.assert_not_called()

    def test_api_returns_false_propagates(self, mock_api_client, mock_storage_service, mock_queue_repo):
        mock_api_client.update_job_status.return_value = False
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        result = svc._dispatch_event("j1", "status_update", {"status": "completed"})
        assert result is False

    def test_api_raises_returns_false(self, mock_api_client, mock_storage_service, mock_queue_repo):
        mock_api_client.update_job_status.side_effect = Exception("network error")
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        result = svc._dispatch_event("j1", "status_update", {"status": "completed"})
        assert result is False


# enqueue_event
class TestEnqueueEvent:
    def test_creates_pending_json_file(self, initialized_db, mock_api_client, mock_storage_service, mock_queue_repo):
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        svc.enqueue_event("job-99", "status_update", {"status": "failed"})

        pending_files = list(cfg_module.config.QUEUE_PENDING_DIR.glob("*.json"))
        assert len(pending_files) == 1

    def test_pending_file_contains_correct_data(
        self, initialized_db, mock_api_client, mock_storage_service, mock_queue_repo
    ):
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        svc.enqueue_event("job-77", "status_update", {"status": "completed"})

        files = list(cfg_module.config.QUEUE_PENDING_DIR.glob("*.json"))
        data = json.loads(files[0].read_text())
        assert data["job_id"] == "job-77"
        assert data["event_type"] == "status_update"
        assert data["payload"]["status"] == "completed"

    def test_file_name_contains_job_id_and_event_type(
        self, initialized_db, mock_api_client, mock_storage_service, mock_queue_repo
    ):
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        svc.enqueue_event("job-55", "status_update", {"status": "failed"})

        files = list(cfg_module.config.QUEUE_PENDING_DIR.glob("*.json"))
        assert "job-55" in files[0].name
        assert "status_update" in files[0].name

    def test_multiple_events_create_multiple_files(
        self, initialized_db, mock_api_client, mock_storage_service, mock_queue_repo
    ):
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        svc.enqueue_event("j1", "status_update", {"status": "failed"})
        svc.enqueue_event("j2", "status_update", {"status": "completed"})

        files = list(cfg_module.config.QUEUE_PENDING_DIR.glob("*.json"))
        assert len(files) == 2

    def test_writes_to_sqlite_ledger(
        self, initialized_db, mock_api_client, mock_storage_service, mock_queue_repo
    ):
        from app.core.local_agent_db import LocalAgentDB
        svc = QueueService(mock_api_client, mock_storage_service, queue_repo=mock_queue_repo)
        svc.enqueue_event("j1", "status_update", {"status": "completed"})

        with LocalAgentDB.get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM queue_events WHERE job_id='j1'"
            ).fetchall()
        assert len(rows) == 1
        assert rows[0]["synced"] == 0


# process_queue
class TestProcessQueue:
    def _make_storage_mock(self):
        """Storage mock that moves files to the correct target dir."""
        mock_storage = MagicMock()

        def transition(filename, frm, to):
            src = getattr(cfg_module.config, f"QUEUE_{frm.upper()}_DIR") / filename
            dst = getattr(cfg_module.config, f"QUEUE_{to.upper()}_DIR") / filename
            if src.exists():
                import shutil
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(src), str(dst))
                return dst
            return None

        mock_storage.transition_queue_file.side_effect = transition
        return mock_storage

    def test_calls_api_for_pending_event(self, initialized_db, mock_api_client, mock_queue_repo):
        mock_storage = self._make_storage_mock()
        svc = QueueService(mock_api_client, mock_storage, mock_queue_repo)
        svc.enqueue_event("job-1", "status_update", {"status": "completed"})
        svc.process_queue()
        mock_api_client.update_job_status.assert_called_once_with(
            "job-1", "completed", ""
        )

    def test_moves_file_to_completed_on_success(self, initialized_db, mock_api_client, mock_queue_repo):
        mock_storage = self._make_storage_mock()
        svc = QueueService(mock_api_client, mock_storage, mock_queue_repo)
        svc.enqueue_event("job-2", "status_update", {"status": "completed"})
        svc.process_queue()

        completed = list(cfg_module.config.QUEUE_COMPLETED_DIR.glob("*.json"))
        assert len(completed) == 1
        assert not list(cfg_module.config.QUEUE_PENDING_DIR.glob("*.json"))

    def test_moves_file_back_to_pending_on_network_failure(
        self, initialized_db, mock_api_client, mock_queue_repo
    ):
        mock_api_client.update_job_status.return_value = False
        mock_storage = self._make_storage_mock()
        svc = QueueService(mock_api_client, mock_storage, mock_queue_repo)
        svc.enqueue_event("job-3", "status_update", {"status": "failed"})
        svc.process_queue()

        # File should be back in pending
        pending = list(cfg_module.config.QUEUE_PENDING_DIR.glob("*.json"))
        assert len(pending) == 1

    def test_stops_processing_on_network_failure(self, initialized_db, mock_api_client, mock_queue_repo):
        """When the network is down, process_queue should not attempt remaining events."""
        mock_api_client.update_job_status.return_value = False
        mock_storage = self._make_storage_mock()
        svc = QueueService(mock_api_client, mock_storage, mock_queue_repo)
        svc.enqueue_event("j1", "status_update", {"status": "failed"})
        svc.enqueue_event("j2", "status_update", {"status": "failed"})
        svc.process_queue()

        # Only one attempt should have been made (stopped on first failure)
        assert mock_api_client.update_job_status.call_count == 1

    def test_marks_event_synced_in_db_on_success(
        self, initialized_db, mock_api_client, mock_queue_repo
    ):
        from app.core.local_agent_db import LocalAgentDB
        mock_storage = self._make_storage_mock()
        svc = QueueService(mock_api_client, mock_storage, mock_queue_repo)
        svc.enqueue_event("job-sync", "status_update", {"status": "completed"})
        svc.process_queue()

        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT synced FROM queue_events WHERE job_id='job-sync'"
            ).fetchone()
        assert row["synced"] == 1

    def test_corrupted_file_moved_to_failed(self, initialized_db, mock_api_client, mock_queue_repo):
        mock_storage = self._make_storage_mock()
        svc = QueueService(mock_api_client, mock_storage, mock_queue_repo)

        # Write a corrupted JSON file directly to pending
        bad_file = cfg_module.config.QUEUE_PENDING_DIR / "99_bad_job_status_update.json"
        bad_file.write_text("this is not valid json {{{")

        svc.process_queue()

        failed = list(cfg_module.config.QUEUE_FAILED_DIR.glob("*.json"))
        assert len(failed) == 1

    def test_empty_pending_dir_does_nothing(self, initialized_db, mock_api_client, mock_queue_repo):
        mock_storage = self._make_storage_mock()
        svc = QueueService(mock_api_client, mock_storage, mock_queue_repo)
        svc.process_queue()  # Should not raise
        mock_api_client.update_job_status.assert_not_called()

    def test_process_multiple_events_in_order(self, initialized_db, mock_api_client, mock_queue_repo):
        mock_storage = self._make_storage_mock()
        svc = QueueService(mock_api_client, mock_storage, mock_queue_repo)

        statuses = []

        def capture_call(job_id, status, details=""):
            statuses.append((job_id, status))
            return True

        mock_api_client.update_job_status.side_effect = capture_call

        svc.enqueue_event("j1", "status_update", {"status": "printing"})
        svc.enqueue_event("j2", "status_update", {"status": "completed"})
        svc.process_queue()

        assert ("j1", "printing") in statuses
        assert ("j2", "completed") in statuses
