"""
Tests for app.services.storage_service.StorageService covering:
  verify_download
  transition_job_file
  transition_queue_file
  cleanup_failed_download
"""
import pytest

from app.core import config as cfg_module
from app.core.security import calculate_file_hash
from app.services.storage_service import StorageService


@pytest.fixture()
def storage():
    return StorageService()


# verify_download
class TestVerifyDownload:
    def test_valid_hash_returns_true(self, storage, tmp_path):
        data = b"valid pdf content"
        f = tmp_path / "job.pdf"
        f.write_bytes(data)
        import hashlib
        h = hashlib.sha256(data).hexdigest()
        assert storage.verify_download(f, h) is True

    def test_wrong_hash_returns_false(self, storage, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"some content")
        assert storage.verify_download(f, "badhash" * 9) is False

    def test_empty_hash_skips_verification(self, storage, tmp_path):
        """No hash provided → cloud didn't send one → treat as valid."""
        f = tmp_path / "job.pdf"
        f.write_bytes(b"any content")
        assert storage.verify_download(f, "") is True

    def test_none_hash_skips_verification(self, storage, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"any content")
        # StorageService.verify_download should handle None gracefully
        result = storage.verify_download(f, None)
        assert result is True

    def test_missing_file_returns_false(self, storage, tmp_path):
        result = storage.verify_download(tmp_path / "ghost.pdf", "abc123")
        assert result is False


# transition_job_file
class TestTransitionJobFile:
    def test_download_to_ready(self, storage):
        src = cfg_module.config.JOB_DOWNLOAD_DIR / "test_doc.pdf"
        src.write_bytes(b"dummy PDF content")

        new_path = storage.transition_job_file("test_doc.pdf", "download", "ready")

        assert new_path is not None
        assert new_path.exists()
        assert new_path.parent == cfg_module.config.JOB_READY_DIR
        assert not src.exists()

    def test_ready_to_printing(self, storage):
        src = cfg_module.config.JOB_READY_DIR / "job2.pdf"
        src.write_bytes(b"pdf bytes")

        new_path = storage.transition_job_file("job2.pdf", "ready", "printing")

        assert new_path is not None
        assert new_path.parent == cfg_module.config.JOB_PRINTING_DIR
        assert not src.exists()

    def test_printing_to_completed(self, storage):
        src = cfg_module.config.JOB_PRINTING_DIR / "job3.pdf"
        src.write_bytes(b"pdf")

        new_path = storage.transition_job_file("job3.pdf", "printing", "completed")

        assert new_path is not None
        assert new_path.parent == cfg_module.config.JOB_COMPLETED_DIR

    def test_printing_to_failed(self, storage):
        src = cfg_module.config.JOB_PRINTING_DIR / "job4.pdf"
        src.write_bytes(b"pdf")

        new_path = storage.transition_job_file("job4.pdf", "printing", "failed")

        assert new_path is not None
        assert new_path.parent == cfg_module.config.JOB_FAILED_DIR

    def test_missing_source_returns_none(self, storage):
        """File doesn't exist → return None, don't raise."""
        assert storage.transition_job_file("nonexistent.pdf", "download", "ready") is None

    def test_invalid_from_state_returns_none(self, storage):
        assert storage.transition_job_file("f.pdf", "bogus_from", "ready") is None

    def test_invalid_to_state_returns_none(self, storage):
        src = cfg_module.config.JOB_DOWNLOAD_DIR / "f.pdf"
        src.write_bytes(b"x")
        assert storage.transition_job_file("f.pdf", "download", "bogus_to") is None

    def test_both_states_invalid_returns_none(self, storage):
        assert storage.transition_job_file("f.pdf", "bogus_from", "bogus_to") is None

    def test_file_contents_preserved_after_move(self, storage):
        data = b"important pdf data that must survive a move"
        src = cfg_module.config.JOB_DOWNLOAD_DIR / "preserve.pdf"
        src.write_bytes(data)

        new_path = storage.transition_job_file("preserve.pdf", "download", "ready")
        assert new_path.read_bytes() == data

    def test_source_removed_after_move(self, storage):
        src = cfg_module.config.JOB_DOWNLOAD_DIR / "remove_me.pdf"
        src.write_bytes(b"x")

        storage.transition_job_file("remove_me.pdf", "download", "ready")
        assert not src.exists()


# transition_queue_file
class TestTransitionQueueFile:
    def test_pending_to_processing(self, storage):
        src = cfg_module.config.QUEUE_PENDING_DIR / "1_j1_status_update.json"
        src.write_text('{"event_id": 1}')

        result = storage.transition_queue_file(
            "1_j1_status_update.json", "pending", "processing"
        )

        assert result is not None
        assert result.parent == cfg_module.config.QUEUE_PROCESSING_DIR
        assert not src.exists()

    def test_processing_to_completed(self, storage):
        src = cfg_module.config.QUEUE_PROCESSING_DIR / "2_j2_status_update.json"
        src.write_text('{"event_id": 2}')

        result = storage.transition_queue_file(
            "2_j2_status_update.json", "processing", "completed"
        )

        assert result is not None
        assert result.parent == cfg_module.config.QUEUE_COMPLETED_DIR

    def test_processing_to_pending_on_failure(self, storage):
        src = cfg_module.config.QUEUE_PROCESSING_DIR / "3_j3_status_update.json"
        src.write_text('{"event_id": 3}')

        result = storage.transition_queue_file(
            "3_j3_status_update.json", "processing", "pending"
        )

        assert result is not None
        assert result.parent == cfg_module.config.QUEUE_PENDING_DIR

    def test_processing_to_failed_on_corruption(self, storage):
        src = cfg_module.config.QUEUE_PROCESSING_DIR / "4_j4_status_update.json"
        src.write_text("bad json{{{")

        result = storage.transition_queue_file(
            "4_j4_status_update.json", "processing", "failed"
        )

        assert result is not None
        assert result.parent == cfg_module.config.QUEUE_FAILED_DIR

    def test_missing_source_returns_none_silently(self, storage):
        """File already grabbed by another thread → silent None, no exception."""
        result = storage.transition_queue_file(
            "nonexistent.json", "pending", "processing"
        )
        assert result is None

    def test_invalid_from_state_returns_none(self, storage):
        assert storage.transition_queue_file("f.json", "bogus", "processing") is None

    def test_invalid_to_state_returns_none(self, storage):
        src = cfg_module.config.QUEUE_PENDING_DIR / "f.json"
        src.write_text("{}")
        assert storage.transition_queue_file("f.json", "pending", "bogus_to") is None


# cleanup_failed_download
class TestCleanupFailedDownload:
    def test_deletes_existing_file(self, storage):
        corrupt = cfg_module.config.JOB_DOWNLOAD_DIR / "bad_job.pdf"
        corrupt.write_bytes(b"truncated")

        storage.cleanup_failed_download("bad_job.pdf")

        assert not corrupt.exists()

    def test_does_not_raise_if_file_missing(self, storage):
        """If the file is already gone, cleanup should be a no-op."""
        storage.cleanup_failed_download("already_gone.pdf")  # must not raise
