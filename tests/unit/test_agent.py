"""Unit tests for the Agent dataclass and its state machine."""

import pytest

from agent_manage import Agent, AgentStatus
from agent_manage.exceptions import AgentAlreadyRunningError


class TestAgentCreation:
    def test_default_status_is_idle(self, agent_a):
        assert agent_a.status == AgentStatus.IDLE

    def test_id_and_name_set(self):
        ag = Agent(id="test-id", name="TestBot")
        assert ag.id == "test-id"
        assert ag.name == "TestBot"

    def test_config_defaults_to_empty(self, agent_a):
        assert agent_a.config == {}

    def test_created_at_is_set(self, agent_a):
        assert agent_a.created_at > 0

    def test_custom_config(self):
        ag = Agent(id="x", name="X", config={"model": "claude-opus-4-6"})
        assert ag.config["model"] == "claude-opus-4-6"

    def test_on_start_defaults_none(self, agent_a):
        assert agent_a._on_start is None

    def test_on_stop_defaults_none(self, agent_a):
        assert agent_a._on_stop is None


class TestAgentStart:
    def test_start_sets_running_status(self, agent_a):
        agent_a.start()
        assert agent_a.status == AgentStatus.RUNNING

    def test_start_already_running_raises(self, agent_a):
        agent_a.start()
        with pytest.raises(AgentAlreadyRunningError):
            agent_a.start()

    def test_start_already_running_error_contains_id(self, agent_a):
        agent_a.start()
        with pytest.raises(AgentAlreadyRunningError) as exc_info:
            agent_a.start()
        assert exc_info.value.agent_id == "agent-a"

    def test_start_triggers_on_start_hook(self, agent_a):
        called_with = []
        agent_a._on_start = lambda ag: called_with.append(ag)
        agent_a.start()
        assert called_with == [agent_a]

    def test_start_from_stopped_state(self, agent_a):
        agent_a.start()
        agent_a.stop()
        agent_a.start()
        assert agent_a.status == AgentStatus.RUNNING

    def test_start_from_error_state(self, agent_a):
        agent_a.set_error("boom")
        agent_a.start()
        assert agent_a.status == AgentStatus.RUNNING


class TestAgentStop:
    def test_stop_sets_stopped_status(self, agent_a):
        agent_a.start()
        agent_a.stop()
        assert agent_a.status == AgentStatus.STOPPED

    def test_stop_idle_agent_sets_stopped(self, agent_a):
        agent_a.stop()
        assert agent_a.status == AgentStatus.STOPPED

    def test_stop_triggers_on_stop_hook(self, agent_a):
        called_with = []
        agent_a._on_stop = lambda ag: called_with.append(ag)
        agent_a.start()
        agent_a.stop()
        assert called_with == [agent_a]

    def test_stop_without_hook_does_not_raise(self, agent_a):
        agent_a.start()
        agent_a.stop()  # no hook set


class TestAgentSetError:
    def test_set_error_changes_status(self, agent_a):
        agent_a.set_error("network failure")
        assert agent_a.status == AgentStatus.ERROR

    def test_set_error_with_reason_stored_in_config(self, agent_a):
        agent_a.set_error("disk full")
        assert agent_a.config["last_error"] == "disk full"

    def test_set_error_empty_reason_no_config_key(self, agent_a):
        agent_a.set_error("")
        assert "last_error" not in agent_a.config

    def test_set_error_no_reason_default(self, agent_a):
        agent_a.set_error()
        assert agent_a.status == AgentStatus.ERROR


class TestAgentToDict:
    def test_to_dict_has_required_keys(self, agent_a):
        d = agent_a.to_dict()
        for key in ("id", "name", "config", "status", "created_at"):
            assert key in d

    def test_to_dict_status_is_string(self, agent_a):
        d = agent_a.to_dict()
        assert isinstance(d["status"], str)
        assert d["status"] == "idle"

    def test_to_dict_id_matches(self, agent_a):
        assert agent_a.to_dict()["id"] == "agent-a"

    def test_to_dict_name_matches(self, agent_a):
        assert agent_a.to_dict()["name"] == "Alpha"

    def test_to_dict_running_status(self, agent_a):
        agent_a.start()
        assert agent_a.to_dict()["status"] == "running"
