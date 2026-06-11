"""
Tests for all data models: JobModel, AgentModel, PrinterModel, QueueEventModel.
"""
import json

import pytest

from app.models.agent_model import AgentModel
from app.models.job_model import JobModel
from app.models.printer_model import PrinterModel
from app.models.queue_model import QueueEventModel


# JobModel
class TestJobModel:
    def test_from_api_response_full_payload(self):
        job = JobModel.from_api_response({
            "id": "job_999",
            "printer_id": "Front_Desk_Laser",
            "status": "pending",
            "file_url": "https://inkify.com/download/job_999.pdf",
            "sha256_hash": "abcdef123456",
            "copies": 2,
            "is_color": True,
            "document_id": "doc_777",
        })
        assert job.job_id == "job_999"
        assert job.printer_id == "Front_Desk_Laser"
        assert job.status == "pending"
        assert job.file_url == "https://inkify.com/download/job_999.pdf"
        assert job.expected_hash == "abcdef123456"
        assert job.copies == 2
        assert job.is_color is True
        assert job.document_id == "doc_777"

    def test_is_valid_with_required_fields(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1"})
        assert job.is_valid() is True

    def test_is_valid_missing_job_id(self):
        job = JobModel.from_api_response({"printer_id": "p1"})
        assert job.is_valid() is False

    def test_is_valid_missing_printer_id(self):
        job = JobModel.from_api_response({"id": "j1"})
        assert job.is_valid() is False

    def test_is_valid_empty_payload(self):
        assert JobModel.from_api_response({}).is_valid() is False

    def test_default_copies_is_one(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1"})
        assert job.copies == 1

    def test_copies_zero_clamped_to_one(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1", "copies": 0})
        assert job.copies == 1

    def test_copies_negative_clamped_to_one(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1", "copies": -5})
        assert job.copies == 1

    def test_copies_valid_positive(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1", "copies": 5})
        assert job.copies == 5

    def test_default_is_color_false(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1"})
        assert job.is_color is False

    def test_is_color_true(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1", "is_color": True})
        assert job.is_color is True

    def test_default_status(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1"})
        assert job.status == "pending"

    def test_missing_file_url_is_none(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1"})
        assert job.file_url is None

    def test_missing_expected_hash_is_none(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1"})
        assert job.expected_hash is None

    def test_missing_document_id_is_none(self):
        job = JobModel.from_api_response({"id": "j1", "printer_id": "p1"})
        assert job.document_id is None


# AgentModel
class TestAgentModel:
    def test_round_trip_serialization(self):
        m = AgentModel(agent_id="a1", agent_token="tok", location="office")
        m2 = AgentModel.from_dict(m.to_dict())
        assert m2.agent_id == "a1"
        assert m2.agent_token == "tok"
        assert m2.location == "office"

    def test_default_location(self):
        m = AgentModel()
        assert m.location == "unassigned"

    def test_default_agent_id_empty(self):
        m = AgentModel()
        assert m.agent_id == ""

    def test_default_agent_token_empty(self):
        m = AgentModel()
        assert m.agent_token == ""

    def test_features_enabled_defaults_empty(self):
        m = AgentModel()
        assert m.features_enabled == {}

    def test_from_dict_missing_keys_use_defaults(self):
        m = AgentModel.from_dict({})
        assert m.agent_id == ""
        assert m.agent_token == ""
        assert m.location == "unassigned"

    def test_from_dict_with_features(self):
        m = AgentModel.from_dict({
            "agent_id": "x",
            "agent_token": "y",
            "location": "lobby",
            "features": {"qr_scan": True, "auto_update": False},
        })
        assert m.features_enabled["qr_scan"] is True
        assert m.features_enabled["auto_update"] is False

    def test_to_dict_contains_expected_keys(self):
        m = AgentModel(agent_id="id1", agent_token="t1", location="floor2")
        d = m.to_dict()
        assert "agent_id" in d
        assert "agent_token" in d
        assert "location" in d
        assert "features" in d

    def test_to_dict_values(self):
        m = AgentModel(agent_id="id1", agent_token="t1", location="floor2")
        d = m.to_dict()
        assert d["agent_id"] == "id1"
        assert d["agent_token"] == "t1"
        assert d["location"] == "floor2"


# PrinterModel
class TestPrinterModel:
    def test_is_ready_when_idle(self):
        assert PrinterModel(id="p1", name="HP", status="idle").is_ready is True

    def test_is_ready_when_printing(self):
        assert PrinterModel(id="p1", name="HP", status="printing").is_ready is True

    def test_not_ready_when_offline(self):
        assert PrinterModel(id="p2", name="Canon", status="offline").is_ready is False

    def test_not_ready_unknown_status(self):
        assert PrinterModel(id="p3", name="Zebra", status="error").is_ready is False

    def test_from_dict_full(self):
        p = PrinterModel.from_dict({
            "id": "hp1",
            "name": "HP LaserJet",
            "status": "idle",
            "raw_status": "is idle",
            "connection_type": "usb",
            "device_uri": "usb://HP?serial=123",
            "hardware_signature": "HWSIG123",
            "supports_color": True,
            "supports_duplex": True,
        })
        assert p.id == "hp1"
        assert p.name == "HP LaserJet"
        assert p.connection_type == "usb"
        assert p.hardware_signature == "HWSIG123"
        assert p.supports_color is True
        assert p.supports_duplex is True

    def test_from_dict_defaults(self):
        p = PrinterModel.from_dict({"id": "p1", "name": "X", "status": "idle"})
        assert p.connection_type == "unknown"
        assert p.device_uri == ""
        assert p.hardware_signature == ""
        assert p.supports_color is False
        assert p.supports_duplex is False


# QueueEventModel
class TestQueueEventModel:
    def test_get_payload_json_returns_string(self):
        event = QueueEventModel(
            job_id="job_123",
            event_type="status_update",
            payload={"status": "completed", "details": "Printed perfectly"},
        )
        result = event.get_payload_json()
        assert isinstance(result, str)

    def test_get_payload_json_valid_json(self):
        payload = {"status": "failed", "details": "Paper jam"}
        event = QueueEventModel(job_id="j1", event_type="status_update", payload=payload)
        parsed = json.loads(event.get_payload_json())
        assert parsed["status"] == "failed"
        assert parsed["details"] == "Paper jam"

    def test_get_payload_json_empty_payload(self):
        event = QueueEventModel(job_id="j1", event_type="status_update", payload={})
        assert json.loads(event.get_payload_json()) == {}

    def test_get_payload_json_nested_payload(self):
        payload = {"status": "completed", "meta": {"pages": 3, "color": True}}
        event = QueueEventModel(job_id="j1", event_type="status_update", payload=payload)
        parsed = json.loads(event.get_payload_json())
        assert parsed["meta"]["pages"] == 3

    def test_default_synced_is_false(self):
        event = QueueEventModel(job_id="j1", event_type="status_update", payload={})
        assert event.synced is False

    def test_default_event_id_is_zero(self):
        event = QueueEventModel(job_id="j1", event_type="status_update", payload={})
        assert event.event_id == 0

    def test_default_created_at_is_none(self):
        event = QueueEventModel(job_id="j1", event_type="status_update", payload={})
        assert event.created_at is None
