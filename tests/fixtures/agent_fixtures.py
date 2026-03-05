"""
测试数据工厂 (Test Data Factory)

提供可参数化的工厂函数，在每个测试用例中生成独立的数据实例，
避免测试间共享可变状态造成的干扰。
"""
from __future__ import annotations

from typing import Any

from agent_manage.agent import Agent, AgentStatus
from agent_manage.manager import AgentManager

# ------------------------------------------------------------------
# 静态样本数据（只读，用于参数化测试或快照断言）
# ------------------------------------------------------------------

SAMPLE_AGENTS: list[dict[str, Any]] = [
    {
        "id": "agent-001",
        "name": "DataCollector",
        "config": {"interval": 30, "retry": 3},
    },
    {
        "id": "agent-002",
        "name": "Analyzer",
        "config": {"model": "gpt-4", "temperature": 0.7},
    },
    {
        "id": "agent-003",
        "name": "Reporter",
        "config": {"format": "json", "destination": "s3://bucket/reports"},
    },
]


# ------------------------------------------------------------------
# 工厂函数：每次调用返回全新实例
# ------------------------------------------------------------------


def make_agent(
    agent_id: str = "test-agent",
    name: str = "TestAgent",
    config: dict[str, Any] | None = None,
    status: AgentStatus = AgentStatus.IDLE,
) -> Agent:
    """创建一个独立的 Agent 测试实例，支持覆盖任意字段"""
    agent = Agent(id=agent_id, name=name, config=config or {})
    agent.status = status
    return agent


def make_manager(pre_populate: bool = False) -> AgentManager:
    """
    创建一个隔离的 AgentManager 实例。

    Args:
        pre_populate: 若为 True，预填充 SAMPLE_AGENTS 数据，
                      适用于需要现有数据的读取/更新类测试。
    """
    manager = AgentManager()
    if pre_populate:
        for data in SAMPLE_AGENTS:
            manager.create(
                agent_id=data["id"],
                name=data["name"],
                config=data["config"].copy(),  # 防止样本数据被测试修改
            )
    return manager
