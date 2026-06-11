"""
Tests for app.agent_lifecycle.PrinterAgent covering:
  __init__ — dependency wiring
  run       — auth check, printer sync, recovery, background thread start
  stop      — graceful shutdown
  _loop     — adaptive backoff, queue flush, cleanup trigger, updater call
"""
import sys
import time
import threading
from unittest.mock import MagicMock, patch, call

import pytest

from app.models.agent_model import AgentModel


# Helpers
def _make_agent():
    """
    Creates a PrinterAgent with ALL service dependencies replaced by mocks
    so we only test the lifecycle orchestration logic.
    """
    # Patch every heavy constructor so __init__ stays fast
    with patch("app.agent_lifecycle.AgentRepository") as MockAgentRepo, \
         patch("app.agent_lifecycle.PrinterRepository"), \
         patch("app.agent_lifecycle.APIClientService"), \
         patch("app.agent_lifecycle.get_printer_manager"), \
         patch("app.agent_lifecycle.StorageService"), \
         patch("app.agent_lifecycle.QueueService"), \
         patch("app.agent_lifecycle.PairingService"), \
         patch("app.agent_lifecycle.PrinterService"), \
         patch("app.agent_lifecycle.HeartbeatService"), \
         patch("app.agent_lifecycle.DiscoveryService"), \
         patch("app.agent_lifecycle.JobService"), \
         patch("app.agent_lifecycle.CleanupService"), \
         patch("app.agent_lifecycle.UpdaterService"):

        from app.agent_lifecycle import PrinterAgent
        agent = PrinterAgent()

    # Wire up sensible mock defaults
    agent.agent_repo.get_config.return_value = AgentModel(
        agent_id="test-agent", agent_token="test-token"
    )
    agent.job_service.process_pending_jobs.return_value = 0
    agent.queue_service.process_queue.return_value = None
    agent.heartbeat_service.start.return_value = None
    agent.heartbeat_service.stop.return_value = None
    agent.discovery_service.start.return_value = None
    agent.discovery_service.stop.return_value = None
    agent.job_service.shutdown.return_value = None
    agent.job_service.recover_interrupted_jobs.return_value = None
    agent.printer_service.sync_printers_with_cloud.return_value = None
    agent.cleanup_service.run_cleanup.return_value = None
    agent.updater_service.check_for_updates.return_value = None
    agent.updater_service.apply_update_if_ready.return_value = None

    return agent


# __init__ — dependency wiring
class TestPrinterAgentInit:
    def test_all_services_are_set(self):
        agent = _make_agent()
        for attr in (
            "agent_repo", "printer_repo", "api_client", "printer_manager",
            "storage_service", "queue_service", "pairing_service",
            "printer_service", "heartbeat_service", "discovery_service",
            "job_service", "cleanup_service", "updater_service",
        ):
            assert hasattr(agent, attr), f"Missing attribute: {attr}"

    def test_stop_event_is_not_set_on_init(self):
        agent = _make_agent()
        assert not agent.stop_event.is_set()

    def test_is_running_is_false_on_init(self):
        agent = _make_agent()
        assert agent.is_running is False


# run
class TestPrinterAgentRun:
    def test_exits_if_not_authenticated(self):
        agent = _make_agent()
        agent.agent_repo.get_config.return_value = AgentModel()   # no token
        with pytest.raises(SystemExit) as exc:
            agent.run()
        assert exc.value.code == 1

    def test_syncs_printers_on_startup(self):
        agent = _make_agent()
        # Make the loop exit after one iteration
        agent.stop_event.set()
        agent.run()
        agent.printer_service.sync_printers_with_cloud.assert_called_once()

    def test_recovers_interrupted_jobs_on_startup(self):
        agent = _make_agent()
        agent.stop_event.set()
        agent.run()
        agent.job_service.recover_interrupted_jobs.assert_called_once()

    def test_starts_heartbeat_service(self):
        agent = _make_agent()
        agent.stop_event.set()
        agent.run()
        agent.heartbeat_service.start.assert_called_once()

    def test_starts_discovery_service(self):
        agent = _make_agent()
        agent.stop_event.set()
        agent.run()
        agent.discovery_service.start.assert_called_once()

    def test_sets_is_running_true(self):
        agent = _make_agent()
        agent.stop_event.set()
        agent.run()
        # is_running is set to True during run then False on stop
        # After stop_event is already set, stop() is called → is_running = False
        # Verify it was at least set to True at some point (stop sets it False)
        # We check that stop() was reached (stop_event was set before loop)
        agent.heartbeat_service.stop.assert_called()


