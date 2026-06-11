"""
Tests for app.services.cleanup_service.CleanupService covering:
  run_cleanup
  _cleanup_directory
  _cleanup_database
"""
import time
from pathlib import Path

import pytest

from app.core import config as cfg_module
from app.core.local_agent_db import LocalAgentDB
from app.services.cleanup_service import CleanupService



# Helpers
def _age_file(path: Path, seconds_old: int) -> None:
    """Back-date a file's mtime so it appears older than it is."""
    old_time = time.time() - seconds_old
    import os
    os.utime(str(path), (old_time, old_time))


def _insert_job(status: str, job_id: str = "j1", days_old: int = 0) -> None:
    modifier = f"-{days_old} days" if days_old else "now"
    with LocalAgentDB.get_connection() as conn:
        conn.execute(
            "INSERT INTO jobs (job_id, printer_id, status, "
            "updated_at) VALUES (?,?,?, datetime(?))",
            (job_id, "p1", status, modifier),
        )
        conn.commit()


def _insert_queue_event(synced: int, event_id: str, days_old: int = 0) -> None:
    modifier = f"-{days_old} days" if days_old else "now"
    with LocalAgentDB.get_connection() as conn:
        conn.execute(
            "INSERT INTO queue_events (job_id, event_type, payload, "
            "synced, created_at) VALUES (?,?,?,?,datetime(?))",
            (event_id, "status_update", "{}", synced, modifier),
        )
        conn.commit()



# CleanupService initialisation
class TestCleanupServiceInit:
    def test_default_retention(self):
        svc = CleanupService()
        assert svc.retention_days == cfg_module.config.CLEANUP_RETENTION_DAYS

    def test_custom_retention(self):
        svc = CleanupService(retention_days=14)
        assert svc.retention_days == 14
        assert svc.retention_seconds == 14 * 24 * 60 * 60



# _cleanup_directory
class TestCleanupDirectory:
    def test_deletes_old_file(self):
        svc = CleanupService(retention_days=1)
        old_file = cfg_module.config.JOB_COMPLETED_DIR / "old.pdf"
        old_file.write_bytes(b"data")
        _age_file(old_file, seconds_old=2 * 24 * 3600)  # 2 days old

        svc._cleanup_directory(cfg_module.config.JOB_COMPLETED_DIR)

        assert not old_file.exists()

    def test_keeps_recent_file(self):
        svc = CleanupService(retention_days=7)
        recent = cfg_module.config.JOB_COMPLETED_DIR / "recent.pdf"
        recent.write_bytes(b"data")
        # Default mtime is now → well within retention

        svc._cleanup_directory(cfg_module.config.JOB_COMPLETED_DIR)

        assert recent.exists()

    def test_skips_nonexistent_directory(self):
        svc = CleanupService()
        fake_dir = cfg_module.config.RUNTIME_DIR / "nonexistent_dir"
        svc._cleanup_directory(fake_dir)  # must not raise

    def test_only_deletes_files_not_subdirs(self):
        svc = CleanupService(retention_days=1)
        subdir = cfg_module.config.JOB_COMPLETED_DIR / "subdir"
        subdir.mkdir()
        _age_file(subdir, seconds_old=2 * 24 * 3600)

        svc._cleanup_directory(cfg_module.config.JOB_COMPLETED_DIR)

        assert subdir.exists()   # directories must not be removed

    def test_frees_disk_space(self):
        svc = CleanupService(retention_days=1)
        for i in range(3):
            f = cfg_module.config.JOB_COMPLETED_DIR / f"old_{i}.pdf"
            f.write_bytes(b"x" * 1024)
            _age_file(f, seconds_old=2 * 24 * 3600)

        svc._cleanup_directory(cfg_module.config.JOB_COMPLETED_DIR)
        remaining = list(cfg_module.config.JOB_COMPLETED_DIR.iterdir())
        assert remaining == []

    def test_cleans_failed_jobs_directory(self):
        svc = CleanupService(retention_days=1)
        f = cfg_module.config.JOB_FAILED_DIR / "failed.pdf"
        f.write_bytes(b"fail")
        _age_file(f, seconds_old=2 * 24 * 3600)

        svc._cleanup_directory(cfg_module.config.JOB_FAILED_DIR)

        assert not f.exists()



