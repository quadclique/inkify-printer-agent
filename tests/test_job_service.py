"""
Tests for app.services.job_service.JobService covering:
  process_pending_jobs
  recover_interrupted_jobs
  _handle_single_job  (via integration-style tests)
  _register_job_in_db
  _update_db_status
  _update_db_filepath
  _fail_job
  _complete_job
  shutdown
"""
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import time

import pytest

from app.core import config as cfg_module
from app.core.local_agent_db import LocalAgentDB
from app.models.job_model import JobModel
from app.services.job_service import JobService


# Helpers
def _make_svc(initialized_db, api=None, printer_svc=None, storage=None, queue=None, job_repo=None):
    mock_api = api or MagicMock()
    mock_printer = printer_svc or MagicMock()
    mock_storage = storage or MagicMock()
    mock_queue = queue or MagicMock()
    mock_job_repo = job_repo or MagicMock()

    # Sensible defaults
    mock_api.pull_next_job.return_value = {"status": "idle"}
    mock_api.update_job_status.return_value = True
    mock_api.download_job_file.return_value = True
    mock_api.get_job_details.return_value = None
    mock_storage.verify_download.return_value = True
    mock_storage.transition_job_file.side_effect = lambda f, frm, to: (
        getattr(cfg_module.config, f"JOB_{to.upper()}_DIR") / f
    )
    mock_printer.dispatch_job.return_value = True

    svc = JobService(mock_api, mock_printer, mock_storage, mock_queue, mock_job_repo)
    return svc, mock_api, mock_printer, mock_storage, mock_queue


# process_pending_jobs
class TestProcessPendingJobs:
    def test_returns_zero_when_queue_idle(self, initialized_db):
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.pull_next_job.return_value = {"status": "idle"}
        assert svc.process_pending_jobs() == 0

    def test_returns_count_of_jobs_submitted(self, initialized_db):
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        # First call returns a job, second returns idle
        mock_api.pull_next_job.side_effect = [
            {"job": {"id": "j1", "printer_id": "p1", "file_url": "http://x/f.pdf"}},
            {"status": "idle"},
        ]
        count = svc.process_pending_jobs()
        assert count == 1

    def test_processes_multiple_jobs(self, initialized_db):
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.pull_next_job.side_effect = [
            {"job": {"id": "j1", "printer_id": "p1", "file_url": "http://x/f1.pdf"}},
            {"job": {"id": "j2", "printer_id": "p1", "file_url": "http://x/f2.pdf"}},
            {"status": "idle"},
        ]
        count = svc.process_pending_jobs()
        assert count == 2

    def test_stops_on_api_exception(self, initialized_db):
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.pull_next_job.side_effect = Exception("network down")
        count = svc.process_pending_jobs()
        assert count == 0

    def test_stops_when_response_has_no_job_key(self, initialized_db):
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.pull_next_job.return_value = {"status": "ok"}  # no "job" key
        assert svc.process_pending_jobs() == 0

    def test_returns_zero_when_response_is_none(self, initialized_db):
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.pull_next_job.return_value = None
        assert svc.process_pending_jobs() == 0


# recover_interrupted_jobs
class TestRecoverInterruptedJobs:
    def _insert_job(self, status, job_id="stuck_job"):
        with LocalAgentDB.get_connection() as conn:
            conn.execute(
                "INSERT INTO jobs (job_id, printer_id, status) VALUES (?,?,?)",
                (job_id, "p1", status),
            )
            conn.commit()

    def test_no_interrupted_jobs_does_nothing(self, initialized_db):
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        svc.recover_interrupted_jobs()   # must not raise
        mock_api.get_job_details.assert_not_called()

    def test_checks_cloud_for_each_interrupted_job(self, initialized_db):
        self._insert_job("downloading", "j_dl")
        self._insert_job("printing", "j_pr")
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.get_job_details.return_value = {"status": "failed"}
        svc.recover_interrupted_jobs()
        assert mock_api.get_job_details.call_count == 2

    def test_marks_failed_when_cloud_says_cancelled(self, initialized_db):
        self._insert_job("downloading")
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.get_job_details.return_value = {"status": "cancelled"}
        svc.recover_interrupted_jobs()
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE job_id='stuck_job'"
            ).fetchone()
        assert row["status"] == "failed"

    def test_marks_failed_when_cloud_says_refunded(self, initialized_db):
        self._insert_job("printing")
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.get_job_details.return_value = {"status": "refunded"}
        svc.recover_interrupted_jobs()
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE job_id='stuck_job'"
            ).fetchone()
        assert row["status"] == "failed"

    def test_marks_failed_when_cloud_says_printing(self, initialized_db):
        """Safest strategy: fail locally to avoid double-print on restart."""
        self._insert_job("printing")
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.get_job_details.return_value = {"status": "printing"}
        svc.recover_interrupted_jobs()
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE job_id='stuck_job'"
            ).fetchone()
        assert row["status"] == "failed"

    def test_skips_when_cloud_unreachable(self, initialized_db):
        """If cloud is unreachable, leave the job alone for the next cycle."""
        self._insert_job("downloading")
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        mock_api.get_job_details.return_value = None
        svc.recover_interrupted_jobs()   # must not raise
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE job_id='stuck_job'"
            ).fetchone()
        # Status should be unchanged
        assert row["status"] == "downloading"


