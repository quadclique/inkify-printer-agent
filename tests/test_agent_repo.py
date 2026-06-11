"""
Tests for app.repositories.agent_repo.AgentRepository covering:
  get_config
  save_config
"""
import os

import pytest
import yaml

from app.core import config as cfg_module
from app.models.agent_model import AgentModel
from app.repositories.agent_repo import AgentRepository


@pytest.fixture()
def repo():
    return AgentRepository()



# get_config
class TestGetConfig:
    def test_returns_blank_model_when_file_missing(self, repo):
        model = repo.get_config()
        assert isinstance(model, AgentModel)
        assert model.agent_id == ""
        assert model.agent_token == ""

    def test_reads_existing_config_file(self, repo):
        cfg_module.config.AGENT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg_module.config.AGENT_CONFIG_FILE.write_text(
            yaml.safe_dump({
                "agent_id": "my-agent",
                "agent_token": "tok123",
                "location": "lobby",
                "features": {},
            })
        )
        model = repo.get_config()
        assert model.agent_id == "my-agent"
        assert model.agent_token == "tok123"
        assert model.location == "lobby"

    def test_returns_blank_model_on_corrupted_yaml(self, repo):
        cfg_module.config.AGENT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg_module.config.AGENT_CONFIG_FILE.write_text("{{{ invalid yaml !!!")
        model = repo.get_config()
        assert isinstance(model, AgentModel)
        assert model.agent_id == ""

    def test_returns_blank_model_on_empty_yaml(self, repo):
        cfg_module.config.AGENT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg_module.config.AGENT_CONFIG_FILE.write_text("")
        model = repo.get_config()
        assert isinstance(model, AgentModel)

    def test_reads_features_correctly(self, repo):
        cfg_module.config.AGENT_CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        cfg_module.config.AGENT_CONFIG_FILE.write_text(
            yaml.safe_dump({
                "agent_id": "x",
                "agent_token": "y",
                "location": "z",
                "features": {"qr_scan": True, "auto_update": False},
            })
        )
        model = repo.get_config()
        assert model.features_enabled["qr_scan"] is True
        assert model.features_enabled["auto_update"] is False



# save_config
class TestSaveConfig:
    def test_save_creates_file(self, repo):
        model = AgentModel(agent_id="a1", agent_token="tok", location="office")
        assert repo.save_config(model) is True
        assert cfg_module.config.AGENT_CONFIG_FILE.exists()

    def test_saved_file_is_valid_yaml(self, repo):
        model = AgentModel(agent_id="a1", agent_token="tok", location="office")
        repo.save_config(model)
        data = yaml.safe_load(cfg_module.config.AGENT_CONFIG_FILE.read_text())
        assert data["agent_id"] == "a1"
        assert data["agent_token"] == "tok"
        assert data["location"] == "office"

    def test_round_trip_get_then_save(self, repo):
        original = AgentModel(
            agent_id="rt-id",
            agent_token="rt-tok",
            location="floor3",
        )
        repo.save_config(original)
        loaded = repo.get_config()
        assert loaded.agent_id == "rt-id"
        assert loaded.agent_token == "rt-tok"
        assert loaded.location == "floor3"

    def test_creates_parent_directory_if_missing(self, repo):
        # isolate_config already created CONFIG_DIR; verify save still works
        model = AgentModel(agent_id="x", agent_token="y")
        assert repo.save_config(model) is True

    def test_overwrites_existing_file(self, repo):
        repo.save_config(AgentModel(agent_id="old", agent_token="old_tok"))
        repo.save_config(AgentModel(agent_id="new", agent_token="new_tok"))
        loaded = repo.get_config()
        assert loaded.agent_id == "new"
        assert loaded.agent_token == "new_tok"

    def test_file_permissions_restricted_on_unix(self, repo):
        if os.name == "nt":
            pytest.skip("Permission check not applicable on Windows")
        model = AgentModel(agent_id="a1", agent_token="tok")
        repo.save_config(model)
        mode = oct(cfg_module.config.AGENT_CONFIG_FILE.stat().st_mode)
        # 0o600 → owner read/write only
        assert mode.endswith("600")

    def test_save_preserves_features(self, repo):
        model = AgentModel(
            agent_id="f1",
            agent_token="ft",
            features_enabled={"qr_scan": True},
        )
        repo.save_config(model)
        loaded = repo.get_config()
        assert loaded.features_enabled.get("qr_scan") is True
