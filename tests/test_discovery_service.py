"""
Tests for app.services.discovery_service.DiscoveryService covering:
  start / stop lifecycle
  _trigger  (debounce logic)
  _fallback_poll
  _start_unix_watcher  (watchdog availability / absent dirs)
  _start_windows_watcher  (pywin32 unavailable path)
"""
import time
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from app.core import config as cfg_module
from app.services.discovery_service import DiscoveryService


def _make_svc(callback=None):
    cb = callback or MagicMock()
    svc = DiscoveryService(on_change=cb)
    svc._debounce_seconds = 0.0   # disable debounce for most tests
    return svc, cb


# start / stop lifecycle
class TestDiscoveryLifecycle:
    def test_start_spawns_fallback_thread(self):
        svc, _ = _make_svc()
        svc.start()
        names = [t.name for t in svc._threads if isinstance(t, threading.Thread)]
        assert any("Fallback" in n for n in names)
        svc.stop()

    def test_stop_sets_stop_event(self):
        svc, _ = _make_svc()
        svc.start()
        svc.stop()
        assert svc._stop_event.is_set()

    def test_stop_clears_threads_list(self):
        svc, _ = _make_svc()
        svc.start()
        svc.stop()
        assert svc._threads == []

    def test_stop_before_start_does_not_raise(self):
        svc, _ = _make_svc()
        svc.stop()


# _trigger — debounce
class TestTriggerDebounce:
    def test_trigger_calls_on_change(self):
        svc, cb = _make_svc()
        svc._trigger("test reason")
        cb.assert_called_once()

    def test_trigger_respects_debounce(self):
        svc, cb = _make_svc()
        svc._debounce_seconds = 10.0   # very long debounce
        svc._trigger("first")
        svc._trigger("second")   # should be suppressed
        assert cb.call_count == 1

    def test_trigger_allows_second_call_after_debounce_expires(self):
        svc, cb = _make_svc()
        svc._debounce_seconds = 0.05
        svc._trigger("first")
        time.sleep(0.1)
        svc._trigger("second")
        assert cb.call_count == 2

    def test_trigger_handles_on_change_exception(self):
        cb = MagicMock(side_effect=Exception("callback error"))
        svc, _ = _make_svc(callback=cb)
        svc._trigger("reason")   # must not propagate the exception

    def test_trigger_updates_last_trigger_time(self):
        svc, _ = _make_svc()
        before = svc._last_trigger_time
        svc._trigger("tick")
        assert svc._last_trigger_time > before


# _fallback_poll
class TestFallbackPoll:
    def test_fallback_poll_calls_trigger_after_interval(self):
        svc, cb = _make_svc()
        # Patch PRINTER_SYNC_INTERVAL to a very short value
        with patch.object(cfg_module.config, "PRINTER_SYNC_INTERVAL", 0.05):
            thread = threading.Thread(target=svc._fallback_poll, daemon=True)
            thread.start()
            time.sleep(0.15)
            svc._stop_event.set()
            thread.join(timeout=1)
        assert cb.call_count >= 1

    def test_fallback_poll_stops_on_stop_event(self):
        svc, cb = _make_svc()
        svc._stop_event.set()   # stop immediately
        with patch.object(cfg_module.config, "PRINTER_SYNC_INTERVAL", 0.01):
            svc._fallback_poll()   # must return without hanging
        cb.assert_not_called()


# _start_unix_watcher
class TestUnixWatcher:
    def test_unix_watcher_falls_back_when_watchdog_missing(self):
        svc, _ = _make_svc()
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "watchdog.observers":
                raise ImportError("watchdog not installed")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            svc._start_unix_watcher()   # must not raise

    def test_unix_watcher_does_not_crash_when_no_cups_dirs(self):
        svc, _ = _make_svc()
        with patch("os.path.isdir", return_value=False):
            try:
                svc._start_unix_watcher()
            except Exception as e:
                pytest.fail(f"_start_unix_watcher raised unexpectedly: {e}")

    def test_unix_watcher_skips_nonexistent_cups_dirs(self):
        svc, _ = _make_svc()
        # If no CUPS dirs exist, no observer should be added to _threads
        initial_count = len(svc._threads)
        with patch("os.path.isdir", return_value=False):
            svc._start_unix_watcher()
        # No new threads added (beyond initial count)
        assert len(svc._threads) == initial_count


# _start_windows_watcher
class TestWindowsWatcher:
    def test_windows_watcher_spawns_thread(self):
        svc, _ = _make_svc()
        # Patch the WMI loop so it exits immediately
        with patch.object(svc, "_windows_wmi_loop"):
            svc._start_windows_watcher()
            assert len(svc._threads) >= 1

    def test_windows_wmi_loop_handles_import_error(self):
        svc, _ = _make_svc()
        import builtins
        real_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name in ("win32com.client", "pythoncom"):
                raise ImportError("pywin32 not available")
            return real_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            svc._windows_wmi_loop()   # must not raise

    def test_windows_wmi_loop_stops_on_stop_event(self):
        svc, _ = _make_svc()
        svc._stop_event.set()

        import sys
        # Provide minimal pywin32 stubs so the loop reaches the while check
        mock_pythoncom = MagicMock()
        mock_wmi_client = MagicMock()
        mock_svc = MagicMock()
        mock_watcher = MagicMock()
        mock_watcher.NextEvent.side_effect = Exception("timeout")
        mock_svc.ExecNotificationQuery.return_value = mock_watcher
        mock_wmi_client.Dispatch.return_value.ConnectServer.return_value = mock_svc

        with patch.dict(sys.modules, {
            "win32com": MagicMock(),
            "win32com.client": mock_wmi_client,
            "pythoncom": mock_pythoncom,
        }):
            svc._windows_wmi_loop()   # must return quickly since stop_event is set
