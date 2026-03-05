"""Shared fixtures for all test suites."""

import pytest

from agent_manage import Agent, AgentManager, AgentStatus, AgentType
from tests.mocks.mock_storage import MockStorage


@pytest.fixture
def manager():
    """Return a fresh AgentManager for each test."""
    return AgentManager()


@pytest.fixture
def chat_agent():
    """CHAT-type agent named 'chat-bot'."""
    return Agent(name="chat-bot", agent_type=AgentType.CHAT)


@pytest.fixture
def task_agent():
    """TASK-type agent named 'task-bot'."""
    return Agent(name="task-bot", agent_type=AgentType.TASK)


@pytest.fixture
def populated_manager(manager, chat_agent, task_agent):
    """Manager pre-loaded with three agents (CHAT, TASK, MONITOR)."""
    monitor = Agent(name="sys-monitor", agent_type=AgentType.MONITOR)
    manager.register(chat_agent)
    manager.register(task_agent)
    manager.register(monitor)
    return manager


@pytest.fixture
def idle_agent():
    """An IDLE agent for lifecycle tests."""
    return Agent(name="idle-agent", agent_type=AgentType.CHAT)


@pytest.fixture
def running_agent():
    """A RUNNING agent for lifecycle tests."""
    agent = Agent(name="running-agent", agent_type=AgentType.CHAT)
    agent.start()
    return agent


@pytest.fixture
def agent_with_hooks():
    """An agent paired with a call tracker (used to verify stop was called)."""
    from tests.mocks.mock_hooks import CallTracker
    tracker = CallTracker()
    agent = Agent(name="hooked-agent", agent_type=AgentType.CHAT)
    return agent, tracker


@pytest.fixture
def empty_manager():
    """An empty AgentManager."""
    return AgentManager()


@pytest.fixture
def manager_with_mock_storage():
    """AgentManager whose internal _agents dict is replaced with MockStorage."""
    mgr = AgentManager()
    storage = MockStorage()
    mgr._agents = storage
    return mgr, storage
