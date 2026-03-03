import pytest
from unittest.mock import patch, MagicMock
from app.services.cups_service import CUPSManager

@patch("app.services.cups_manage_servicer.subprocess.run")
def test_get_printers_success(mock_run):
    """Tests if the CUPS manager correctly parses `lpstat` output."""
    mock_run.return_value = MagicMock(
        stdout="printer HP_Laser is idle. enabled since Jan 1\nprinter Zebra is disabled",
        returncode=0
    )
    
    manager = CUPSManager()
    printers = manager.get_printers()
    
    assert len(printers) == 2
    assert printers[0]["name"] == "HP_Laser"
    assert printers[0]["status"] == "idle"
    assert printers[1]["name"] == "Zebra"
    assert printers[1]["status"] == "offline"