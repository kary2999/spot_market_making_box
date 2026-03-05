"""
Agent 单元测试示例

演示如何综合使用 fixtures、mocks 和 helpers。
"""
import pytest

from agent_manage.agent import AgentStatus
from agent_manage.exceptions import AgentAlreadyRunningError, AgentNotFoundError
from tests.helpers.assertions import assert_agent_dict, assert_status
from tests.helpers.builders import AgentBuilder
from tests.mocks.mock_hooks import CallTracker, make_hook


class TestAgentLifecycle:
    def test_idle_agent_can_start(self, idle_agent):
        idle_agent.start()
        assert_status(idle_agent, AgentStatus.RUNNING)

    def test_start_triggers_on_start_hook(self):
        tracker = CallTracker()
        agent = AgentBuilder().on_start(tracker).build()

        agent.start()

        tracker.assert_called_once()
        assert tracker.last_args[0] is agent  # 钩子接收到 agent 自身

    def test_running_agent_cannot_start_again(self, running_agent):
        with pytest.raises(AgentAlreadyRunningError) as exc_info:
            running_agent.start()
        assert exc_info.value.agent_id == running_agent.id

    def test_stop_triggers_on_stop_hook(self, agent_with_hooks):
        agent, tracker = agent_with_hooks
        agent.start()
        tracker.reset()  # 忽略 start 的调用

        agent.stop()

        tracker.assert_called_once()

    def test_set_error_updates_status_and_config(self, idle_agent):
        idle_agent.set_error("timeout")

        assert_status(idle_agent, AgentStatus.ERROR)
        assert idle_agent.config["last_error"] == "timeout"

    def test_to_dict_serializes_correctly(self):
        agent = AgentBuilder().with_id("x").with_name("X").build()

        assert_agent_dict(
            agent.to_dict(),
            {"id": "x", "name": "X", "config": {}, "status": "idle"},
        )


class TestAgentManager:
    def test_create_and_get(self, empty_manager):
        empty_manager.create("a1", "Alpha")
        agent = empty_manager.get("a1")
        assert agent.name == "Alpha"

    def test_get_nonexistent_raises(self, empty_manager):
        with pytest.raises(AgentNotFoundError):
            empty_manager.get("ghost")

    def test_delete_removes_agent(self, populated_manager):
        populated_manager.delete("agent-001")
        assert populated_manager.count() == 2

    def test_list_agents_filtered_by_status(self, populated_manager):
        populated_manager.start_agent("agent-001")

        running = populated_manager.list_agents(status=AgentStatus.RUNNING)
        assert len(running) == 1
        assert running[0].id == "agent-001"

    def test_mock_storage_records_operations(self, manager_with_mock_storage):
        manager, storage = manager_with_mock_storage

        manager.create("new-agent", "New")

        assert "new-agent" in storage.set_calls