# _cleanup_database
class TestCleanupDatabase:
    def test_removes_old_completed_job(self, initialized_db):
        _insert_job("completed", "j_old", days_old=10)
        svc = CleanupService(retention_days=7)
        svc._cleanup_database()
        with LocalAgentDB.get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id='j_old'"
            ).fetchone()
        assert row is None

    def test_removes_old_failed_job(self, initialized_db):
        _insert_job("failed", "j_fail", days_old=10)
        svc = CleanupService(retention_days=7)
        svc._cleanup_database()
        with LocalAgentDB.get_connection() as conn:
            assert conn.execute(
                "SELECT * FROM jobs WHERE job_id='j_fail'"
            ).fetchone() is None

    def test_keeps_recent_completed_job(self, initialized_db):
        _insert_job("completed", "j_recent", days_old=1)
        svc = CleanupService(retention_days=7)
        svc._cleanup_database()
        with LocalAgentDB.get_connection() as conn:
            assert conn.execute(
                "SELECT * FROM jobs WHERE job_id='j_recent'"
            ).fetchone() is not None

    def test_keeps_active_job(self, initialized_db):
        _insert_job("printing", "j_active", days_old=10)
        svc = CleanupService(retention_days=7)
        svc._cleanup_database()
        with LocalAgentDB.get_connection() as conn:
            assert conn.execute(
                "SELECT * FROM jobs WHERE job_id='j_active'"
            ).fetchone() is not None

    def test_removes_old_synced_queue_events(self, initialized_db):
        _insert_queue_event(synced=1, event_id="ev_old", days_old=10)
        svc = CleanupService(retention_days=7)
        svc._cleanup_database()
        with LocalAgentDB.get_connection() as conn:
            assert conn.execute(
                "SELECT * FROM queue_events WHERE job_id='ev_old'"
            ).fetchone() is None

    def test_keeps_recent_synced_queue_event(self, initialized_db):
        _insert_queue_event(synced=1, event_id="ev_recent", days_old=1)
        svc = CleanupService(retention_days=7)
        svc._cleanup_database()
        with LocalAgentDB.get_connection() as conn:
            assert conn.execute(
                "SELECT * FROM queue_events WHERE job_id='ev_recent'"
            ).fetchone() is not None

    def test_keeps_unsynced_old_queue_event(self, initialized_db):
        """Unsynced events must never be deleted — they haven't been sent yet."""
        _insert_queue_event(synced=0, event_id="ev_unsynced", days_old=30)
        svc = CleanupService(retention_days=7)
        svc._cleanup_database()
        with LocalAgentDB.get_connection() as conn:
            assert conn.execute(
                "SELECT * FROM queue_events WHERE job_id='ev_unsynced'"
            ).fetchone() is not None



# run_cleanup (integration)
class TestRunCleanup:
    def test_run_cleanup_does_not_raise(self, initialized_db):
        CleanupService().run_cleanup()

    def test_run_cleanup_cleans_completed_dir(self, initialized_db):
        svc = CleanupService(retention_days=1)
        f = cfg_module.config.JOB_COMPLETED_DIR / "done.pdf"
        f.write_bytes(b"x")
        _age_file(f, seconds_old=2 * 24 * 3600)

        svc.run_cleanup()

        assert not f.exists()

    def test_run_cleanup_cleans_queue_completed_dir(self, initialized_db):
        svc = CleanupService(retention_days=1)
        f = cfg_module.config.QUEUE_COMPLETED_DIR / "event.json"
        f.write_text("{}")
        _age_file(f, seconds_old=2 * 24 * 3600)

        svc.run_cleanup()

        assert not f.exists()
