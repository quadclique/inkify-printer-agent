"""
Tests for:
  LocalAgentDB
  JobRepository
  QueueRepository
  PrinterRepository
"""
import yaml
import pytest

from app.core import config as cfg_module
from app.core.local_agent_db import LocalAgentDB
from app.models.job_model import JobModel
from app.models.queue_model import QueueEventModel
from app.repositories.job_repo import JobRepository
from app.repositories.printer_repo import PrinterRepository
from app.repositories.queue_repo import QueueRepository


# LocalAgentDB
class TestLocalAgentDB:
    def test_initialize_schema_creates_jobs_table(self, initialized_db):
        with initialized_db.get_connection() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "jobs" in tables

    def test_initialize_schema_creates_queue_events_table(self, initialized_db):
        with initialized_db.get_connection() as conn:
            tables = {
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
        assert "queue_events" in tables

    def test_initialize_schema_idempotent(self, initialized_db):
        """Calling initialize_schema twice must not raise."""
        LocalAgentDB.initialize_schema()
        LocalAgentDB.initialize_schema()

    def test_get_connection_returns_row_factory(self, initialized_db):
        """Rows should be accessible by column name (dict-like)."""
        with initialized_db.get_connection() as conn:
            conn.execute(
                "INSERT INTO jobs (job_id, printer_id, status) VALUES (?,?,?)",
                ("j1", "p1", "pending"),
            )
            conn.commit()
            row = conn.execute(
                "SELECT * FROM jobs WHERE job_id='j1'"
            ).fetchone()
        assert row["job_id"] == "j1"
        assert row["status"] == "pending"

    def test_connection_closed_after_context(self, initialized_db):
        """Connection object should be closed after the with-block exits."""
        import sqlite3
        captured = []
        with initialized_db.get_connection() as conn:
            captured.append(conn)
        # Any further operation on a closed connection raises an error
        with pytest.raises(Exception):
            captured[0].execute("SELECT 1")

    def test_wal_mode_enabled(self, initialized_db):
        with initialized_db.get_connection() as conn:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
        assert mode == "wal"


# JobRepository
class TestJobRepository:
    def test_save_new_job(self, initialized_db):
        repo = JobRepository()
        job = JobModel(job_id="j1", printer_id="p1", status="pending")
        assert repo.save(job) is True

    def test_save_duplicate_is_ignored(self, initialized_db):
        """INSERT OR IGNORE — saving the same job_id twice should not raise."""
        repo = JobRepository()
        job = JobModel(job_id="j1", printer_id="p1", status="pending")
        assert repo.save(job) is True
        assert repo.save(job) is True  # second call → ignored, not error

    def test_get_job_returns_correct_data(self, initialized_db):
        repo = JobRepository()
        repo.save(JobModel(
            job_id="test_job_1",
            printer_id="Test_Printer",
            status="downloading",
            file_path="/tmp/test_job_1.pdf",
        ))
        fetched = repo.get_job("test_job_1")
        assert fetched is not None
        assert fetched.job_id == "test_job_1"
        assert fetched.printer_id == "Test_Printer"
        assert fetched.status == "downloading"
        assert fetched.file_path == "/tmp/test_job_1.pdf"

    def test_get_job_missing_returns_none(self, initialized_db):
        assert JobRepository().get_job("does-not-exist") is None

    def test_update_status(self, initialized_db):
        repo = JobRepository()
        repo.save(JobModel(job_id="j2", printer_id="p1", status="pending"))
        assert repo.update_status("j2", "printing") is True
        assert repo.get_job("j2").status == "printing"

    def test_update_status_all_states(self, initialized_db):
        repo = JobRepository()
        repo.save(JobModel(job_id="j3", printer_id="p1", status="pending"))
        for status in ("downloading", "printing", "completed", "failed"):
            assert repo.update_status("j3", status) is True
            assert repo.get_job("j3").status == status

    def test_update_status_nonexistent_job(self, initialized_db):
        """Updating a non-existent job should return True (0 rows affected but no error)."""
        assert JobRepository().update_status("ghost", "completed") is True

    def test_update_file_path(self, initialized_db):
        repo = JobRepository()
        repo.save(JobModel(job_id="j4", printer_id="p1", status="pending"))
        assert repo.update_file_path("j4", "/printing/j4.pdf") is True
        assert repo.get_job("j4").file_path == "/printing/j4.pdf"

    def test_get_interrupted_jobs_returns_correct_statuses(self, initialized_db):
        repo = JobRepository()
        repo.save(JobModel(job_id="ji1", printer_id="p1", status="downloading"))
        repo.save(JobModel(job_id="ji2", printer_id="p1", status="printing"))
        repo.save(JobModel(job_id="ji3", printer_id="p1", status="completed"))
        repo.save(JobModel(job_id="ji4", printer_id="p1", status="pending"))

        interrupted = repo.get_interrupted_jobs()
        interrupted_ids = {j.job_id for j in interrupted}
        assert "ji1" in interrupted_ids
        assert "ji2" in interrupted_ids
        assert "ji3" not in interrupted_ids
        assert "ji4" not in interrupted_ids

    def test_get_interrupted_jobs_empty_when_none(self, initialized_db):
        repo = JobRepository()
        repo.save(JobModel(job_id="j5", printer_id="p1", status="completed"))
        assert repo.get_interrupted_jobs() == []


# QueueRepository
class TestQueueRepository:
    def test_add_event_returns_true(self, initialized_db):
        repo = QueueRepository()
        event = QueueEventModel(
            job_id="j1", event_type="status_update", payload={"status": "completed"}
        )
        assert repo.add_event(event) is True

    def test_get_unsynced_events_returns_added_event(self, initialized_db):
        repo = QueueRepository()
        repo.add_event(QueueEventModel(
            job_id="j1", event_type="status_update", payload={"status": "failed"}
        ))
        events = repo.get_unsynced_events()
        assert len(events) == 1
        assert events[0].job_id == "j1"
        assert events[0].event_type == "status_update"
        assert events[0].synced is False

    def test_get_unsynced_preserves_payload(self, initialized_db):
        repo = QueueRepository()
        repo.add_event(QueueEventModel(
            job_id="j1", event_type="status_update",
            payload={"status": "completed", "details": "done"}
        ))
        events = repo.get_unsynced_events()
        assert events[0].payload["status"] == "completed"
        assert events[0].payload["details"] == "done"

    def test_mark_as_synced(self, initialized_db):
        repo = QueueRepository()
        repo.add_event(QueueEventModel(
            job_id="j1", event_type="status_update", payload={"status": "failed"}
        ))
        events = repo.get_unsynced_events()
        assert repo.mark_as_synced(events[0].event_id) is True
        assert repo.get_unsynced_events() == []

    def test_full_workflow(self, initialized_db):
        """Add → retrieve → mark synced → verify empty."""
        repo = QueueRepository()
        event = QueueEventModel(
            job_id="offline_job_1",
            event_type="status_update",
            payload={"status": "failed"},
        )
        assert repo.add_event(event) is True

        unsynced = repo.get_unsynced_events()
        assert len(unsynced) == 1
        saved = unsynced[0]
        assert saved.job_id == "offline_job_1"
        assert saved.synced is False
        assert saved.payload["status"] == "failed"

        assert repo.mark_as_synced(saved.event_id) is True
        assert repo.get_unsynced_events() == []

    def test_multiple_events_ordered_by_created_at(self, initialized_db):
        repo = QueueRepository()
        for i in range(3):
            repo.add_event(QueueEventModel(
                job_id=f"j{i}", event_type="status_update", payload={"i": i}
            ))
        events = repo.get_unsynced_events()
        assert len(events) == 3
        assert events[0].job_id == "j0"
        assert events[2].job_id == "j2"

    def test_only_unsynced_returned(self, initialized_db):
        """Synced events should not appear in get_unsynced_events."""
        repo = QueueRepository()
        repo.add_event(QueueEventModel(
            job_id="j1", event_type="status_update", payload={}
        ))
        repo.add_event(QueueEventModel(
            job_id="j2", event_type="status_update", payload={}
        ))
        events = repo.get_unsynced_events()
        repo.mark_as_synced(events[0].event_id)

        remaining = repo.get_unsynced_events()
        assert len(remaining) == 1
        assert remaining[0].job_id == "j2"


# PrinterRepository
class TestPrinterRepository:
    def test_upsert_and_get_best_connection(self):
        repo = PrinterRepository()
        repo.upsert_connection(
            signature="SIG001",
            transport="usb",
            device_uri="usb://HP/LaserJet?serial=SIG001",
            queue_name="HP_LaserJet",
            cloud_printer_id="cloud-uuid-1",
            display_name="HP LaserJet",
        )
        best = repo.get_best_connection("SIG001")
        assert best is not None
        assert best["transport"] == "usb"
        assert best["queue_name"] == "HP_LaserJet"
        assert best["device_uri"] == "usb://HP/LaserJet?serial=SIG001"

    def test_usb_takes_priority_over_network(self):
        repo = PrinterRepository()
        repo.upsert_connection("SIG002", "network", "ipp://192.168.1.10", "HP_Net")
        repo.upsert_connection("SIG002", "usb", "usb://HP?serial=SIG002", "HP_USB")
        assert repo.get_best_connection("SIG002")["transport"] == "usb"

    def test_network_returned_when_no_usb(self):
        repo = PrinterRepository()
        repo.upsert_connection("SIG003", "network", "ipp://192.168.1.11", "HP_Net")
        best = repo.get_best_connection("SIG003")
        assert best["transport"] == "network"

    def test_get_best_connection_unknown_signature_returns_none(self):
        repo = PrinterRepository()
        assert repo.get_best_connection("NONEXISTENT") is None

    def test_get_cloud_id_by_signature(self):
        repo = PrinterRepository()
        repo.upsert_connection(
            "SIG004", "usb", "usb://x", "Q",
            cloud_printer_id="cloud-id-4",
        )
        assert repo.get_cloud_id_by_signature("SIG004") == "cloud-id-4"

    def test_get_cloud_id_missing_signature_returns_none(self):
        repo = PrinterRepository()
        assert repo.get_cloud_id_by_signature("MISSING") is None

    def test_upsert_updates_existing_connection(self):
        """Upserting the same signature+transport should update the URI."""
        repo = PrinterRepository()
        repo.upsert_connection("SIG005", "usb", "usb://old", "OldQ")
        repo.upsert_connection("SIG005", "usb", "usb://new", "NewQ")
        best = repo.get_best_connection("SIG005")
        assert best["device_uri"] == "usb://new"
        assert best["queue_name"] == "NewQ"

    def test_upsert_adds_second_transport_without_removing_first(self):
        """Adding WiFi to a USB-known printer should keep both connections."""
        repo = PrinterRepository()
        repo.upsert_connection("SIG006", "usb", "usb://hp", "HP_USB")
        repo.upsert_connection("SIG006", "network", "ipp://192.168.1.1", "HP_WiFi")
        m = repo.get_printer_map()
        conns = m["SIG006"]["connections"]
        assert "usb" in conns
        assert "network" in conns

    def test_save_and_reload_printer_map(self):
        repo = PrinterRepository()
        repo.upsert_connection(
            "SIG007", "usb", "usb://persist", "PersistQ",
            cloud_printer_id="cloud-persist"
        )
        # Re-instantiate to force a fresh disk read
        repo2 = PrinterRepository()
        m = repo2.get_printer_map()
        assert "SIG007" in m
        assert m["SIG007"]["cloud_printer_id"] == "cloud-persist"

    def test_get_printer_map_empty_when_no_file(self):
        repo = PrinterRepository()
        # isolate_config ensures PRINTERS_CONFIG_FILE points to a non-existent file
        assert repo.get_printer_map() == {}

    def test_legacy_migration_flat_schema(self):
        """Old flat-schema entries should be silently upgraded to nested schema."""
        pf = cfg_module.config.PRINTERS_CONFIG_FILE
        legacy = {
            "printer_map": {
                "OLD_SIG": {
                    "cloud_printer_id": "uuid-old",
                    "local_name": "OldPrinter",
                    "connection_type": "usb",
                    "device_uri": "usb://old",
                }
            }
        }
        pf.write_text(yaml.safe_dump(legacy))

        repo = PrinterRepository()
        m = repo.get_printer_map()
        assert "OLD_SIG" in m
        assert "connections" in m["OLD_SIG"]
        assert m["OLD_SIG"]["cloud_printer_id"] == "uuid-old"
        # Connection should be accessible via get_best_connection too
        best = repo.get_best_connection("OLD_SIG")
        assert best is not None
        assert best["transport"] == "usb"

    def test_legacy_migration_preserves_new_schema(self):
        """New-schema entries must pass through migration unchanged."""
        pf = cfg_module.config.PRINTERS_CONFIG_FILE
        new_schema = {
            "printer_map": {
                "NEW_SIG": {
                    "cloud_printer_id": "uuid-new",
                    "display_name": "NewPrinter",
                    "connections": {
                        "usb": {
                            "device_uri": "usb://new",
                            "queue_name": "NewQ",
                            "last_seen": None,
                        }
                    },
                }
            }
        }
        pf.write_text(yaml.safe_dump(new_schema))

        repo = PrinterRepository()
        m = repo.get_printer_map()
        assert "NEW_SIG" in m
        assert m["NEW_SIG"]["display_name"] == "NewPrinter"
        assert "usb" in m["NEW_SIG"]["connections"]
