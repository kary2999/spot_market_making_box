"""
Agent 单元测试示例

演示如何综合使用 fixtures、mocks 和 helpers。
"""
import pytest

from agent_manage.agent import Agent, AgentStatus, AgentType
from agent_manage.exceptions import AgentNotFoundError
from tests.helpers.assertions import assert_agent_dict, assert_status
from tests.helpers.builders import AgentBuilder
from tests.mocks.mock_hooks import CallTracker, make_hook


class TestAgentLifecycle:
    def test_idle_agent_can_start(self, idle_agent):
        idle_agent.start()
        assert_status(idle_agent, AgentStatus.RUNNING)

    def test_start_changes_status_to_running(self):
        agent = AgentBuilder().build()
        agent.start()
        assert_status(agent, AgentStatus.RUNNING)

    def test_running_agent_cannot_start_again(self, running_agent):
        with pytest.raises(ValueError):
            running_agent.start()

    def test_stop_changes_status_to_stopped(self, agent_with_hooks):
        agent, tracker = agent_with_hooks
        agent.start()
        agent.stop()
        assert_status(agent, AgentStatus.STOPPED)

    def test_set_error_updates_status_and_metadata(self, idle_agent):
        idle_agent.set_error("timeout")

        assert_status(idle_agent, AgentStatus.ERROR)
        assert idle_agent.metadata["error"] == "timeout"

    def test_to_dict_serializes_correctly(self):
        agent = AgentBuilder().with_id("x").with_name("X").build()

        assert_agent_dict(
            agent.to_dict(),
            {
                "agent_id": "x",
                "name": "X",
                "agent_type": "chat",
                "model": "claude-sonnet-4-6",
                "metadata": {},
                "status": "idle",
            },
        )


class TestAgentManager:
    def test_create_and_get(self, empty_manager):
        agent = Agent(name="Alpha", agent_type=AgentType.CHAT)
        empty_manager.register(agent)
        retrieved = empty_manager.get(agent.agent_id)
        assert retrieved.name == "Alpha"

    def test_get_nonexistent_raises(self, empty_manager):
        with pytest.raises(AgentNotFoundError):
            empty_manager.get("ghost")

    def test_delete_removes_agent(self, populated_manager):
        first_id = list(populated_manager._agents.keys())[0]
        populated_manager.remove(first_id)
        assert populated_manager.count()["total"] == 2

    def test_list_agents_filtered_by_status(self, populated_manager, chat_agent):
        populated_manager.start_agent(chat_agent.agent_id)

        running = populated_manager.list_agents(status=AgentStatus.RUNNING)
        assert len(running) == 1
        assert running[0].agent_id == chat_agent.agent_id

    def test_mock_storage_records_operations(self, manager_with_mock_storage):
        manager, storage = manager_with_mock_storage
        agent = Agent(name="new-agent", agent_type=AgentType.CHAT)

        manager.register(agent)

        assert agent.agent_id in storage.set_calls
