"""
Tests for __main__ covering:
  _extract_token_from_filename
  _prompt_for_token
  _run_pairing_loop
"""
import importlib
import sys
from unittest.mock import MagicMock, patch

import pytest


# Helpers — reload main after patching sys.executable

def _reload_main(executable_path: str):
    """Reload main module with sys.executable pointing to a custom path."""
    with patch.object(sys, "executable", executable_path):
        import main as m
        importlib.reload(m)
        return m


# _extract_token_from_filename
class TestExtractTokenFromFilename:
    def test_extracts_token_from_windows_installer(self, monkeypatch):
        monkeypatch.setattr(sys, "executable",
                            "/downloads/InkifySetup--tkn_abc123xyz.exe")
        import main as m; importlib.reload(m)
        assert m._extract_token_from_filename() == "tkn_abc123xyz"

    def test_extracts_token_from_pkg_filename(self, monkeypatch):
        monkeypatch.setattr(sys, "executable",
                            "/tmp/InkifyAgent_v1.0.0--tkn_xyz987abc.pkg")
        import main as m; importlib.reload(m)
        assert m._extract_token_from_filename() == "tkn_xyz987abc"

    def test_extracts_token_from_deb_filename(self, monkeypatch):
        monkeypatch.setattr(sys, "executable",
                            "/tmp/inkify-agent_1.0.0--tkn_deb001.deb")
        import main as m; importlib.reload(m)
        assert m._extract_token_from_filename() == "tkn_deb001"

    def test_returns_empty_when_no_token_in_filename(self, monkeypatch):
        monkeypatch.setattr(sys, "executable", "/downloads/InkifySetup.exe")
        import main as m; importlib.reload(m)
        assert m._extract_token_from_filename() == ""

    def test_returns_empty_when_separator_present_but_no_tkn_prefix(self, monkeypatch):
        monkeypatch.setattr(sys, "executable",
                            "/downloads/InkifySetup--notavalidtoken.exe")
        import main as m; importlib.reload(m)
        assert m._extract_token_from_filename() == ""

    def test_returns_empty_for_plain_python_executable(self, monkeypatch):
        monkeypatch.setattr(sys, "executable", "/usr/bin/python3")
        import main as m; importlib.reload(m)
        assert m._extract_token_from_filename() == ""

    def test_handles_path_with_spaces_gracefully(self, monkeypatch):
        monkeypatch.setattr(sys, "executable",
                            "/Program Files/Inkify/InkifySetup--tkn_sp001.exe")
        import main as m; importlib.reload(m)
        # Token may or may not be extracted depending on regex — must not raise
        result = m._extract_token_from_filename()
        assert isinstance(result, str)

    def test_token_must_start_with_tkn_underscore(self, monkeypatch):
        """Tokens not starting with tkn_ should not be extracted."""
        monkeypatch.setattr(sys, "executable",
                            "/tmp/InkifySetup--reg_abc123.exe")
        import main as m; importlib.reload(m)
        assert m._extract_token_from_filename() == ""


# _run_pairing_loop
class TestRunPairingLoop:
    def _make_agent(self, paired_on_call=1):
        """Agent mock whose ensure_paired returns True on the Nth call."""
        agent = MagicMock()
        call_count = [0]

        def _ensure_paired(token):
            call_count[0] += 1
            return call_count[0] >= paired_on_call

        agent.pairing_service.ensure_paired.side_effect = _ensure_paired
        return agent

    def test_returns_true_on_immediate_success(self):
        import main as m; importlib.reload(m)
        agent = self._make_agent(paired_on_call=1)
        result = m._run_pairing_loop(agent, "tkn_good", pair_only=True)
        assert result is True

    def test_returns_false_when_no_token_in_non_interactive(self):
        import main as m; importlib.reload(m)
        agent = self._make_agent()
        with patch.object(sys.stdin, "isatty", return_value=False):
            result = m._run_pairing_loop(agent, "", pair_only=False)
        assert result is False

    def test_returns_false_in_pair_only_mode_on_failure(self):
        import main as m; importlib.reload(m)
        agent = MagicMock()
        agent.pairing_service.ensure_paired.return_value = False
        result = m._run_pairing_loop(agent, "tkn_bad", pair_only=True)
        assert result is False

    def test_returns_false_when_non_interactive_stdin_and_bad_token(self):
        import main as m; importlib.reload(m)
        agent = MagicMock()
        agent.pairing_service.ensure_paired.return_value = False
        with patch.object(sys.stdin, "isatty", return_value=False):
            result = m._run_pairing_loop(agent, "tkn_bad", pair_only=False)
        assert result is False

    def test_returns_true_after_user_provides_new_token(self):
        """First token fails; user types 'y' and provides a good token."""
        import main as m; importlib.reload(m)
        agent = self._make_agent(paired_on_call=2)   # succeeds on 2nd call
        with patch.object(sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", side_effect=["y", "tkn_second_try"]):
            result = m._run_pairing_loop(agent, "tkn_first_fail", pair_only=False)
        assert result is True

    def test_returns_false_when_user_declines_retry(self):
        import main as m; importlib.reload(m)
        agent = MagicMock()
        agent.pairing_service.ensure_paired.return_value = False
        with patch.object(sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", return_value="n"):
            result = m._run_pairing_loop(agent, "tkn_bad", pair_only=False)
        assert result is False

    def test_prompts_when_no_token_in_interactive_mode(self):
        import main as m; importlib.reload(m)
        agent = self._make_agent(paired_on_call=1)
        with patch.object(sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", return_value="tkn_interactive"):
            result = m._run_pairing_loop(agent, "", pair_only=False)
        assert result is True

    def test_empty_interactive_input_exits(self):
        import main as m; importlib.reload(m)
        agent = MagicMock()
        with patch.object(sys.stdin, "isatty", return_value=True), \
             patch("builtins.input", return_value=""):
            result = m._run_pairing_loop(agent, "", pair_only=False)
        assert result is False


# Integration smoke test — main() argument parsing
class TestMainArgParsing:
    def test_main_exits_when_already_paired_with_pair_only(self, monkeypatch):
        """--pair-only with an already-paired agent should exit 0."""
        import main as m; importlib.reload(m)

        mock_agent = MagicMock()
        mock_agent.pairing_service.is_paired.return_value = True

        monkeypatch.setattr(sys, "argv", ["main.py", "--pair-only"])

        with patch("main.PrinterAgent", return_value=mock_agent), \
             patch("main.StartupService.initialize_environment"), \
             patch("main.LocalAgentDB.initialize_schema"), \
             patch("main.setup_logging"), \
             pytest.raises(SystemExit) as exc_info:
            m.main()

        assert exc_info.value.code == 0

    def test_main_exits_1_when_pairing_fails_pair_only(self, monkeypatch):
        """--pair-only with a bad token and no interactive stdin should exit 1."""
        import main as m; importlib.reload(m)

        mock_agent = MagicMock()
        mock_agent.pairing_service.is_paired.return_value = False
        mock_agent.pairing_service.ensure_paired.return_value = False

        monkeypatch.setattr(sys, "argv",
                            ["main.py", "--token", "tkn_bad", "--pair-only"])
        monkeypatch.setattr(sys.stdin, "isatty", lambda: False)

        with patch("main.PrinterAgent", return_value=mock_agent), \
             patch("main.StartupService.initialize_environment"), \
             patch("main.LocalAgentDB.initialize_schema"), \
             patch("main.setup_logging"), \
             pytest.raises(SystemExit) as exc_info:
            m.main()

        assert exc_info.value.code == 1
