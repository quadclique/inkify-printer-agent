"""
Tests for app.services.printer_service.PrinterService covering:
  get_available_printers
  get_printer_name_by_cloud_uuid
  is_printer_ready
  dispatch_job
  sync_printers_with_cloud
  _build_connections_payload
  check_for_hardware_changes
"""
from pathlib import Path
from unittest.mock import MagicMock, patch, call

import pytest
import yaml

from app.core import config as cfg_module
from app.services.printer_service import PrinterService


# Shared helpers
def _usb_printer(name="HP_LaserJet", status="idle", sig="SIG001"):
    return {
        "id": name, "name": name, "status": status,
        "raw_status": "is idle", "connection_type": "usb",
        "device_uri": f"usb://HP/LaserJet?serial={sig}",
        "hardware_signature": sig,
        "supports_color": True, "supports_duplex": False,
    }


def _make_svc(printers=None, printer_map=None,
              api_response=None):
    """Build a PrinterService with all dependencies mocked."""
    mock_api = MagicMock()
    mock_api.sync_printers.return_value = api_response or {"synced_printers": []}

    mock_mgr = MagicMock()
    mock_mgr.get_printers.return_value = printers or [_usb_printer()]
    mock_mgr.print_file_async.return_value = "OS-JOB-1"

    mock_repo = MagicMock()
    mock_repo.get_printer_map.return_value = printer_map or {}
    mock_repo.get_best_connection.return_value = {
        "transport": "usb",
        "queue_name": "HP_LaserJet",
        "device_uri": "usb://HP/LaserJet?serial=SIG001",
    }

    mock_storage = MagicMock()

    svc = PrinterService(mock_api, mock_mgr, mock_repo, mock_storage)
    return svc, mock_api, mock_mgr, mock_repo, mock_storage


# get_available_printers
class TestGetAvailablePrinters:
    def test_delegates_to_printer_manager(self):
        svc, _, mock_mgr, _, _ = _make_svc()
        result = svc.get_available_printers()
        mock_mgr.get_printers.assert_called_once()
        assert isinstance(result, list)

    def test_returns_manager_output_unchanged(self):
        printers = [_usb_printer("P1"), _usb_printer("P2", sig="SIG002")]
        svc, _, _, _, _ = _make_svc(printers=printers)
        assert svc.get_available_printers() == printers

    def test_returns_empty_list_when_no_printers(self):
        svc, _, mock_mgr, _, _ = _make_svc(printers=[])
        assert svc.get_available_printers() == []


# get_printer_name_by_cloud_uuid
class TestGetPrinterNameByCloudUUID:
    def test_returns_queue_name_for_known_uuid(self):
        printer_map = {
            "SIG001": {
                "cloud_printer_id": "cloud-uuid-1",
                "connections": {"usb": {"queue_name": "HP_USB", "device_uri": "usb://..."}}
            }
        }
        svc, _, _, mock_repo, _ = _make_svc(printer_map=printer_map)
        mock_repo.get_printer_map.return_value = printer_map
        mock_repo.get_best_connection.return_value = {
            "transport": "usb", "queue_name": "HP_USB", "device_uri": "usb://..."
        }
        result = svc.get_printer_name_by_cloud_uuid("cloud-uuid-1")
        assert result == "HP_USB"

    def test_returns_none_for_unknown_uuid(self):
        svc, _, _, mock_repo, _ = _make_svc()
        mock_repo.get_printer_map.return_value = {}
        assert svc.get_printer_name_by_cloud_uuid("cloud-uuid-unknown") is None

    def test_returns_none_when_no_connection_found(self):
        printer_map = {"SIG001": {"cloud_printer_id": "cloud-uuid-1"}}
        svc, _, _, mock_repo, _ = _make_svc(printer_map=printer_map)
        mock_repo.get_printer_map.return_value = printer_map
        mock_repo.get_best_connection.return_value = None
        assert svc.get_printer_name_by_cloud_uuid("cloud-uuid-1") is None

    def test_returns_none_for_empty_printer_map(self):
        svc, _, _, mock_repo, _ = _make_svc()
        mock_repo.get_printer_map.return_value = {}
        assert svc.get_printer_name_by_cloud_uuid("any-uuid") is None