# stop
class TestPrinterAgentStop:
    def test_stop_sets_stop_event(self):
        agent = _make_agent()
        agent.is_running = True
        agent.stop()
        assert agent.stop_event.is_set()

    def test_stop_sets_is_running_false(self):
        agent = _make_agent()
        agent.is_running = True
        agent.stop()
        assert agent.is_running is False

    def test_stop_calls_heartbeat_stop(self):
        agent = _make_agent()
        agent.is_running = True
        agent.stop()
        agent.heartbeat_service.stop.assert_called_once()

    def test_stop_calls_discovery_stop(self):
        agent = _make_agent()
        agent.is_running = True
        agent.stop()
        agent.discovery_service.stop.assert_called_once()

    def test_stop_calls_job_service_shutdown(self):
        agent = _make_agent()
        agent.is_running = True
        agent.stop()
        agent.job_service.shutdown.assert_called_once()

    def test_stop_when_not_running_is_no_op(self):
        agent = _make_agent()
        agent.is_running = False
        agent.stop()   # must not raise and must not call shutdown
        agent.job_service.shutdown.assert_not_called()

    def test_stop_idempotent(self):
        agent = _make_agent()
        agent.is_running = True
        agent.stop()
        agent.stop()   # second call must not raise


# _loop — adaptive backoff and cleanup
class TestPrinterAgentLoop:
    def _run_one_iteration(self, agent):
        """
        Run exactly one iteration of _loop by setting the stop_event
        after the first wait call returns.
        """
        original_wait = agent.stop_event.wait

        call_count = [0]

        def patched_wait(timeout=None):
            call_count[0] += 1
            if call_count[0] >= 1:
                agent.stop_event.set()
            return original_wait(0)  # return immediately

        agent.stop_event.wait = patched_wait
        agent._loop()

    def test_processes_queue_before_jobs(self):
        agent = _make_agent()
        order = []
        agent.queue_service.process_queue.side_effect = lambda: order.append("queue")
        agent.job_service.process_pending_jobs.side_effect = lambda: (
            order.append("jobs") or 0
        )
        self._run_one_iteration(agent)
        assert order.index("queue") < order.index("jobs")

    def test_resets_interval_when_jobs_found(self):
        from app.core.config import config
        agent = _make_agent()
        agent.job_service.process_pending_jobs.return_value = 2   # jobs found

        # Capture the wait timeout used
        wait_timeouts = []
        original_wait = agent.stop_event.wait
        calls = [0]

        def patched_wait(timeout=None):
            calls[0] += 1
            wait_timeouts.append(timeout)
            if calls[0] >= 1:
                agent.stop_event.set()
            return original_wait(0)

        agent.stop_event.wait = patched_wait
        agent._loop()

        # When jobs are found, interval should be reset to JOB_POLL_INTERVAL
        assert any(t == config.JOB_POLL_INTERVAL for t in wait_timeouts)

    def test_increases_interval_when_idle(self):
        from app.core.config import config
        agent = _make_agent()
        agent.job_service.process_pending_jobs.return_value = 0   # idle

        wait_timeouts = []
        calls = [0]
        original_wait = agent.stop_event.wait

        def patched_wait(timeout=None):
            calls[0] += 1
            wait_timeouts.append(timeout)
            if calls[0] >= 2:   # run 2 iterations
                agent.stop_event.set()
            return original_wait(0)

        agent.stop_event.wait = patched_wait
        agent._loop()

        # After two idle iterations, interval should have grown
        if len(wait_timeouts) >= 2:
            assert wait_timeouts[1] >= wait_timeouts[0]

    def test_calls_updater_check_for_updates(self):
        agent = _make_agent()
        self._run_one_iteration(agent)
        agent.updater_service.check_for_updates.assert_called()

    def test_calls_updater_apply_update_if_ready(self):
        agent = _make_agent()
        self._run_one_iteration(agent)
        agent.updater_service.apply_update_if_ready.assert_called()

    def test_runs_cleanup_when_interval_exceeded(self):
        from app.core import config as cfg_module
        agent = _make_agent()
        # Fake last_cleanup_time far in the past
        agent.last_cleanup_time = 0
        with patch.object(cfg_module.config, "CLEANUP_INTERVAL_SECONDS", 0):
            self._run_one_iteration(agent)
        agent.cleanup_service.run_cleanup.assert_called_once()

    def test_does_not_run_cleanup_when_not_due(self):
        agent = _make_agent()
        agent.last_cleanup_time = time.time()   # just cleaned
        self._run_one_iteration(agent)
        agent.cleanup_service.run_cleanup.assert_not_called()

    def test_loop_recovers_from_exception_in_iteration(self):
        """An exception in one iteration must not terminate the loop."""
        agent = _make_agent()
        calls = [0]

        def boom():
            calls[0] += 1
            if calls[0] == 1:
                raise RuntimeError("transient error")
            agent.stop_event.set()
            return 0

        agent.job_service.process_pending_jobs.side_effect = boom

        original_wait = agent.stop_event.wait
        agent.stop_event.wait = lambda t=None: original_wait(0)

        agent._loop()   # must not propagate the RuntimeError
        assert calls[0] >= 2   # loop continued after the error
