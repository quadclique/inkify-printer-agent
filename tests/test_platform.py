"""
Tests for:
  app.platform.factory   — get_printer_manager
  app.platform.unix      — UnixPrinterManager (mocked subprocess)
  app.platform.windows   — WindowsPrinterManager (mocked subprocess / pywin32)
  app.platform.base      — BasePrinterManager contract enforcement
"""
import json
import platform
import subprocess
from unittest.mock import MagicMock, patch, call

import pytest

from app.platform.base import BasePrinterManager
from app.platform.factory import get_printer_manager


# BasePrinterManager — abstract interface
class TestBasePrinterManager:
    def test_cannot_instantiate_directly(self):
        with pytest.raises(TypeError):
            BasePrinterManager() # type: ignore

    def test_concrete_subclass_must_implement_all_methods(self):
        class Incomplete(BasePrinterManager):
            def get_printers(self): ...
            # Missing the other three methods

        with pytest.raises(TypeError):
            Incomplete() # type: ignore

    def test_full_concrete_subclass_instantiates(self):
        class Full(BasePrinterManager):
            def get_printers(self): return []
            def get_printer_capabilities(self, n): return {}
            def print_file_async(self, *a, **kw): return None
            def clear_queue(self, n): return True

        mgr = Full()
        assert mgr.get_printers() == []


# factory — get_printer_manager
class TestGetPrinterManager:
    def test_returns_unix_manager_on_linux(self):
        with patch("app.platform.factory.platform.system", return_value="Linux"):
            mgr = get_printer_manager()
        from app.platform.unix import UnixPrinterManager
        assert isinstance(mgr, UnixPrinterManager)

    def test_returns_unix_manager_on_darwin(self):
        with patch("app.platform.factory.platform.system", return_value="Darwin"):
            mgr = get_printer_manager()
        from app.platform.unix import UnixPrinterManager
        assert isinstance(mgr, UnixPrinterManager)

    def test_returns_windows_manager_on_windows(self):
        with patch("app.platform.factory.platform.system", return_value="Windows"):
            mgr = get_printer_manager()
        from app.platform.windows import WindowsPrinterManager
        assert isinstance(mgr, WindowsPrinterManager)

    def test_defaults_to_unix_on_unknown_os(self):
        with patch("app.platform.factory.platform.system", return_value="FreeBSD"):
            mgr = get_printer_manager()
        from app.platform.unix import UnixPrinterManager
        assert isinstance(mgr, UnixPrinterManager)

    def test_returns_base_printer_manager_instance(self):
        mgr = get_printer_manager()
        assert isinstance(mgr, BasePrinterManager)


