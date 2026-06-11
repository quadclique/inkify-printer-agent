"""
Shared pytest fixtures.
"""
import pytest
from pathlib import Path
from unittest.mock import MagicMock


@pytest.fixture(autouse=True)
def isolate_config(tmp_path, monkeypatch):
    """
    Patches all config paths to point to a temporary directory for every test.
    This prevents tests from reading or writing real runtime state.
    """
    from app.core import config as cfg_module
    c = cfg_module.config

    dirs = [
        "RUNTIME_DIR", "LOG_DIR", "CONFIG_DIR",
        "QUEUE_DIR", "JOB_DIR", "DB_DIR", "LOCK_DIR",
        "JOB_DOWNLOAD_DIR", "JOB_READY_DIR", "JOB_PRINTING_DIR",
        "JOB_COMPLETED_DIR", "JOB_FAILED_DIR",
        "QUEUE_PENDING_DIR", "QUEUE_PROCESSING_DIR",
        "QUEUE_COMPLETED_DIR", "QUEUE_FAILED_DIR",
    ]
    files = [
        "DB_FILE", "LOCK_FILE", "VERSION_FILE",
        "AGENT_CONFIG_FILE", "PRINTERS_CONFIG_FILE",
        "AGENT_LOG_FILE", "ERROR_LOG_FILE", "AUDIT_LOG_FILE",
    ]

    for attr in dirs:
        new_path = tmp_path / attr.lower()
        new_path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(c, attr, new_path)

    for attr in files:
        monkeypatch.setattr(c, attr, tmp_path / f"{attr.lower()}.file")


@pytest.fixture()
def mock_api_client():
    """A fully-mocked APIClientService."""
    client = MagicMock()
    client.check_in.return_value = True
    client.pull_next_job.return_value = {"status": "idle"}
    client.update_job_status.return_value = True
    client.sync_printers.return_value = {"synced_printers": []}
    client.download_job_file.return_value = True
    client.get_job_details.return_value = None
    return client


@pytest.fixture()
def mock_printer_manager():
    """A mocked BasePrinterManager."""
    mgr = MagicMock()
    mgr.get_printers.return_value = [
        {
            "id": "TestPrinter",
            "name": "TestPrinter",
            "status": "idle",
            "raw_status": "is idle",
            "connection_type": "usb",
            "device_uri": "usb://Test/Printer?serial=TEST001",
            "hardware_signature": "TEST001",
            "supports_color": True,
            "supports_duplex": False,
        }
    ]
    mgr.print_file_async.return_value = "OS-JOB-1"
    mgr.get_printer_capabilities.return_value = {
        "supports_color": True,
        "supports_duplex": False,
    }
    mgr.clear_queue.return_value = True
    return mgr


@pytest.fixture()
def mock_storage_service():
    """A mocked StorageService."""
    svc = MagicMock()
    svc.verify_download.return_value = True
    svc.transition_job_file.return_value = Path("/tmp/printing/job.pdf")
    svc.transition_queue_file.return_value = Path("/tmp/completed/event.json")
    svc.cleanup_failed_download.return_value = None
    return svc


@pytest.fixture()
def initialized_db(tmp_path, monkeypatch):
    """Provides an initialized in-memory-style SQLite DB for repository tests."""
    from app.core import config as cfg_module
    monkeypatch.setattr(cfg_module.config, "DB_FILE", tmp_path / "test.db")
    from app.core.local_agent_db import LocalAgentDB
    LocalAgentDB.initialize_schema()
    return LocalAgentDB