# is_printer_ready
class TestIsPrinterReady:
    def test_idle_printer_is_ready(self):
        svc, _, mock_mgr, _, _ = _make_svc(
            printers=[_usb_printer("HP_Laser", status="idle")]
        )
        assert svc.is_printer_ready("HP_Laser") is True

    def test_printing_printer_is_ready(self):
        svc, _, mock_mgr, _, _ = _make_svc(
            printers=[_usb_printer("HP_Laser", status="printing")]
        )
        assert svc.is_printer_ready("HP_Laser") is True

    def test_offline_printer_not_ready(self):
        svc, _, mock_mgr, _, _ = _make_svc(
            printers=[_usb_printer("HP_Laser", status="offline")]
        )
        assert svc.is_printer_ready("HP_Laser") is False

    def test_unknown_printer_not_ready(self):
        svc, _, mock_mgr, _, _ = _make_svc(printers=[])
        assert svc.is_printer_ready("Ghost_Printer") is False

    def test_correct_printer_matched_by_name(self):
        printers = [
            _usb_printer("Offline_Printer", status="offline", sig="SIG_A"),
            _usb_printer("Online_Printer", status="idle", sig="SIG_B"),
        ]
        svc, _, _, _, _ = _make_svc(printers=printers)
        assert svc.is_printer_ready("Online_Printer") is True
        assert svc.is_printer_ready("Offline_Printer") is False


# dispatch_job
class TestDispatchJob:
    def _file(self, tmp_path, name="job.pdf"):
        f = tmp_path / name
        f.write_bytes(b"pdf")
        return f

    def test_successful_dispatch_returns_true(self, tmp_path):
        printer_map = {"SIG001": {"cloud_printer_id": "cloud-1"}}
        svc, _, mock_mgr, mock_repo, _ = _make_svc(printer_map=printer_map)
        mock_repo.get_printer_map.return_value = printer_map
        mock_repo.get_best_connection.return_value = {
            "transport": "usb", "queue_name": "HP_LaserJet", "device_uri": "usb://..."
        }

        on_success = MagicMock()
        on_failure = MagicMock()
        result = svc.dispatch_job(
            "job-1", "cloud-1", self._file(tmp_path),
            copies=1, is_color=False,
            on_success=on_success, on_failure=on_failure,
        )
        assert result is True
        mock_mgr.print_file_async.assert_called_once()

    def test_missing_file_returns_false_and_calls_on_failure(self, tmp_path):
        svc, _, _, _, _ = _make_svc()
        on_failure = MagicMock()
        result = svc.dispatch_job(
            "job-1", "cloud-1", tmp_path / "ghost.pdf",
            copies=1, is_color=False,
            on_success=MagicMock(), on_failure=on_failure,
        )
        assert result is False
        on_failure.assert_called_once()

    def test_unknown_cloud_uuid_returns_false(self, tmp_path):
        svc, _, _, mock_repo, _ = _make_svc()
        mock_repo.get_printer_map.return_value = {}
        on_failure = MagicMock()
        result = svc.dispatch_job(
            "job-1", "unknown-uuid", self._file(tmp_path),
            copies=1, is_color=False,
            on_success=MagicMock(), on_failure=on_failure,
        )
        assert result is False
        on_failure.assert_called_once()

    def test_offline_printer_returns_false(self, tmp_path):
        printer_map = {"SIG001": {"cloud_printer_id": "cloud-1"}}
        svc, _, mock_mgr, mock_repo, _ = _make_svc(
            printers=[_usb_printer(status="offline")],
            printer_map=printer_map,
        )
        mock_repo.get_printer_map.return_value = printer_map
        mock_repo.get_best_connection.return_value = {
            "transport": "usb", "queue_name": "HP_LaserJet", "device_uri": "usb://..."
        }
        on_failure = MagicMock()
        result = svc.dispatch_job(
            "job-1", "cloud-1", self._file(tmp_path),
            copies=1, is_color=False,
            on_success=MagicMock(), on_failure=on_failure,
        )
        assert result is False
        on_failure.assert_called_once()

    def test_print_file_async_called_with_correct_params(self, tmp_path):
        printer_map = {"SIG001": {"cloud_printer_id": "cloud-1"}}
        svc, _, mock_mgr, mock_repo, _ = _make_svc(printer_map=printer_map)
        mock_repo.get_printer_map.return_value = printer_map
        mock_repo.get_best_connection.return_value = {
            "transport": "usb", "queue_name": "HP_LaserJet", "device_uri": "usb://..."
        }
        f = self._file(tmp_path, "myjob.pdf")
        svc.dispatch_job(
            "job-99", "cloud-1", f,
            copies=3, is_color=True,
            on_success=MagicMock(), on_failure=MagicMock(),
        )
        call_kwargs = mock_mgr.print_file_async.call_args
        assert call_kwargs.kwargs.get("copies") == 3 or call_kwargs.args[3] == 3
        assert call_kwargs.kwargs.get("is_color") is True or call_kwargs.args[4] is True

    def test_os_job_id_none_returns_false(self, tmp_path):
        printer_map = {"SIG001": {"cloud_printer_id": "cloud-1"}}
        svc, _, mock_mgr, mock_repo, _ = _make_svc(printer_map=printer_map)
        mock_mgr.print_file_async.return_value = None
        mock_repo.get_printer_map.return_value = printer_map
        mock_repo.get_best_connection.return_value = {
            "transport": "usb", "queue_name": "HP_LaserJet", "device_uri": "usb://..."
        }
        result = svc.dispatch_job(
            "job-1", "cloud-1", self._file(tmp_path),
            copies=1, is_color=False,
            on_success=MagicMock(), on_failure=MagicMock(),
        )
        assert result is False


