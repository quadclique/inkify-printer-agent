import pytest
import json
from datetime import datetime
from pathlib import Path

# Adjust imports based on your exact app structure
from app.core import config
from app.core.local_agent_db import LocalAgentDB
from app.models.job_model import JobModel
from app.models.queue_model import QueueEventModel
from app.repositories.job_repo import JobRepository
from app.repositories.queue_repo import QueueRepository

# ==========================================
# FIXTURES (Setup & Teardown)
# ==========================================


@pytest.fixture(autouse=True)
def isolated_test_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """
    This fixture automatically runs before EVERY test.
    It reroutes the database file to a temporary folder and builds the schema.
    This ensures tests never touch your real production database.
    """
    # Create a temporary database file
    temp_db_file = tmp_path / "test_agent.db"

    # Force the app to use this temporary file
    monkeypatch.setattr(config, "DB_FILE", temp_db_file)

    # Initialize the tables in this fresh temporary database
    LocalAgentDB.initialize_schema()

    # Yield hands control over to the test.
    # When the test finishes, the temp_db_file is automatically deleted.
    yield


# ==========================================
# 1. MODEL TESTS
# ==========================================


def test_job_model_from_api_response():
    """Tests if raw cloud JSON correctly transforms into a strict Python object."""
    mock_api_data = {
        "id": "job_999",
        "printer_name": "Front_Desk_Laser",
        "status": "pending",
        "file_url": "https://inkify.com/download/job_999.pdf",
        "sha256_hash": "abcdef123456",
    }

    job = JobModel.from_api_response(mock_api_data)

    assert job.job_id == "job_999"
    assert job.printer_id == "Front_Desk_Laser"
    assert job.status == "pending"
    assert job.file_url == "https://inkify.com/download/job_999.pdf"
    assert job.expected_hash == "abcdef123456"


def test_queue_model_payload_serialization():
    """Tests if the queue model can safely pack a dictionary into a JSON string."""
    event = QueueEventModel(
        job_id="job_123",
        event_type="status_update",
        payload={"status": "completed", "details": "Printed perfectly"},
    )

    json_string = event.get_payload_json()

    # Verify it's a valid string
    assert isinstance(json_string, str)

    # Verify it unpacks correctly
    unpacked_dict = json.loads(json_string)
    assert unpacked_dict["status"] == "completed"


# ==========================================
# 2. REPOSITORY TESTS
# ==========================================


def test_job_repository_save_and_retrieve():
    """Tests writing a job to SQLite and reading it back."""
    repo = JobRepository()

    new_job = JobModel(
        job_id="test_job_1",
        printer_id="Test_Printer",
        status="downloading",
        file_path="/tmp/test_job_1.pdf",
    )

    # 1. Save it
    success = repo.save(new_job)
    assert success is True

    # 2. Retrieve it
    fetched_job = repo.get_job("test_job_1")
    assert fetched_job is not None
    assert fetched_job.job_id == "test_job_1"
    assert fetched_job.printer_id == "Test_Printer"
    assert fetched_job.status == "downloading"


def test_job_repository_update_status():
    """Tests changing a job's status in the database."""
    repo = JobRepository()

    # Setup initial job
    repo.save(JobModel(job_id="job_to_update", printer_id="P1", status="ready"))

    # Update status to printing
    update_success = repo.update_status("job_to_update", "printing")
    assert update_success is True

    # Verify the change
    updated_job = repo.get_job("job_to_update")
    assert updated_job.status == "printing"


def test_queue_repository_workflow():
    """Tests the full lifecycle of an offline queue event."""
    repo = QueueRepository()

    event = QueueEventModel(
        job_id="offline_job_1", event_type="status_update", payload={"status": "failed"}
    )

    # 1. Add event to queue
    add_success = repo.add_event(event)
    assert add_success is True

    # 2. Verify it shows up in the unsynced list
    unsynced_events = repo.get_unsynced_events()
    assert len(unsynced_events) == 1

    saved_event = unsynced_events[0]
    assert saved_event.job_id == "offline_job_1"
    assert saved_event.synced is False
    assert (
        saved_event.payload["status"] == "failed"
    )  # Should be auto-unpacked into a dict

    # 3. Mark it as synced
    sync_success = repo.mark_as_synced(saved_event.event_id)
    assert sync_success is True

    # 4. Verify the unsynced list is now empty
    remaining_events = repo.get_unsynced_events()
    assert len(remaining_events) == 0
