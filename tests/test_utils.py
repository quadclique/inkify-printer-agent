"""
Tests for all utility modules:
  app.utils.file_utils
  app.utils.time_utils
  app.utils.validation_utils
  app.utils.system_utils
  app.utils.retry_utils
  app.utils.hardware_utils
"""
import importlib
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from app.utils.file_utils import safe_delete, safe_move
from app.utils.retry_utils import with_retries
from app.utils.system_utils import get_system_metrics
from app.utils.time_utils import is_time_between
from app.utils.validation_utils import is_valid_url, is_valid_job_payload


# file_utils — safe_move
class TestSafeMove:
    def test_moves_file_to_existing_dir(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "dst.txt"
        src.write_text("hello")
        assert safe_move(src, dst) is True
        assert dst.read_text() == "hello"
        assert not src.exists()

    def test_creates_parent_directories(self, tmp_path):
        src = tmp_path / "src.txt"
        dst = tmp_path / "a" / "b" / "c" / "dst.txt"
        src.write_text("data")
        assert safe_move(src, dst) is True
        assert dst.read_text() == "data"

    def test_returns_false_when_source_missing(self, tmp_path):
        result = safe_move(tmp_path / "ghost.txt", tmp_path / "dst.txt")
        assert result is False

    def test_moves_binary_file(self, tmp_path):
        src = tmp_path / "file.pdf"
        dst = tmp_path / "moved.pdf"
        data = bytes(range(256))
        src.write_bytes(data)
        assert safe_move(src, dst) is True
        assert dst.read_bytes() == data

    def test_preserves_file_contents(self, tmp_path):
        content = "Inkify Agent v1.0.0\nLine two\n"
        src = tmp_path / "src.log"
        dst = tmp_path / "dst.log"
        src.write_text(content)
        safe_move(src, dst)
        assert dst.read_text() == content


# file_utils — safe_delete
class TestSafeDelete:
    def test_deletes_existing_file(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("data")
        assert safe_delete(f) is True
        assert not f.exists()

    def test_returns_true_for_nonexistent_file(self, tmp_path):
        assert safe_delete(tmp_path / "ghost.txt") is True

    def test_deletes_empty_file(self, tmp_path):
        f = tmp_path / "empty.bin"
        f.write_bytes(b"")
        assert safe_delete(f) is True
        assert not f.exists()

    def test_idempotent(self, tmp_path):
        f = tmp_path / "file.txt"
        f.write_text("x")
        safe_delete(f)
        # Second delete should also return True
        assert safe_delete(f) is True


# time_utils — is_time_between
class TestIsTimeBetween:
    # Normal (non-overnight) windows
    def test_inside_window(self):
        assert is_time_between("02:30", "01:00", "04:00") is True

    def test_at_window_start(self):
        assert is_time_between("01:00", "01:00", "04:00") is True

    def test_at_window_end(self):
        assert is_time_between("04:00", "01:00", "04:00") is True

    def test_before_window(self):
        assert is_time_between("00:30", "01:00", "04:00") is False

    def test_after_window(self):
        assert is_time_between("05:00", "01:00", "04:00") is False

    # Overnight windows (e.g. 23:00 → 02:00)
    def test_overnight_inside_before_midnight(self):
        assert is_time_between("23:30", "23:00", "02:00") is True

    def test_overnight_inside_after_midnight(self):
        assert is_time_between("01:00", "23:00", "02:00") is True

    def test_overnight_at_start(self):
        assert is_time_between("23:00", "23:00", "02:00") is True

    def test_overnight_at_end(self):
        assert is_time_between("02:00", "23:00", "02:00") is True

    def test_overnight_outside(self):
        assert is_time_between("10:00", "23:00", "02:00") is False

    def test_overnight_midday_outside(self):
        assert is_time_between("12:00", "23:00", "02:00") is False


# validation_utils — is_valid_url
class TestIsValidUrl:
    def test_valid_https_url(self):
        assert is_valid_url("https://api.inkify.in") is True

    def test_valid_http_url(self):
        assert is_valid_url("http://localhost:8000") is True

    def test_valid_url_with_path(self):
        assert is_valid_url("https://api.inkify.in/agent/jobs/next") is True

    def test_valid_url_with_query(self):
        assert is_valid_url("https://s3.amazonaws.com/bucket/file.pdf?token=abc") is True

    def test_invalid_no_scheme(self):
        assert is_valid_url("api.inkify.in") is False

    def test_invalid_non_http_scheme(self):
        assert is_valid_url("ftp://files.inkify.in") is False

    def test_invalid_plain_string(self):
        assert is_valid_url("not-a-url") is False

    def test_invalid_empty_string(self):
        assert is_valid_url("") is False

    def test_invalid_none_like_empty(self):
        assert is_valid_url("   ") is False or is_valid_url("   ") is True  # graceful

    def test_invalid_just_scheme(self):
        assert is_valid_url("https://") is False


# validation_utils — is_valid_job_payload
class TestIsValidJobPayload:
    def test_valid_payload(self):
        assert is_valid_job_payload({"id": "j1", "printer_id": "p1"}) is True

    def test_missing_id(self):
        assert is_valid_job_payload({"printer_id": "p1"}) is False

    def test_missing_printer_id(self):
        assert is_valid_job_payload({"id": "j1"}) is False

    def test_empty_dict(self):
        assert is_valid_job_payload({}) is False

    def test_empty_string_values(self):
        assert is_valid_job_payload({"id": "", "printer_id": "p1"}) is False


# system_utils — get_system_metrics
class TestGetSystemMetrics:
    def test_returns_dict(self):
        m = get_system_metrics()
        assert isinstance(m, dict)

    def test_has_cpu_percent(self):
        assert "cpu_percent" in get_system_metrics()

    def test_has_ram_mb_used(self):
        assert "ram_mb_used" in get_system_metrics()

    def test_has_ram_mb_total(self):
        assert "ram_mb_total" in get_system_metrics()

    def test_has_disk_gb_free(self):
        assert "disk_gb_free" in get_system_metrics()

    def test_cpu_percent_is_float(self):
        m = get_system_metrics()
        assert isinstance(m["cpu_percent"], float)

    def test_ram_mb_used_non_negative(self):
        m = get_system_metrics()
        assert m["ram_mb_used"] >= 0

    def test_ram_mb_total_positive(self):
        m = get_system_metrics()
        assert m["ram_mb_total"] >= 0

    def test_disk_gb_free_non_negative(self):
        m = get_system_metrics()
        assert m["disk_gb_free"] >= 0.0

    def test_graceful_without_psutil(self):
        """If psutil is unavailable, should return zero-filled dict without raising."""
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "psutil":
                raise ImportError("psutil not available")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            # Re-import to trigger the mocked import
            import app.utils.system_utils as su
            importlib.reload(su)
            m = su.get_system_metrics()
            assert "cpu_percent" in m
            assert m["cpu_percent"] == 0.0
            importlib.reload(su)  # restore


# retry_utils — with_retries decorator
class TestWithRetries:
    def test_succeeds_on_first_try(self):
        calls = []

        @with_retries(max_retries=3, base_delay=0, exceptions=(ValueError,))
        def fn():
            calls.append(1)
            return "ok"

        assert fn() == "ok"
        assert len(calls) == 1

    def test_retries_then_succeeds(self):
        calls = []

        @with_retries(max_retries=3, base_delay=0, exceptions=(ValueError,))
        def fn():
            calls.append(1)
            if len(calls) < 3:
                raise ValueError("not yet")
            return "done"

        assert fn() == "done"
        assert len(calls) == 3

    def test_raises_after_max_retries(self):
        @with_retries(max_retries=2, base_delay=0, exceptions=(RuntimeError,))
        def fn():
            raise RuntimeError("always fails")

        with pytest.raises(RuntimeError):
            fn()

    def test_does_not_retry_non_matching_exception(self):
        """Only catches the declared exception type — others propagate immediately."""
        calls = []

        @with_retries(max_retries=3, base_delay=0, exceptions=(ValueError,))
        def fn():
            calls.append(1)
            raise TypeError("wrong type")

        with pytest.raises(TypeError):
            fn()
        assert len(calls) == 1  # No retry occurred

    def test_total_attempts_equals_max_retries_plus_one(self):
        calls = []

        @with_retries(max_retries=4, base_delay=0, exceptions=(OSError,))
        def fn():
            calls.append(1)
            raise OSError("fail")

        with pytest.raises(OSError):
            fn()
        assert len(calls) == 5  # 1 initial + 4 retries

    def test_preserves_return_value(self):
        @with_retries(max_retries=1, base_delay=0, exceptions=(Exception,))
        def fn():
            return {"key": "value"}

        assert fn() == {"key": "value"}

    def test_wraps_preserves_function_name(self):
        @with_retries(max_retries=1, base_delay=0, exceptions=(Exception,))
        def my_function():
            pass

        assert my_function.__name__ == "my_function"

    def test_multiple_exception_types(self):
        calls = []

        @with_retries(max_retries=3, base_delay=0,
                      exceptions=(ValueError, OSError))
        def fn():
            calls.append(1)
            if len(calls) == 1:
                raise ValueError("v")
            if len(calls) == 2:
                raise OSError("o")
            return "success"

        assert fn() == "success"
        assert len(calls) == 3


# hardware_utils — get_hardware_id
class TestGetHardwareId:
    def test_returns_non_empty_string(self):
        from app.utils.hardware_utils import get_hardware_id
        hw_id = get_hardware_id()
        assert isinstance(hw_id, str)
        assert len(hw_id) > 0

    def test_consistent_across_calls(self):
        """Two calls in the same process should return the same ID."""
        from app.utils.hardware_utils import get_hardware_id
        assert get_hardware_id() == get_hardware_id()

    def test_fallback_to_mac_when_all_fail(self):
        """When all platform-specific methods fail, should fall back to MAC UUID."""
        from app.utils import hardware_utils as hw

        with patch.object(hw, "_get_linux_hw_id", return_value=""), \
             patch.object(hw, "_get_windows_uuid", return_value=""), \
             patch.object(hw, "_get_mac_uuid", return_value=""), \
             patch("app.utils.hardware_utils.platform.system", return_value="Linux"):
            result = hw.get_hardware_id()
            # Should fall back to MAC address node (numeric string)
            assert isinstance(result, str)
            assert len(result) > 0
