"""Integration tests: verify interactions between Agent and AgentManager."""

import pytest

from agent_manage import (
    Agent,
    AgentManager,
    AgentNotFoundError,
    AgentStatus,
    AgentType,
    DuplicateAgentError,
)


class TestLifecycleIntegration:
    """Full agent lifecycle through the manager."""

    def test_register_start_stop_remove(self, manager):
        agent = Agent(name="lifecycle", agent_type=AgentType.TASK)
        manager.register(agent)

        manager.start_agent(agent.agent_id)
        assert manager.get(agent.agent_id).status == AgentStatus.RUNNING

        manager.stop_agent(agent.agent_id)
        assert manager.get(agent.agent_id).status == AgentStatus.STOPPED

        manager.remove(agent.agent_id)
        with pytest.raises(AgentNotFoundError):
            manager.get(agent.agent_id)

    def test_error_recovery_flow(self, manager):
        agent = Agent(name="recoverable", agent_type=AgentType.CHAT)
        manager.register(agent)

        manager.start_agent(agent.agent_id)
        agent.set_error("simulated crash")
        assert manager.get(agent.agent_id).status == AgentStatus.ERROR

        agent.reset()
        manager.start_agent(agent.agent_id)
        assert manager.get(agent.agent_id).status == AgentStatus.RUNNING


class TestMultiAgentIntegration:
    """Multiple agents coexisting in the same manager."""

    def test_independent_state_per_agent(self, manager):
        a1 = Agent(name="agent-1", agent_type=AgentType.CHAT)
        a2 = Agent(name="agent-2", agent_type=AgentType.TASK)
        manager.register(a1)
        manager.register(a2)

        manager.start_agent(a1.agent_id)

        assert manager.get(a1.agent_id).status == AgentStatus.RUNNING
        assert manager.get(a2.agent_id).status == AgentStatus.IDLE

    def test_count_reflects_live_state(self, manager):
        agents = [
            Agent(name=f"agent-{i}", agent_type=AgentType.CHAT) for i in range(5)
        ]
        for ag in agents:
            manager.register(ag)

        for ag in agents[:3]:
            manager.start_agent(ag.agent_id)

        counts = manager.count()
        assert counts["total"] == 5
        assert counts["running"] == 3
        assert counts["idle"] == 2

    def test_remove_one_does_not_affect_others(self, populated_manager, chat_agent, task_agent):
        populated_manager.remove(chat_agent.agent_id)
        assert len(populated_manager.list_agents()) == 2
        populated_manager.get(task_agent.agent_id)  # must not raise

    def test_duplicate_name_after_removal_allowed(self, manager):
        agent = Agent(name="reusable", agent_type=AgentType.CHAT)
        manager.register(agent)
        manager.remove(agent.agent_id)

        new_agent = Agent(name="reusable", agent_type=AgentType.CHAT)
        manager.register(new_agent)
        assert len(manager.list_agents()) == 1


class TestFilterIntegration:
    """Filtering across a mixed population."""

    def test_filter_running_from_mixed(self, manager):
        running_ids = set()
        for i in range(4):
            ag = Agent(name=f"ag-{i}", agent_type=AgentType.CHAT)
            manager.register(ag)
            if i % 2 == 0:
                manager.start_agent(ag.agent_id)
                running_ids.add(ag.agent_id)

        results = manager.list_agents(status=AgentStatus.RUNNING)
        assert {a.agent_id for a in results} == running_ids

    def test_filter_by_type_returns_correct_subset(self, populated_manager):
        chat_agents = populated_manager.list_agents(agent_type=AgentType.CHAT)
        monitor_agents = populated_manager.list_agents(agent_type=AgentType.MONITOR)
        assert len(chat_agents) == 1
        assert len(monitor_agents) == 1
        assert chat_agents[0].name == "chat-bot"
        assert monitor_agents[0].name == "sys-monitor"