# sync_printers_with_cloud
class TestSyncPrintersWithCloud:
    def test_calls_api_sync_printers(self):
        svc, mock_api, _, _, _ = _make_svc()
        svc.sync_printers_with_cloud()
        mock_api.sync_printers.assert_called_once()

    def test_payload_includes_detected_printer(self):
        printers = [_usb_printer("HP_Laser", sig="SIG001")]
        svc, mock_api, _, _, _ = _make_svc(printers=printers)
        svc.sync_printers_with_cloud()
        payload = mock_api.sync_printers.call_args[1]["printers"]
        assert any(p["hardware_signature"] == "SIG001" for p in payload)

    def test_offline_printers_included_in_payload(self):
        """Printers in the saved map but not detected must be reported offline."""
        printer_map = {
            "SIG_GONE": {
                "cloud_printer_id": "cloud-gone",
                "display_name": "OldPrinter",
                "connections": {}
            }
        }
        svc, mock_api, _, mock_repo, _ = _make_svc(
            printers=[],  # nothing detected
            printer_map=printer_map,
        )
        mock_repo.get_printer_map.return_value = printer_map
        svc.sync_printers_with_cloud()
        payload = mock_api.sync_printers.call_args[1]["printers"]
        offline = [p for p in payload if not p["is_online"]]
        assert any(p["hardware_signature"] == "SIG_GONE" for p in offline)

    def test_saves_printer_map_after_successful_sync(self):
        api_response = {
            "synced_printers": [{
                "hardware_signature": "SIG001",
                "cloud_printer_id": "cloud-uuid-1",
                "local_name": "HP_LaserJet",
                "connections": [
                    {"transport": "usb", "device_uri": "usb://hp", "queue_name": "HP_LaserJet"}
                ]
            }]
        }
        svc, _, _, mock_repo, _ = _make_svc(api_response=api_response)
        svc.sync_printers_with_cloud()
        mock_repo.save_printer_map.assert_called_once()

    def test_handles_none_api_response_gracefully(self):
        svc, mock_api, _, mock_repo, _ = _make_svc()
        mock_api.sync_printers.return_value = None
        svc.sync_printers_with_cloud()   # must not raise
        mock_repo.save_printer_map.assert_not_called()

    def test_no_printers_detected_or_known_does_nothing(self):
        svc, mock_api, _, mock_repo, _ = _make_svc(printers=[], printer_map={})
        mock_repo.get_printer_map.return_value = {}
        svc.sync_printers_with_cloud()
        mock_api.sync_printers.assert_not_called()

    def test_duplicate_signatures_deduplicated(self):
        """Two entries with the same hardware_signature should produce one payload item."""
        printers = [
            _usb_printer("HP_USB", sig="SIG001"),
            {**_usb_printer("HP_Net", sig="SIG001"), "connection_type": "network",
             "device_uri": "ipp://192.168.1.1"},
        ]
        svc, mock_api, _, _, _ = _make_svc(printers=printers)
        svc.sync_printers_with_cloud()
        payload = mock_api.sync_printers.call_args[1]["printers"]
        sig_counts = [p["hardware_signature"] for p in payload if p.get("is_online")]
        assert sig_counts.count("SIG001") == 1

    def test_connections_fallback_when_backend_omits_connections(self):
        """Backend response without a connections array → fallback to top-level fields."""
        api_response = {
            "synced_printers": [{
                "hardware_signature": "SIG001",
                "cloud_printer_id": "cloud-uuid-1",
                "local_name": "HP_Laser",
                "connection_type": "usb",
                "device_uri": "usb://hp",
                # Note: no "connections" key
            }]
        }
        svc, _, _, mock_repo, _ = _make_svc(api_response=api_response)
        svc.sync_printers_with_cloud()
        saved_map = mock_repo.save_printer_map.call_args[0][0]
        assert "SIG001" in saved_map
        assert "connections" in saved_map["SIG001"]


