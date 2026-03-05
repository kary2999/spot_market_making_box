"""
自定义断言工具函数

将复杂的断言逻辑封装为语义化函数，让测试用例保持简洁可读。
"""
from __future__ import annotations

from typing import Any

from agent_manage.agent import Agent, AgentStatus


def assert_agent_dict(result: dict[str, Any], expected: dict[str, Any]) -> None:
    """
    比较 Agent.to_dict() 的输出，忽略 created_at 时间戳（不稳定字段）。

    Example::

        assert_agent_dict(agent.to_dict(), {"agent_id": "x", "name": "X", "status": "idle"})
    """
    ignore_keys = {"created_at"}
    filtered_result = {k: v for k, v in result.items() if k not in ignore_keys}
    filtered_expected = {k: v for k, v in expected.items() if k not in ignore_keys}
    assert filtered_result == filtered_expected, (
        f"Agent dict mismatch.\n"
        f"  Got:      {filtered_result}\n"
        f"  Expected: {filtered_expected}"
    )


def assert_status(agent: Agent, expected: AgentStatus) -> None:
    """
    断言 Agent 处于期望的状态，提供清晰的错误信息。

    Example::

        assert_status(agent, AgentStatus.RUNNING)
    """
    assert agent.status == expected, (
        f"Agent '{agent.agent_id}' status mismatch: "
        f"got '{agent.status.value}', expected '{expected.value}'"
    )


def assert_agents_count(agents: list[Agent], expected_count: int) -> None:
    """断言 Agent 列表长度"""
    assert len(agents) == expected_count, (
        f"Expected {expected_count} agents, got {len(agents)}"
    )
