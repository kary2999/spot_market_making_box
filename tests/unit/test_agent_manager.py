"""Unit tests for AgentManager CRUD and query operations."""

import pytest

from agent_manage import (
    Agent,
    AgentManager,
    AgentNotFoundError,
    AgentStatus,
    AgentType,
    DuplicateAgentError,
)


class TestRegister:
    def test_register_returns_agent(self, manager, chat_agent):
        result = manager.register(chat_agent)
        assert result is chat_agent

    def test_registered_agent_is_retrievable(self, manager, chat_agent):
        manager.register(chat_agent)
        assert manager.get(chat_agent.agent_id) is chat_agent

    def test_duplicate_name_raises(self, manager, chat_agent):
        manager.register(chat_agent)
        duplicate = Agent(name="chat-bot", agent_type=AgentType.CHAT)
        with pytest.raises(DuplicateAgentError):
            manager.register(duplicate)

    def test_different_names_allowed(self, manager, chat_agent, task_agent):
        manager.register(chat_agent)
        manager.register(task_agent)
        assert len(manager.list_agents()) == 2


class TestGet:
    def test_get_existing_agent(self, manager, chat_agent):
        manager.register(chat_agent)
        assert manager.get(chat_agent.agent_id) is chat_agent

    def test_get_nonexistent_raises(self, manager):
        with pytest.raises(AgentNotFoundError):
            manager.get("nonexistent-id")


class TestRemove:
    def test_remove_existing_agent(self, manager, chat_agent):
        manager.register(chat_agent)
        manager.remove(chat_agent.agent_id)
        assert len(manager.list_agents()) == 0

    def test_remove_nonexistent_raises(self, manager):
        with pytest.raises(AgentNotFoundError):
            manager.remove("nonexistent-id")

    def test_removed_agent_not_retrievable(self, manager, chat_agent):
        manager.register(chat_agent)
        manager.remove(chat_agent.agent_id)
        with pytest.raises(AgentNotFoundError):
            manager.get(chat_agent.agent_id)


class TestListAgents:
    def test_list_all(self, populated_manager):
        assert len(populated_manager.list_agents()) == 3

    def test_list_empty_manager(self, manager):
        assert manager.list_agents() == []

    def test_filter_by_status(self, populated_manager, chat_agent):
        chat_agent.start()
        running = populated_manager.list_agents(status=AgentStatus.RUNNING)
        assert len(running) == 1
        assert running[0] is chat_agent

    def test_filter_by_type(self, populated_manager, task_agent):
        tasks = populated_manager.list_agents(agent_type=AgentType.TASK)
        assert len(tasks) == 1
        assert tasks[0] is task_agent

    def test_filter_by_status_and_type(self, populated_manager, chat_agent):
        chat_agent.start()
        results = populated_manager.list_agents(
            status=AgentStatus.RUNNING, agent_type=AgentType.CHAT
        )
        assert len(results) == 1
        assert results[0] is chat_agent

    def test_filter_no_match(self, populated_manager):
        results = populated_manager.list_agents(status=AgentStatus.ERROR)
        assert results == []


class TestStartStopAgent:
    def test_start_agent_via_manager(self, manager, chat_agent):
        manager.register(chat_agent)
        manager.start_agent(chat_agent.agent_id)
        assert chat_agent.status == AgentStatus.RUNNING

    def test_stop_agent_via_manager(self, manager, chat_agent):
        manager.register(chat_agent)
        manager.start_agent(chat_agent.agent_id)
        manager.stop_agent(chat_agent.agent_id)
        assert chat_agent.status == AgentStatus.STOPPED

    def test_start_nonexistent_raises(self, manager):
        with pytest.raises(AgentNotFoundError):
            manager.start_agent("bad-id")

    def test_stop_nonexistent_raises(self, manager):
        with pytest.raises(AgentNotFoundError):
            manager.stop_agent("bad-id")


class TestCount:
    def test_count_empty(self, manager):
        counts = manager.count()
        assert counts["total"] == 0
        assert counts["idle"] == 0

    def test_count_total(self, populated_manager):
        assert populated_manager.count()["total"] == 3

    def test_count_by_status(self, populated_manager, chat_agent):
        chat_agent.start()
        counts = populated_manager.count()
        assert counts["running"] == 1
        assert counts["idle"] == 2

    def test_count_includes_all_statuses(self, manager):
        counts = manager.count()
        for status in AgentStatus:
            assert status.value in counts