# _build_connections_payload
class TestBuildConnectionsPayload:
    def test_single_connection(self):
        printers = [_usb_printer("HP", sig="SIG001")]
        svc, _, _, _, _ = _make_svc(printers=printers)
        conns = svc._build_connections_payload(printers, "SIG001")
        assert len(conns) == 1
        assert conns[0]["transport"] == "usb"

    def test_multiple_transports_for_same_signature(self):
        printers = [
            _usb_printer("HP_USB", sig="SIG001"),
            {**_usb_printer("HP_Net", sig="SIG001"), "connection_type": "network",
             "device_uri": "ipp://192.168.1.1"},
        ]
        svc, _, _, _, _ = _make_svc(printers=printers)
        conns = svc._build_connections_payload(printers, "SIG001")
        transports = {c["transport"] for c in conns}
        assert "usb" in transports
        assert "network" in transports

    def test_filters_other_signatures(self):
        printers = [
            _usb_printer("HP", sig="SIG001"),
            _usb_printer("Canon", sig="SIG002"),
        ]
        svc, _, _, _, _ = _make_svc(printers=printers)
        conns = svc._build_connections_payload(printers, "SIG001")
        assert all(c["queue_name"] == "HP" for c in conns)

    def test_deduplicates_same_uri(self):
        printers = [
            _usb_printer("HP", sig="SIG001"),
            _usb_printer("HP", sig="SIG001"),  # exact duplicate
        ]
        svc, _, _, _, _ = _make_svc(printers=printers)
        conns = svc._build_connections_payload(printers, "SIG001")
        assert len(conns) == 1

    def test_empty_printers_returns_empty_list(self):
        svc, _, _, _, _ = _make_svc(printers=[])
        assert svc._build_connections_payload([], "SIG001") == []


# check_for_hardware_changes
class TestCheckForHardwareChanges:
    def test_triggers_sync_when_new_printer_detected(self):
        printers = [_usb_printer(sig="SIG_NEW")]
        svc, mock_api, _, mock_repo, _ = _make_svc(
            printers=printers,
            printer_map={},  # saved map is empty → new printer
        )
        mock_repo.get_printer_map.return_value = {}
        svc.check_for_hardware_changes()
        mock_api.sync_printers.assert_called_once()

    def test_triggers_sync_when_printer_removed(self):
        printer_map = {"SIG_GONE": {"cloud_printer_id": "cloud-gone", "connections": {}}}
        svc, mock_api, _, mock_repo, _ = _make_svc(
            printers=[],  # nothing detected now
            printer_map=printer_map,
        )
        mock_repo.get_printer_map.return_value = printer_map
        svc.check_for_hardware_changes()
        mock_api.sync_printers.assert_called_once()

    def test_no_sync_when_nothing_changed(self):
        """Same signature in detected and saved map → no sync needed."""
        printers = [_usb_printer(sig="SIG001")]
        printer_map = {
            "SIG001": {
                "cloud_printer_id": "cloud-1",
                "connections": {"usb": {"queue_name": "HP", "device_uri": "usb://..."}}
            }
        }
        svc, mock_api, _, mock_repo, _ = _make_svc(
            printers=printers, printer_map=printer_map
        )
        mock_repo.get_printer_map.return_value = printer_map
        svc.check_for_hardware_changes()
        mock_api.sync_printers.assert_not_called()

    def test_triggers_sync_when_new_transport_added(self):
        """Same signature but now has WiFi too → connection count differs → sync."""
        printers = [
            _usb_printer(sig="SIG001"),
            {**_usb_printer(sig="SIG001"), "connection_type": "network",
             "device_uri": "ipp://192.168.1.1", "name": "HP_Net"},
        ]
        printer_map = {
            "SIG001": {
                "cloud_printer_id": "cloud-1",
                "connections": {"usb": {"queue_name": "HP", "device_uri": "usb://..."}}
                # Only 1 connection saved, but 2 now detected
            }
        }
        svc, mock_api, _, mock_repo, _ = _make_svc(
            printers=printers, printer_map=printer_map
        )
        mock_repo.get_printer_map.return_value = printer_map
        svc.check_for_hardware_changes()
        mock_api.sync_printers.assert_called_once()