# Internal DB helpers
class TestJobServiceDBHelpers:
    def test_register_job_in_db(self, initialized_db):
        svc, *_ = _make_svc(initialized_db)
        svc.job_repo.register_job("j-reg", "p1")
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id='j-reg'"
            ).fetchone()
        assert row is not None
        assert row["status"] == "pending"

    def test_register_job_idempotent(self, initialized_db):
        """INSERT OR IGNORE — calling twice must not raise."""
        svc, *_ = _make_svc(initialized_db)
        svc.job_repo.register_job("j-idem", "p1")
        svc.job_repo.register_job("j-idem", "p1")

    def test_update_db_status(self, initialized_db):
        svc, *_ = _make_svc(initialized_db)
        svc.job_repo.register_job("j-stat", "p1")
        svc.job_repo.update_job_status("j-stat", "printing")
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE job_id='j-stat'"
            ).fetchone()
        assert row["status"] == "printing"

    def test_update_db_filepath(self, initialized_db):
        svc, *_ = _make_svc(initialized_db)
        svc.job_repo.register_job("j-fp", "p1")
        svc.job_repo.update_db_filepath("j-fp", "/printing/j-fp.pdf")
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT file_path FROM jobs WHERE job_id='j-fp'"
            ).fetchone()
        assert row["file_path"] == "/printing/j-fp.pdf"


# _fail_job
class TestFailJob:
    def test_marks_job_failed_in_db(self, initialized_db):
        svc, _, _, _, _ = _make_svc(initialized_db)
        svc.job_repo.register_job("j-fail", "p1")
        svc.job_repo.fail_job("j-fail", "Paper jam")
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE job_id='j-fail'"
            ).fetchone()
        assert row["status"] == "failed"

    def test_calls_api_update_status_failed(self, initialized_db):
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        svc.job_repo.register_job("j-fail2", "p1")
        svc.job_repo.fail_job("j-fail2", "Out of paper")
        mock_api.update_job_status.assert_called_with(
            "j-fail2", "failed", details="Out of paper"
        )

    def test_enqueues_event_when_api_fails(self, initialized_db):
        svc, mock_api, _, _, mock_queue = _make_svc(initialized_db)
        mock_api.update_job_status.return_value = False
        svc.job_repo.register_job("j-q", "p1")
        svc.job_repo.fail_job("j-q", "Network error")
        mock_queue.enqueue_event.assert_called_once_with(
            "j-q", "status_update",
            {"status": "failed", "details": "Network error"},
        )

    def test_enqueues_event_when_api_raises(self, initialized_db):
        svc, mock_api, _, _, mock_queue = _make_svc(initialized_db)
        mock_api.update_job_status.side_effect = Exception("timeout")
        svc.job_repo.register_job("j-exc", "p1")
        svc.job_repo.fail_job("j-exc", "Timeout")
        mock_queue.enqueue_event.assert_called_once()

    def test_no_queue_event_when_api_succeeds(self, initialized_db):
        svc, mock_api, _, _, mock_queue = _make_svc(initialized_db)
        mock_api.update_job_status.return_value = True
        svc.job_repo.register_job("j-ok", "p1")
        svc.job_repo.fail_job("j-ok", "reason")
        mock_queue.enqueue_event.assert_not_called()


# _complete_job
class TestCompleteJob:
    def test_marks_job_completed_in_db(self, initialized_db):
        svc, _, _, _, _ = _make_svc(initialized_db)
        svc.job_repo.register_job("j-done", "p1")
        svc.job_repo.complete_job("j-done")
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT status FROM jobs WHERE job_id='j-done'"
            ).fetchone()
        assert row["status"] == "completed"

    def test_calls_api_update_status_completed(self, initialized_db):
        svc, mock_api, _, _, _ = _make_svc(initialized_db)
        svc.job_repo.register_job("j-done2", "p1")
        svc.job_repo.complete_job("j-done2")
        mock_api.update_job_status.assert_called_with("j-done2", "completed")

    def test_enqueues_event_when_api_fails(self, initialized_db):
        svc, mock_api, _, _, mock_queue = _make_svc(initialized_db)
        mock_api.update_job_status.return_value = False
        svc.job_repo.register_job("j-cq", "p1")
        svc.job_repo.complete_job("j-cq")
        mock_queue.enqueue_event.assert_called_once_with(
            "j-cq", "status_update", {"status": "completed"}
        )

    def test_enqueues_event_when_api_raises(self, initialized_db):
        svc, mock_api, _, _, mock_queue = _make_svc(initialized_db)
        mock_api.update_job_status.side_effect = Exception("network error")
        svc.job_repo.register_job("j-cexc", "p1")
        svc.job_repo.complete_job("j-cexc")
        mock_queue.enqueue_event.assert_called_once()

    def test_no_queue_event_when_api_succeeds(self, initialized_db):
        svc, mock_api, _, _, mock_queue = _make_svc(initialized_db)
        mock_api.update_job_status.return_value = True
        svc.job_repo.register_job("j-cok", "p1")
        svc.job_repo.complete_job("j-cok")
        mock_queue.enqueue_event.assert_not_called()


# shutdown
class TestShutdown:
    def test_shutdown_does_not_raise(self, initialized_db):
        svc, *_ = _make_svc(initialized_db)
        svc.shutdown()   # must not raise

    def test_shutdown_is_idempotent(self, initialized_db):
        svc, *_ = _make_svc(initialized_db)
        svc.shutdown()
        svc.shutdown()   # second call must also not raise
