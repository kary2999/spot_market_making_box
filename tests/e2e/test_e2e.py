"""End-to-end tests simulating real user workflows."""

import subprocess
import sys

import pytest

from agent_manage import Agent, AgentManager, AgentStatus, AgentType


class TestOnboardingWorkflow:
    """User registers agents, verifies the dashboard, then cleans up."""

    def test_full_onboarding_and_teardown(self):
        manager = AgentManager()

        # User creates a fleet of agents
        specs = [
            ("support-chat", AgentType.CHAT),
            ("data-pipeline", AgentType.TASK),
            ("health-check", AgentType.MONITOR),
        ]
        registered = []
        for name, atype in specs:
            ag = Agent(name=name, agent_type=atype)
            manager.register(ag)
            registered.append(ag)

        # Verify all agents are present and idle
        assert manager.count()["total"] == 3
        assert manager.count()["idle"] == 3

        # User starts all agents
        for ag in registered:
            manager.start_agent(ag.agent_id)

        assert manager.count()["running"] == 3

        # User decommissions one agent
        manager.stop_agent(registered[2].agent_id)
        manager.remove(registered[2].agent_id)

        assert manager.count()["total"] == 2
        assert manager.count()["running"] == 2


class TestFaultToleranceWorkflow:
    """Simulate an agent crashing and being recovered."""

    def test_crash_and_recover(self):
        manager = AgentManager()
        ag = Agent(name="critical-worker", agent_type=AgentType.TASK)
        manager.register(ag)

        manager.start_agent(ag.agent_id)
        assert ag.status == AgentStatus.RUNNING

        # Simulate crash
        ag.set_error("OOM killed")
        assert ag.status == AgentStatus.ERROR
        assert manager.count()["error"] == 1

        # Operator resets and restarts
        ag.reset()
        manager.start_agent(ag.agent_id)
        assert ag.status == AgentStatus.RUNNING
        assert manager.count()["error"] == 0

    def test_partial_failure_does_not_affect_healthy_agents(self):
        manager = AgentManager()
        healthy = Agent(name="healthy", agent_type=AgentType.CHAT)
        unstable = Agent(name="unstable", agent_type=AgentType.TASK)
        manager.register(healthy)
        manager.register(unstable)

        manager.start_agent(healthy.agent_id)
        manager.start_agent(unstable.agent_id)
        unstable.set_error("timeout")

        assert manager.get(healthy.agent_id).status == AgentStatus.RUNNING
        assert manager.get(unstable.agent_id).status == AgentStatus.ERROR


class TestDashboardWorkflow:
    """User queries the dashboard for summary statistics."""

    def test_dashboard_counts_across_lifecycle(self):
        manager = AgentManager()
        agents = [Agent(name=f"worker-{i}", agent_type=AgentType.TASK) for i in range(6)]
        for ag in agents:
            manager.register(ag)

        # Start half
        for ag in agents[:3]:
            manager.start_agent(ag.agent_id)

        counts = manager.count()
        assert counts["total"] == 6
        assert counts["running"] == 3
        assert counts["idle"] == 3

        # Stop one, error one
        manager.stop_agent(agents[0].agent_id)
        agents[1].set_error("disk full")

        counts = manager.count()
        assert counts["running"] == 1
        assert counts["stopped"] == 1
        assert counts["error"] == 1
        assert counts["idle"] == 3

    def test_list_running_agents_as_dicts(self):
        manager = AgentManager()
        ag = Agent(name="api-server", agent_type=AgentType.CHAT)
        manager.register(ag)
        manager.start_agent(ag.agent_id)

        running = manager.list_agents(status=AgentStatus.RUNNING)
        assert len(running) == 1
        d = running[0].to_dict()
        assert d["name"] == "api-server"
        assert d["status"] == "running"
        assert d["agent_type"] == "chat"


class TestHelloScriptWorkflow:
    """E2E verification that the entry-point script works correctly."""

    def test_hello_script_runs_successfully(self):
        result = subprocess.run(
            [sys.executable, "hello.py"],
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        assert "hello world" in result.stdout
