import pytest
from pathlib import Path
from app.services.storage_service import StorageService
from app.utils import file_utils

def test_transition_job_file(tmp_path: Path, monkeypatch):
    """Tests if a file correctly moves from 'download' to 'ready' folders."""
    # Setup temporary mock directories
    download_dir = tmp_path / "download"
    ready_dir = tmp_path / "ready"
    download_dir.mkdir()
    ready_dir.mkdir()
    
    # Create a dummy file
    dummy_file = download_dir / "test_doc.pdf"
    dummy_file.write_text("dummy PDF content")
    
    storage = StorageService()
    # Override the service's internal dictionary with our tmp paths
    storage.state_dirs["download"] = download_dir
    storage.state_dirs["ready"] = ready_dir
    
    # Perform transition
    new_path = storage.transition_job_file("test_doc.pdf", "download", "ready")
    
    assert new_path is not None
    assert new_path.exists()
    assert new_path.parent.name == "ready"
    assert not dummy_file.exists() # Should be gone from download dir