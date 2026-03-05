"""单元测试 — Agent 实体及生命周期状态机 (agent_manage/agent.py)"""

import pytest

from agent_manage.agent import Agent, AgentStatus, AgentType


# ---------------------------------------------------------------------------
# 测试夹具
# ---------------------------------------------------------------------------


@pytest.fixture
def agent_a() -> Agent:
    """标准测试 Agent：name='Alpha', type=CHAT"""
    return Agent(name="Alpha", agent_type=AgentType.CHAT)


@pytest.fixture
def running_agent_a(agent_a: Agent) -> Agent:
    agent_a.start()
    return agent_a


# ---------------------------------------------------------------------------
# 创建
# ---------------------------------------------------------------------------


class TestAgentCreation:
    def test_default_status_is_idle(self, agent_a):
        assert agent_a.status == AgentStatus.IDLE

    def test_name_set(self, agent_a):
        assert agent_a.name == "Alpha"

    def test_agent_type_set(self, agent_a):
        assert agent_a.agent_type == AgentType.CHAT

    def test_metadata_defaults_to_empty(self, agent_a):
        assert agent_a.metadata == {}

    def test_created_at_is_set(self, agent_a):
        assert agent_a.created_at > 0

    def test_agent_id_auto_generated(self, agent_a):
        assert isinstance(agent_a.agent_id, str)
        assert len(agent_a.agent_id) > 0

    def test_default_model(self, agent_a):
        assert agent_a.model == "claude-sonnet-4-6"

    def test_custom_model(self):
        ag = Agent(name="Bot", agent_type=AgentType.TASK, model="claude-opus-4-6")
        assert ag.model == "claude-opus-4-6"

    def test_two_agents_have_different_ids(self):
        a = Agent(name="A", agent_type=AgentType.CHAT)
        b = Agent(name="B", agent_type=AgentType.TASK)
        assert a.agent_id != b.agent_id


# ---------------------------------------------------------------------------
# start
# ---------------------------------------------------------------------------


class TestAgentStart:
    def test_start_sets_running_status(self, agent_a):
        agent_a.start()
        assert agent_a.status == AgentStatus.RUNNING

    def test_start_already_running_raises_value_error(self, running_agent_a):
        with pytest.raises(ValueError):
            running_agent_a.start()

    def test_start_from_stopped_state_after_reset(self, agent_a):
        agent_a.start()
        agent_a.stop()
        agent_a.reset()
        agent_a.start()
        assert agent_a.status == AgentStatus.RUNNING

    def test_start_from_error_state_raises(self, agent_a):
        agent_a.set_error("boom")
        with pytest.raises(ValueError):
            agent_a.start()

    def test_start_from_error_state_after_reset(self, agent_a):
        agent_a.set_error("boom")
        agent_a.reset()
        agent_a.start()
        assert agent_a.status == AgentStatus.RUNNING


# ---------------------------------------------------------------------------
# stop
# ---------------------------------------------------------------------------


class TestAgentStop:
    def test_stop_sets_stopped_status(self, running_agent_a):
        running_agent_a.stop()
        assert running_agent_a.status == AgentStatus.STOPPED

    def test_stop_idle_agent_raises(self, agent_a):
        with pytest.raises(ValueError):
            agent_a.stop()

    def test_stop_already_stopped_is_no_op(self, running_agent_a):
        running_agent_a.stop()
        running_agent_a.stop()  # idempotent
        assert running_agent_a.status == AgentStatus.STOPPED


# ---------------------------------------------------------------------------
# reset
# ---------------------------------------------------------------------------


class TestAgentReset:
    def test_reset_from_error_to_idle(self, agent_a):
        agent_a.set_error("network failure")
        agent_a.reset()
        assert agent_a.status == AgentStatus.IDLE

    def test_reset_from_stopped_to_idle(self, running_agent_a):
        running_agent_a.stop()
        running_agent_a.reset()
        assert running_agent_a.status == AgentStatus.IDLE

    def test_reset_from_idle_is_no_op(self, agent_a):
        agent_a.reset()
        assert agent_a.status == AgentStatus.IDLE


# ---------------------------------------------------------------------------
# set_error
# ---------------------------------------------------------------------------


class TestAgentSetError:
    def test_set_error_changes_status(self, agent_a):
        agent_a.set_error("disk full")
        assert agent_a.status == AgentStatus.ERROR

    def test_set_error_with_message_stored_in_metadata(self, agent_a):
        agent_a.set_error("disk full")
        assert agent_a.metadata["error"] == "disk full"

    def test_set_error_empty_message_no_metadata_key(self, agent_a):
        agent_a.set_error("")
        assert "error" not in agent_a.metadata

    def test_set_error_no_message_defaults(self, agent_a):
        agent_a.set_error()
        assert agent_a.status == AgentStatus.ERROR


# ---------------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------------


class TestAgentToDict:
    def test_to_dict_has_required_keys(self, agent_a):
        d = agent_a.to_dict()
        for key in ("agent_id", "name", "agent_type", "model", "status", "created_at", "metadata"):
            assert key in d

    def test_to_dict_status_is_string(self, agent_a):
        d = agent_a.to_dict()
        assert isinstance(d["status"], str)
        assert d["status"] == "idle"

    def test_to_dict_name_matches(self, agent_a):
        assert agent_a.to_dict()["name"] == "Alpha"

    def test_to_dict_agent_id_matches(self, agent_a):
        assert agent_a.to_dict()["agent_id"] == agent_a.agent_id

    def test_to_dict_running_status(self, running_agent_a):
        assert running_agent_a.to_dict()["status"] == "running"

    def test_to_dict_agent_type_is_string(self, agent_a):
        assert agent_a.to_dict()["agent_type"] == "chat"
