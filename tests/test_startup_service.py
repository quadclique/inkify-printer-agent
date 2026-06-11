"""
Tests for app.services.startup_service.StartupService covering:
  ensure_directories
  _cleanup_stale_locks
  initialize_environment
"""
import os
import time
from pathlib import Path

import pytest

from app.core import config as cfg_module
from app.services.startup_service import StartupService


# ensure_directories
class TestEnsureDirectories:
    def test_creates_all_required_dirs(self):
        # isolate_config already remaps dirs to tmp_path but does mkdir;
        # delete one of them to prove ensure_directories recreates it.
        target = cfg_module.config.JOB_DOWNLOAD_DIR
        import shutil
        shutil.rmtree(target, ignore_errors=True)
        assert not target.exists()

        StartupService.ensure_directories()

        assert target.exists()

    def test_idempotent_when_dirs_already_exist(self):
        """Calling twice must not raise."""
        StartupService.ensure_directories()
        StartupService.ensure_directories()

    def test_all_required_dirs_present_after_call(self):
        StartupService.ensure_directories()
        required_dirs = [
            cfg_module.config.RUNTIME_DIR,
            cfg_module.config.LOG_DIR,
            cfg_module.config.CONFIG_DIR,
            cfg_module.config.QUEUE_DIR,
            cfg_module.config.JOB_DIR,
            cfg_module.config.DB_DIR,
            cfg_module.config.LOCK_DIR,
            cfg_module.config.JOB_DOWNLOAD_DIR,
            cfg_module.config.JOB_READY_DIR,
            cfg_module.config.JOB_PRINTING_DIR,
            cfg_module.config.JOB_COMPLETED_DIR,
            cfg_module.config.JOB_FAILED_DIR,
            cfg_module.config.QUEUE_PENDING_DIR,
            cfg_module.config.QUEUE_PROCESSING_DIR,
            cfg_module.config.QUEUE_COMPLETED_DIR,
            cfg_module.config.QUEUE_FAILED_DIR,
        ]
        for d in required_dirs:
            assert d.exists(), f"Missing required directory: {d}"

    def test_sets_restrictive_permissions_on_unix(self):
        if os.name == "nt":
            pytest.skip("Permission check not applicable on Windows")

        import shutil
        target = cfg_module.config.JOB_DOWNLOAD_DIR
        shutil.rmtree(target, ignore_errors=True)

        StartupService.ensure_directories()

        mode = oct(target.stat().st_mode)
        assert mode.endswith("750"), f"Expected 750, got {mode}"

    def test_raises_system_exit_on_permission_error(self, monkeypatch):
        from pathlib import Path

        original_mkdir = Path.mkdir

        def mock_mkdir(self, *args, **kwargs):
            raise PermissionError("no permission")

        monkeypatch.setattr(Path, "mkdir", mock_mkdir)
        with pytest.raises((PermissionError, SystemExit)):
            StartupService.ensure_directories()


# _cleanup_stale_locks
class TestCleanupStaleLocks:
    def _make_lock(self, name: str, age_seconds: int = 0) -> Path:
        lock_file = cfg_module.config.LOCK_DIR / name
        lock_file.write_text("lock")
        if age_seconds > 0:
            old_time = time.time() - age_seconds
            os.utime(str(lock_file), (old_time, old_time))
        return lock_file

    def test_removes_stale_lock_file(self):
        lock = self._make_lock("inkify-agent.lock", age_seconds=120)
        StartupService._cleanup_stale_locks()
        assert not lock.exists()

    def test_keeps_fresh_lock_file(self):
        lock = self._make_lock("inkify-agent.lock", age_seconds=0)
        StartupService._cleanup_stale_locks()
        assert lock.exists()

    def test_does_nothing_when_no_locks(self):
        StartupService._cleanup_stale_locks()   # must not raise

    def test_does_nothing_when_lock_dir_missing(self, monkeypatch):
        monkeypatch.setattr(
            cfg_module.config, "LOCK_DIR", cfg_module.config.LOCK_DIR / "nonexistent"
        )
        StartupService._cleanup_stale_locks()   # must not raise

    def test_removes_multiple_stale_locks(self):
        locks = [
            self._make_lock(f"lock_{i}.lock", age_seconds=120) for i in range(3)
        ]
        StartupService._cleanup_stale_locks()
        for lock in locks:
            assert not lock.exists()

    def test_only_removes_lock_files_not_other_files(self):
        stale_lock = self._make_lock("agent.lock", age_seconds=120)
        other_file = cfg_module.config.LOCK_DIR / "notes.txt"
        other_file.write_text("notes")
        StartupService._cleanup_stale_locks()
        assert not stale_lock.exists()
        assert other_file.exists()


# initialize_environment
class TestInitializeEnvironment:
    def test_runs_without_error(self):
        StartupService.initialize_environment()

    def test_all_dirs_created(self):
        # Remove one dir to confirm initialize_environment recreates it
        import shutil
        shutil.rmtree(cfg_module.config.QUEUE_PENDING_DIR, ignore_errors=True)

        StartupService.initialize_environment()

        assert cfg_module.config.QUEUE_PENDING_DIR.exists()

    def test_stale_locks_removed(self):
        stale = cfg_module.config.LOCK_DIR / "old.lock"
        stale.write_text("lock")
        old_time = time.time() - 120
        os.utime(str(stale), (old_time, old_time))

        StartupService.initialize_environment()

        assert not stale.exists()
