"""Shared fixtures for all test suites."""

import pytest

from agent_manage import Agent, AgentManager, AgentStatus, AgentType


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
