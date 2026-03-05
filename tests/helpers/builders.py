"""
Builder 模式的测试数据构建器

链式 API 让测试的 Arrange 阶段更具可读性，
同时集中管理默认值，减少重复代码。
"""
from __future__ import annotations

from typing import Any, Callable, Optional

from agent_manage.agent import Agent, AgentStatus


class AgentBuilder:
    """
    流式构建 Agent 测试实例。

    Example::

        agent = (
            AgentBuilder()
            .with_id("agent-x")
            .with_name("MyAgent")
            .with_config({"key": "value"})
            .running()
            .build()
        )
    """

    def __init__(self) -> None:
        self._id: str = "builder-agent"
        self._name: str = "BuiltAgent"
        self._config: dict[str, Any] = {}
        self._status: AgentStatus = AgentStatus.IDLE
        self._on_start: Optional[Callable] = None
        self._on_stop: Optional[Callable] = None

    def with_id(self, agent_id: str) -> "AgentBuilder":
        self._id = agent_id
        return self

    def with_name(self, name: str) -> "AgentBuilder":
        self._name = name
        return self

    def with_config(self, config: dict[str, Any]) -> "AgentBuilder":
        self._config = config
        return self

    def idle(self) -> "AgentBuilder":
        self._status = AgentStatus.IDLE
        return self

    def running(self) -> "AgentBuilder":
        self._status = AgentStatus.RUNNING
        return self

    def stopped(self) -> "AgentBuilder":
        self._status = AgentStatus.STOPPED
        return self

    def with_error(self) -> "AgentBuilder":
        self._status = AgentStatus.ERROR
        return self

    def on_start(self, callback: Callable) -> "AgentBuilder":
        self._on_start = callback
        return self

    def on_stop(self, callback: Callable) -> "AgentBuilder":
        self._on_stop = callback
        return self

    def build(self) -> Agent:
        agent = Agent(
            id=self._id,
            name=self._name,
            config=self._config.copy(),
            _on_start=self._on_start,
            _on_stop=self._on_stop,
        )
        agent.status = self._status
        return agent
