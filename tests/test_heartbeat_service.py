"""
Tests for app.services.heartbeat_service.HeartbeatService covering:
  start / stop lifecycle
  _build_payload
  _run (via integration)
"""
import time
from unittest.mock import MagicMock, patch

import pytest

from app.core import config as cfg_module
from app.services.heartbeat_service import HeartbeatService


def _make_svc(api=None, printer_svc=None):
    mock_api = api or MagicMock()
    mock_api.check_in.return_value = True

    mock_printer = printer_svc or MagicMock()
    mock_printer.get_available_printers.return_value = [
        {
            "id": "HP1", "name": "HP_LaserJet", "status": "idle",
            "connection_type": "usb", "hardware_signature": "SIG001",
        }
    ]
    mock_printer.printer_repo = MagicMock()
    mock_printer.printer_repo.get_printer_map.return_value = {
        "SIG001": {"cloud_printer_id": "cloud-uuid-1"}
    }

    svc = HeartbeatService(mock_api, mock_printer)
    svc.interval = 0.05   # Speed up tests: 50 ms between beats
    return svc, mock_api, mock_printer


# start / stop
class TestHeartbeatLifecycle:
    def test_start_spawns_thread(self):
        svc, _, _ = _make_svc()
        svc.start()
        assert svc._thread is not None
        assert svc._thread.is_alive()
        svc.stop()

    def test_stop_terminates_thread(self):
        svc, _, _ = _make_svc()
        svc.start()
        svc.stop()
        # Allow a moment for the thread to join
        svc._thread.join(timeout=1)
        assert not svc._thread.is_alive()

    def test_start_twice_does_not_create_duplicate_thread(self):
        svc, _, _ = _make_svc()
        svc.start()
        first_thread = svc._thread
        svc.start()  # second call → should be a no-op
        assert svc._thread is first_thread
        svc.stop()

    def test_stop_before_start_does_not_raise(self):
        svc, _, _ = _make_svc()
        svc.stop()   # must not raise

    def test_heartbeat_calls_check_in(self):
        svc, mock_api, _ = _make_svc()
        svc.start()
        time.sleep(0.15)   # allow 2-3 heartbeats at 50 ms interval
        svc.stop()
        assert mock_api.check_in.call_count >= 1

    def test_heartbeat_continues_after_api_failure(self):
        svc, mock_api, _ = _make_svc()
        mock_api.check_in.return_value = False   # API failing
        svc.start()
        time.sleep(0.15)
        svc.stop()
        # Thread should still be alive and beating (not crashed)
        assert mock_api.check_in.call_count >= 1


# _build_payload
class TestBuildPayload:
    def test_payload_has_required_top_level_keys(self):
        svc, _, _ = _make_svc()
        payload = svc._build_payload()
        for key in ("version", "status", "environment", "metrics", "printers"):
            assert key in payload, f"Missing key: {key}"

    def test_status_is_online(self):
        svc, _, _ = _make_svc()
        assert svc._build_payload()["status"] == "online"

    def test_environment_matches_config(self):
        svc, _, _ = _make_svc()
        assert svc._build_payload()["environment"] == cfg_module.config.ENVIRONMENT

    def test_printers_is_list(self):
        svc, _, _ = _make_svc()
        assert isinstance(svc._build_payload()["printers"], list)

    def test_printers_list_contains_detected_printer(self):
        svc, _, _ = _make_svc()
        printers = svc._build_payload()["printers"]
        assert len(printers) == 1
        assert printers[0]["name"] == "HP_LaserJet"

    def test_printer_cloud_id_resolved(self):
        svc, _, _ = _make_svc()
        printers = svc._build_payload()["printers"]
        assert printers[0]["cloud_printer_id"] == "cloud-uuid-1"

    def test_printer_is_online_for_idle(self):
        svc, _, _ = _make_svc()
        printers = svc._build_payload()["printers"]
        assert printers[0]["is_online"] is True

    def test_printer_is_not_online_for_offline(self):
        svc, _, mock_printer = _make_svc()
        mock_printer.get_available_printers.return_value = [{
            "id": "HP1", "name": "HP_LaserJet", "status": "offline",
            "connection_type": "usb", "hardware_signature": "SIG001",
        }]
        printers = svc._build_payload()["printers"]
        assert printers[0]["is_online"] is False

    def test_metrics_dict_present(self):
        svc, _, _ = _make_svc()
        metrics = svc._build_payload()["metrics"]
        assert isinstance(metrics, dict)
        assert "cpu_percent" in metrics

    def test_version_falls_back_to_config_when_no_file(self):
        svc, _, _ = _make_svc()
        # VERSION_FILE is patched to a non-existent path by isolate_config
        payload = svc._build_payload()
        assert payload["version"] == cfg_module.config.APP_VERSION

    def test_version_reads_from_version_file(self):
        svc, _, _ = _make_svc()
        cfg_module.config.VERSION_FILE.write_text("2.5.0")
        payload = svc._build_payload()
        assert payload["version"] == "2.5.0"

    def test_empty_printers_list_when_none_detected(self):
        svc, _, mock_printer = _make_svc()
        mock_printer.get_available_printers.return_value = []
        payload = svc._build_payload()
        assert payload["printers"] == []
