"""
Tests for app.core.config and app.core.security.
"""
import hashlib
from pathlib import Path

import pytest

from app.core.config import config
from app.core.security import calculate_file_hash, verify_checksum



# AppConfig
class TestAppConfig:
    def test_app_name(self):
        assert config.APP_NAME == "Inkify Printer Agent"

    def test_poll_interval_positive(self):
        assert config.JOB_POLL_INTERVAL > 0

    def test_max_poll_interval_gte_min(self):
        assert config.MAX_JOB_POLL_INTERVAL >= config.JOB_POLL_INTERVAL

    def test_file_chunk_size_positive(self):
        assert config.FILE_CHUNK_SIZE > 0

    def test_max_workers_positive(self):
        assert config.MAX_WORKERS > 0

    def test_api_max_retries_non_negative(self):
        assert config.API_MAX_RETRIES >= 0

    def test_heartbeat_interval_positive(self):
        assert config.HEARTBEAT_INTERVAL > 0

    def test_allowed_extensions_is_set(self):
        assert isinstance(config.ALLOWED_EXTENSIONS, set)
        assert ".pdf" in config.ALLOWED_EXTENSIONS

    def test_cleanup_retention_days_positive(self):
        assert config.CLEANUP_RETENTION_DAYS > 0

    def test_update_check_interval_positive(self):
        assert config.UPDATE_CHECK_INTERVAL > 0

    def test_db_file_is_path(self):
        assert isinstance(config.DB_FILE, Path)

    def test_agent_config_file_is_path(self):
        assert isinstance(config.AGENT_CONFIG_FILE, Path)

    def test_printers_config_file_is_path(self):
        assert isinstance(config.PRINTERS_CONFIG_FILE, Path)

    def test_log_dir_is_path(self):
        assert isinstance(config.LOG_DIR, Path)

    def test_update_window_format(self):
        # Should be HH:MM strings
        assert len(config.UPDATE_WINDOW_START) == 5
        assert len(config.UPDATE_WINDOW_END) == 5
        assert config.UPDATE_WINDOW_START[2] == ":"
        assert config.UPDATE_WINDOW_END[2] == ":"



# calculate_file_hash
class TestCalculateFileHash:
    def test_known_value(self, tmp_path):
        f = tmp_path / "test.txt"
        f.write_bytes(b"inkify")
        expected = hashlib.sha256(b"inkify").hexdigest()
        assert calculate_file_hash(f) == expected

    def test_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        expected = hashlib.sha256(b"").hexdigest()
        assert calculate_file_hash(f) == expected

    def test_missing_file_returns_empty_string(self, tmp_path):
        result = calculate_file_hash(tmp_path / "nonexistent.pdf")
        assert result == ""

    def test_large_file_chunks(self, tmp_path):
        """Ensures chunked reading produces the same hash as a single read."""
        data = b"x" * (1024 * 1024)   # 1 MB
        f = tmp_path / "large.bin"
        f.write_bytes(data)
        expected = hashlib.sha256(data).hexdigest()
        assert calculate_file_hash(f, chunk_size=4096) == expected

    def test_returns_hex_string(self, tmp_path):
        f = tmp_path / "f.bin"
        f.write_bytes(b"abc")
        h = calculate_file_hash(f)
        assert isinstance(h, str)
        assert len(h) == 64   # SHA-256 hex digest length
        int(h, 16)             # must be valid hex



# verify_checksum
class TestVerifyChecksum:
    def test_correct_hash(self, tmp_path):
        data = b"hello inkify"
        f = tmp_path / "file.pdf"
        f.write_bytes(data)
        assert verify_checksum(f, hashlib.sha256(data).hexdigest()) is True

    def test_wrong_hash(self, tmp_path):
        f = tmp_path / "file.pdf"
        f.write_bytes(b"hello")
        assert verify_checksum(f, "deadbeef" * 8) is False

    def test_empty_expected_hash_skips_verification(self, tmp_path):
        """An empty hash means the cloud didn't send one — treat as trusted."""
        f = tmp_path / "file.pdf"
        f.write_bytes(b"any content")
        assert verify_checksum(f, "") is True

    def test_case_insensitive_comparison(self, tmp_path):
        data = b"case test"
        f = tmp_path / "f.pdf"
        f.write_bytes(data)
        upper_hash = hashlib.sha256(data).hexdigest().upper()
        assert verify_checksum(f, upper_hash) is True

    def test_missing_file_returns_false(self, tmp_path):
        assert verify_checksum(tmp_path / "ghost.pdf", "abc123") is False
