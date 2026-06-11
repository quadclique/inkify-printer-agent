"""
Tests for app.services.qr_scanner_service.QRScannerService covering:
  start / stop lifecycle
  _listen_loop
  _send_to_cloud
"""
import time
from io import StringIO
from unittest.mock import MagicMock, patch

import pytest

from app.services.qr_scanner_service import QRScannerService


def _make_svc(api=None):
    mock_api = api or MagicMock()
    mock_api.submit_qr_release.return_value = True
    return QRScannerService(mock_api), mock_api


# start / stop lifecycle
class TestQRScannerLifecycle:
    def test_start_spawns_daemon_thread(self):
        svc, _ = _make_svc()
        with patch("builtins.input", side_effect=EOFError):
            svc.start()
            assert svc._thread is not None
            assert svc._thread.daemon is True
            svc.stop()

    def test_stop_sets_is_running_false(self):
        svc, _ = _make_svc()
        with patch("builtins.input", side_effect=EOFError):
            svc.start()
            svc.stop()
            assert svc._is_running is False

    def test_stop_before_start_does_not_raise(self):
        svc, _ = _make_svc()
        svc.stop()   # must not raise


# _send_to_cloud
class TestSendToCloud:
    def test_calls_submit_qr_release(self):
        svc, mock_api = _make_svc()
        svc._send_to_cloud("inkify_job_release:TOKEN123")
        mock_api.submit_qr_release.assert_called_once_with(
            "inkify_job_release:TOKEN123"
        )

    def test_handles_api_returning_false(self):
        svc, mock_api = _make_svc()
        mock_api.submit_qr_release.return_value = False
        svc._send_to_cloud("inkify_job_release:BAD")   # must not raise

    def test_handles_api_raising_exception(self):
        svc, mock_api = _make_svc()
        mock_api.submit_qr_release.side_effect = Exception("network error")
        svc._send_to_cloud("inkify_job_release:TOKEN")   # must not raise

    def test_passes_full_token_string(self):
        svc, mock_api = _make_svc()
        token = "inkify_job_release:abc123xyz"
        svc._send_to_cloud(token)
        mock_api.submit_qr_release.assert_called_once_with(token)


# _listen_loop (unit — drives the loop with controlled input)
class TestListenLoop:
    def test_valid_qr_token_triggers_send_to_cloud(self):
        svc, mock_api = _make_svc()
        inputs = iter(["inkify_job_release:TOKEN999", EOFError()])

        def _input():
            val = next(inputs)
            if isinstance(val, Exception):
                raise val
            return val

        with patch("builtins.input", side_effect=_input):
            svc._is_running = True
            try:
                svc._listen_loop()
            except StopIteration:
                pass

        mock_api.submit_qr_release.assert_called_once_with(
            "inkify_job_release:TOKEN999"
        )

    def test_unrecognised_input_does_not_call_api(self):
        svc, mock_api = _make_svc()
        inputs = iter(["random_barcode_12345", EOFError()])

        def _input():
            val = next(inputs)
            if isinstance(val, Exception):
                raise val
            return val

        with patch("builtins.input", side_effect=_input):
            svc._is_running = True
            try:
                svc._listen_loop()
            except StopIteration:
                pass

        mock_api.submit_qr_release.assert_not_called()

    def test_empty_input_ignored(self):
        svc, mock_api = _make_svc()
        inputs = iter(["", "   ", EOFError()])

        def _input():
            val = next(inputs)
            if isinstance(val, Exception):
                raise val
            return val

        with patch("builtins.input", side_effect=_input):
            svc._is_running = True
            try:
                svc._listen_loop()
            except StopIteration:
                pass

        mock_api.submit_qr_release.assert_not_called()

    def test_eof_error_exits_loop(self):
        svc, _ = _make_svc()
        with patch("builtins.input", side_effect=EOFError):
            svc._is_running = True
            svc._listen_loop()   # must exit cleanly, not hang

    def test_strips_whitespace_from_scanned_input(self):
        svc, mock_api = _make_svc()
        inputs = iter(["  inkify_job_release:TOK  \n", EOFError()])

        def _input():
            val = next(inputs)
            if isinstance(val, Exception):
                raise val
            return val

        with patch("builtins.input", side_effect=_input):
            svc._is_running = True
            try:
                svc._listen_loop()
            except StopIteration:
                pass

        mock_api.submit_qr_release.assert_called_once_with(
            "inkify_job_release:TOK"
        )