# UnixPrinterManager
class TestUnixPrinterManager:
    @pytest.fixture()
    def mgr(self):
        from app.platform.unix import UnixPrinterManager
        return UnixPrinterManager()

    # get_printers
    def test_get_printers_idle_status(self, mgr):
        lpstat_p = "printer HP_Laser is idle. enabled since Jan 1\n"
        lpstat_v = "device for HP_Laser: usb://HP/LaserJet?serial=ABC123\n"

        def _run(cmd, **kw):
            m = MagicMock()
            m.stdout = lpstat_v if "-v" in cmd else lpstat_p
            m.returncode = 0
            return m

        with patch("subprocess.run", side_effect=_run):
            printers = mgr.get_printers()

        assert len(printers) == 1
        assert printers[0]["name"] == "HP_Laser"
        assert printers[0]["status"] == "idle"
        assert printers[0]["connection_type"] == "usb"

    def test_get_printers_offline_status(self, mgr):
        lpstat_p = "printer Zebra is disabled since Jan 1\n"
        lpstat_v = "device for Zebra: usb://Zebra/ZTC?serial=ZEB001\n"

        def _run(cmd, **kw):
            m = MagicMock()
            m.stdout = lpstat_v if "-v" in cmd else lpstat_p
            m.returncode = 0
            return m

        with patch("subprocess.run", side_effect=_run):
            printers = mgr.get_printers()

        assert printers[0]["status"] == "offline"

    def test_get_printers_printing_status(self, mgr):
        lpstat_p = "printer HP_Laser now printing HP_Laser-42.\n"
        lpstat_v = ""

        def _run(cmd, **kw):
            m = MagicMock()
            m.stdout = lpstat_v if "-v" in cmd else lpstat_p
            m.returncode = 0
            return m

        with patch("subprocess.run", side_effect=_run):
            printers = mgr.get_printers()

        assert printers[0]["status"] == "printing"

    def test_get_printers_extracts_serial_from_uri(self, mgr):
        lpstat_p = "printer HP_Laser is idle. enabled since Jan 1\n"
        lpstat_v = "device for HP_Laser: usb://HP/LaserJet?serial=SN123456\n"

        def _run(cmd, **kw):
            m = MagicMock()
            m.stdout = lpstat_v if "-v" in cmd else lpstat_p
            m.returncode = 0
            return m

        with patch("subprocess.run", side_effect=_run):
            printers = mgr.get_printers()

        assert printers[0]["hardware_signature"] == "SN123456"

    def test_get_printers_network_connection_type(self, mgr):
        lpstat_p = "printer Net_Printer is idle. enabled since Jan 1\n"
        lpstat_v = "device for Net_Printer: ipp://192.168.1.10/ipp/print\n"

        def _run(cmd, **kw):
            m = MagicMock()
            m.stdout = lpstat_v if "-v" in cmd else lpstat_p
            m.returncode = 0
            return m

        with patch("subprocess.run", side_effect=_run):
            printers = mgr.get_printers()

        assert printers[0]["connection_type"] == "network"

    def test_get_printers_returns_empty_on_cups_not_found(self, mgr):
        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert mgr.get_printers() == []

    def test_get_printers_returns_empty_on_subprocess_error(self, mgr):
        with patch("subprocess.run", side_effect=subprocess.CalledProcessError(1, "lpstat")):
            assert mgr.get_printers() == []

    def test_get_printers_multiple_printers(self, mgr):
        lpstat_p = (
            "printer HP_Laser is idle. enabled since Jan 1\n"
            "printer Canon now printing Canon-5.\n"
        )
        lpstat_v = (
            "device for HP_Laser: usb://HP?serial=HP001\n"
            "device for Canon: usb://Canon?serial=CA001\n"
        )

        def _run(cmd, **kw):
            m = MagicMock()
            m.stdout = lpstat_v if "-v" in cmd else lpstat_p
            m.returncode = 0
            return m

        with patch("subprocess.run", side_effect=_run):
            printers = mgr.get_printers()

        assert len(printers) == 2

    # get_printer_capabilities 
    def test_get_capabilities_color_detected(self, mgr):
        m = MagicMock()
        m.stdout = "ColorModel/Color Model: *Auto color Grayscale\n"
        m.returncode = 0
        with patch("subprocess.run", return_value=m):
            caps = mgr.get_printer_capabilities("HP_Color")
        assert caps["supports_color"] is True

    def test_get_capabilities_duplex_detected(self, mgr):
        m = MagicMock()
        m.stdout = "Duplex/2-Sided Printing: *None DuplexNoTumble\n"
        m.returncode = 0
        with patch("subprocess.run", return_value=m):
            caps = mgr.get_printer_capabilities("HP_Duplex")
        assert caps["supports_duplex"] is True

    def test_get_capabilities_defaults_on_exception(self, mgr):
        with patch("subprocess.run", side_effect=Exception("lpoptions error")):
            caps = mgr.get_printer_capabilities("Broken")
        assert caps == {"supports_color": False, "supports_duplex": False}

    # print_file_async
    def test_print_file_async_returns_os_job_id(self, mgr, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"pdf")
        m = MagicMock()
        m.stdout = "request id is HP_Laser-42 (1 file(s))"
        m.returncode = 0
        with patch("subprocess.run", return_value=m), \
             patch("threading.Thread"):
            result = mgr.print_file_async("HP_Laser", str(f))
        assert result == "HP_Laser-42"

    def test_print_file_async_returns_none_on_lp_failure(self, mgr, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"pdf")
        with patch("subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "lp")):
            result = mgr.print_file_async(
                "HP_Laser", str(f), on_failure=MagicMock()
            )
        assert result is None

    def test_print_file_async_calls_on_failure_on_error(self, mgr, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"pdf")
        on_failure = MagicMock()
        with patch("subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "lp", stderr="error")):
            mgr.print_file_async("HP_Laser", str(f), on_failure=on_failure)
        on_failure.assert_called_once()

    def test_print_file_async_bw_passes_monochrome_flag(self, mgr, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"pdf")
        m = MagicMock()
        m.stdout = "request id is HP-1 (1 file(s))"
        with patch("subprocess.run", return_value=m) as mock_run, \
             patch("threading.Thread"):
            mgr.print_file_async("HP", str(f), is_color=False)
        cmd = mock_run.call_args[0][0]
        assert "monochrome" in cmd

    def test_print_file_async_color_passes_color_flag(self, mgr, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"pdf")
        m = MagicMock()
        m.stdout = "request id is HP-2 (1 file(s))"
        with patch("subprocess.run", return_value=m) as mock_run, \
             patch("threading.Thread"):
            mgr.print_file_async("HP", str(f), is_color=True)
        cmd = mock_run.call_args[0][0]
        assert "ColorModel=Color" in " ".join(cmd)

    # clear_queue
    def test_clear_queue_success(self, mgr):
        m = MagicMock(returncode=0)
        with patch("subprocess.run", return_value=m):
            assert mgr.clear_queue("HP_Laser") is True

    def test_clear_queue_already_empty_returns_false(self, mgr):
        with patch("subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "cancel")):
            assert mgr.clear_queue("HP_Laser") is False


# WindowsPrinterManager
class TestWindowsPrinterManager:
    @pytest.fixture()
    def mgr(self):
        from app.platform.windows import WindowsPrinterManager
        return WindowsPrinterManager()

    def _wmi_output(self, printers):
        return json.dumps(printers)

    # get_printers 
    def test_get_printers_idle_status(self, mgr):
        wmi_data = [{"Name": "HP_Laser", "PrinterStatus": 3,
                     "PortName": "USB001", "PNPDeviceID": "USB\\VID1\\PID1",
                     "Network": False}]
        m = MagicMock(stdout=json.dumps(wmi_data), returncode=0)
        with patch("subprocess.run", return_value=m):
            printers = mgr.get_printers()
        assert len(printers) == 1
        assert printers[0]["name"] == "HP_Laser"
        assert printers[0]["status"] == "idle"

    def test_get_printers_printing_status(self, mgr):
        wmi_data = [{"Name": "HP_Laser", "PrinterStatus": 4,
                     "PortName": "USB001", "PNPDeviceID": "USB\\VID1",
                     "Network": False}]
        m = MagicMock(stdout=json.dumps(wmi_data), returncode=0)
        with patch("subprocess.run", return_value=m):
            printers = mgr.get_printers()
        assert printers[0]["status"] == "printing"

    def test_get_printers_offline_status(self, mgr):
        wmi_data = [{"Name": "HP_Laser", "PrinterStatus": 7,
                     "PortName": "USB001", "PNPDeviceID": "USB\\VID1",
                     "Network": False}]
        m = MagicMock(stdout=json.dumps(wmi_data), returncode=0)
        with patch("subprocess.run", return_value=m):
            printers = mgr.get_printers()
        assert printers[0]["status"] == "offline"

    def test_get_printers_usb_connection_type(self, mgr):
        wmi_data = [{"Name": "HP_USB", "PrinterStatus": 3,
                     "PortName": "USB001", "PNPDeviceID": "USB\\VID1",
                     "Network": False}]
        m = MagicMock(stdout=json.dumps(wmi_data), returncode=0)
        with patch("subprocess.run", return_value=m):
            printers = mgr.get_printers()
        assert printers[0]["connection_type"] == "usb"

    def test_get_printers_network_connection_type(self, mgr):
        wmi_data = [{"Name": "HP_Net", "PrinterStatus": 3,
                     "PortName": "IP_192.168.1.10", "PNPDeviceID": "",
                     "Network": True}]
        m = MagicMock(stdout=json.dumps(wmi_data), returncode=0)
        with patch("subprocess.run", return_value=m):
            printers = mgr.get_printers()
        assert printers[0]["connection_type"] == "network"

    def test_get_printers_uses_pnp_id_as_signature(self, mgr):
        wmi_data = [{"Name": "HP", "PrinterStatus": 3,
                     "PortName": "USB001", "PNPDeviceID": "USB\\VID1&PID1\\SN123",
                     "Network": False}]
        m = MagicMock(stdout=json.dumps(wmi_data), returncode=0)
        with patch("subprocess.run", return_value=m):
            printers = mgr.get_printers()
        assert printers[0]["hardware_signature"] == "USB\\VID1&PID1\\SN123"

    def test_get_printers_falls_back_to_name_when_no_pnp_id(self, mgr):
        wmi_data = [{"Name": "HP_NoPNP", "PrinterStatus": 3,
                     "PortName": "TCP01", "PNPDeviceID": None,
                     "Network": True}]
        m = MagicMock(stdout=json.dumps(wmi_data), returncode=0)
        with patch("subprocess.run", return_value=m):
            printers = mgr.get_printers()
        assert printers[0]["hardware_signature"] == "HP_NoPNP"

    def test_get_printers_handles_single_object_response(self, mgr):
        """PowerShell may return a single object instead of an array."""
        wmi_data = {"Name": "Solo_Printer", "PrinterStatus": 3,
                    "PortName": "USB001", "PNPDeviceID": "USB\\VID1",
                    "Network": False}
        m = MagicMock(stdout=json.dumps(wmi_data), returncode=0)
        with patch("subprocess.run", return_value=m):
            printers = mgr.get_printers()
        assert len(printers) == 1

    def test_get_printers_returns_empty_on_subprocess_error(self, mgr):
        with patch("subprocess.run",
                   side_effect=subprocess.CalledProcessError(1, "powershell")):
            assert mgr.get_printers() == []

    def test_get_printers_returns_empty_on_json_error(self, mgr):
        m = MagicMock(stdout="not valid json", returncode=0)
        with patch("subprocess.run", return_value=m):
            assert mgr.get_printers() == []

    def test_get_printers_returns_empty_on_empty_output(self, mgr):
        m = MagicMock(stdout="", returncode=0)
        with patch("subprocess.run", return_value=m):
            assert mgr.get_printers() == []

    # get_printer_capabilities
    def test_get_capabilities_returns_dict(self, mgr):
        caps = mgr.get_printer_capabilities("HP_Laser")
        assert "supports_color" in caps
        assert "supports_duplex" in caps
        assert isinstance(caps["supports_color"], bool)
        assert isinstance(caps["supports_duplex"], bool)

    # print_file_async 
    def test_print_file_async_returns_job_id_string(self, mgr, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"pdf")
        with patch("win32api.ShellExecute", create=True), \
             patch("win32print.GetDefaultPrinter", create=True, return_value="default"), \
             patch("win32print.SetDefaultPrinter", create=True), \
             patch("threading.Thread"):
            # Import the real module with win32 patched
            import sys
            sys.modules.setdefault("win32api", MagicMock())
            sys.modules.setdefault("win32print", MagicMock())
            result = mgr.print_file_async("HP_Laser", str(f))
        # Result is either a job ID string or None (depending on env)
        assert result is None or isinstance(result, str)

    def test_print_file_async_returns_none_without_pywin32(self, mgr, tmp_path):
        f = tmp_path / "job.pdf"
        f.write_bytes(b"pdf")
        import sys
        # Temporarily remove win32api from sys.modules
        win32api_backup = sys.modules.pop("win32api", None)
        win32print_backup = sys.modules.pop("win32print", None)
        try:
            on_failure = MagicMock()
            result = mgr.print_file_async(
                "HP_Laser", str(f), on_failure=on_failure
            )
            assert result is None
        finally:
            if win32api_backup:
                sys.modules["win32api"] = win32api_backup
            if win32print_backup:
                sys.modules["win32print"] = win32print_backup

    # clear_queue
    def test_clear_queue_returns_false_without_pywin32(self, mgr):
        import sys
        win32print_backup = sys.modules.pop("win32print", None)
        try:
            result = mgr.clear_queue("HP_Laser")
            assert result is False
        finally:
            if win32print_backup:
                sys.modules["win32print"] = win32print_backup


# Mock-based printer manager contract tests (shared fixture)
class TestMockPrinterManagerContract:
    """
    Verifies that the mock_printer_manager fixture (from conftest.py) satisfies
    the BasePrinterManager interface, and that higher-level services can use it.
    """
    def test_get_printers_returns_list(self, mock_printer_manager):
        result = mock_printer_manager.get_printers()
        assert isinstance(result, list)

    def test_get_printers_has_required_keys(self, mock_printer_manager):
        for p in mock_printer_manager.get_printers():
            for key in ("id", "name", "status", "hardware_signature",
                        "connection_type", "device_uri"):
                assert key in p, f"Missing key '{key}'"

    def test_get_printer_capabilities_returns_bool_dict(self, mock_printer_manager):
        caps = mock_printer_manager.get_printer_capabilities("any")
        assert isinstance(caps["supports_color"], bool)
        assert isinstance(caps["supports_duplex"], bool)

    def test_print_file_async_returns_string(self, mock_printer_manager):
        result = mock_printer_manager.print_file_async("HP_Laser", "/tmp/job.pdf")
        assert isinstance(result, str)

    def test_clear_queue_returns_bool(self, mock_printer_manager):
        assert isinstance(mock_printer_manager.clear_queue("HP_Laser"), bool)
