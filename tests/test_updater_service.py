"""
Tests for app.services.updater_service.UpdaterService covering:
  _get_current_version
  check_for_updates
  apply_update_if_ready
  _is_maintenance_window
  _trigger_update
"""
import time
from unittest.mock import MagicMock, patch, call

import pytest

from app.core import config as cfg_module
from app.services.updater_service import UpdaterService


def _make_svc(api=None):
    mock_api = api or MagicMock()
    mock_api._request.return_value = None
    svc = UpdaterService(mock_api)
    # Force last_check_time to 0 so check_for_updates always runs
    svc.last_check_time = 0
    return svc, mock_api


# _get_current_version
class TestGetCurrentVersion:
    def test_reads_from_version_file(self):
        cfg_module.config.VERSION_FILE.write_text("2.3.4\n")
        svc, _ = _make_svc()
        # Re-instantiate to pick up the file
        svc2, _ = _make_svc()
        assert svc2.current_version == "2.3.4"

    def test_falls_back_to_config_when_no_file(self):
        # VERSION_FILE points to a non-existent tmp path (from isolate_config)
        svc, _ = _make_svc()
        assert svc.current_version == cfg_module.config.APP_VERSION

    def test_falls_back_to_config_when_file_empty(self):
        cfg_module.config.VERSION_FILE.write_text("")
        svc, _ = _make_svc()
        assert svc.current_version == cfg_module.config.APP_VERSION


# check_for_updates
class TestCheckForUpdates:
    def test_calls_api_version_endpoint(self):
        svc, mock_api = _make_svc()
        mock_api._request.return_value = {"latest_version": "1.0.0", "download_url": ""}
        svc.current_version = "1.0.0"
        svc.check_for_updates()
        mock_api._request.assert_called_once_with("GET", "/agent/version")

    def test_sets_pending_update_url_when_new_version_available(self):
        svc, mock_api = _make_svc()
        mock_api._request.return_value = {
            "latest_version": "2.0.0",
            "download_url": "https://cdn.inkify.in/update.sh",
        }
        svc.current_version = "1.0.0"
        svc.check_for_updates()
        assert svc.pending_update_url == "https://cdn.inkify.in/update.sh"

    def test_does_not_set_pending_url_when_up_to_date(self):
        svc, mock_api = _make_svc()
        mock_api._request.return_value = {
            "latest_version": "1.0.0",
            "download_url": "https://cdn.inkify.in/update.sh",
        }
        svc.current_version = "1.0.0"
        svc.check_for_updates()
        assert svc.pending_update_url == ""

    def test_throttle_prevents_repeat_check(self):
        svc, mock_api = _make_svc()
        mock_api._request.return_value = {"latest_version": "1.0.0", "download_url": ""}
        svc.current_version = "1.0.0"
        svc.check_for_updates()
        svc.check_for_updates()   # should be throttled
        assert mock_api._request.call_count == 1

    def test_reset_throttle_allows_recheck(self):
        svc, mock_api = _make_svc()
        mock_api._request.return_value = {"latest_version": "1.0.0", "download_url": ""}
        svc.current_version = "1.0.0"
        svc.check_for_updates()
        svc.last_check_time = 0   # reset throttle
        svc.check_for_updates()
        assert mock_api._request.call_count == 2

    def test_handles_none_api_response(self):
        svc, mock_api = _make_svc()
        mock_api._request.return_value = None
        svc.check_for_updates()   # must not raise
        assert svc.pending_update_url == ""

    def test_handles_api_exception(self):
        svc, mock_api = _make_svc()
        mock_api._request.side_effect = Exception("network error")
        svc.check_for_updates()   # must not raise


# _is_maintenance_window
class TestIsMaintenanceWindow:
    def _svc_with_window(self, start, end):
        svc, _ = _make_svc()
        cfg_module.config.UPDATE_WINDOW_START = start
        cfg_module.config.UPDATE_WINDOW_END = end
        return svc

    def test_inside_window(self):
        svc = self._svc_with_window("01:00", "04:00")
        with patch("app.services.updater_service.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "02:30"
            assert svc._is_maintenance_window() is True

    def test_outside_window(self):
        svc = self._svc_with_window("01:00", "04:00")
        with patch("app.services.updater_service.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "12:00"
            assert svc._is_maintenance_window() is False

    def test_overnight_window_before_midnight(self):
        svc = self._svc_with_window("23:00", "02:00")
        with patch("app.services.updater_service.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "23:30"
            assert svc._is_maintenance_window() is True

    def test_overnight_window_after_midnight(self):
        svc = self._svc_with_window("23:00", "02:00")
        with patch("app.services.updater_service.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "01:00"
            assert svc._is_maintenance_window() is True

    def test_overnight_window_outside(self):
        svc = self._svc_with_window("23:00", "02:00")
        with patch("app.services.updater_service.datetime") as mock_dt:
            mock_dt.now.return_value.strftime.return_value = "10:00"
            assert svc._is_maintenance_window() is False


# apply_update_if_ready
class TestApplyUpdateIfReady:
    def test_does_nothing_when_no_pending_update(self):
        svc, mock_api = _make_svc()
        svc.pending_update_url = ""
        with patch.object(svc, "_trigger_update") as mock_trigger:
            svc.apply_update_if_ready()
            mock_trigger.assert_not_called()

    def test_does_nothing_outside_maintenance_window(self):
        svc, _ = _make_svc()
        svc.pending_update_url = "https://cdn.inkify.in/update.sh"
        with patch.object(svc, "_is_maintenance_window", return_value=False), \
             patch.object(svc, "_trigger_update") as mock_trigger:
            svc.apply_update_if_ready()
            mock_trigger.assert_not_called()

    def test_triggers_update_inside_window(self):
        svc, _ = _make_svc()
        svc.pending_update_url = "https://cdn.inkify.in/update.sh"
        with patch.object(svc, "_is_maintenance_window", return_value=True), \
             patch.object(svc, "_trigger_update") as mock_trigger:
            svc.apply_update_if_ready()
            mock_trigger.assert_called_once_with("https://cdn.inkify.in/update.sh")


# _trigger_update
class TestTriggerUpdate:
    def test_downloads_update_script(self):
        svc, mock_api = _make_svc()
        mock_api.download_job_file.return_value = True
        with patch("subprocess.Popen"), patch("sys.exit"):
            svc._trigger_update("https://cdn.inkify.in/update.sh")
        mock_api.download_job_file.assert_called_once()

    def test_exits_after_launching_script(self):
        svc, mock_api = _make_svc()
        mock_api.download_job_file.return_value = True
        with patch("subprocess.Popen"), patch("sys.exit") as mock_exit:
            svc._trigger_update("https://cdn.inkify.in/update.sh")
        mock_exit.assert_called_once_with(0)

    def test_does_not_exit_when_download_fails(self):
        svc, mock_api = _make_svc()
        mock_api.download_job_file.return_value = False
        with patch("sys.exit") as mock_exit:
            svc._trigger_update("https://cdn.inkify.in/update.sh")
        mock_exit.assert_not_called()

    def test_handles_exception_gracefully(self):
        svc, mock_api = _make_svc()
        mock_api.download_job_file.side_effect = Exception("disk full")
        svc._trigger_update("https://cdn.inkify.in/update.sh")  # must not raise
