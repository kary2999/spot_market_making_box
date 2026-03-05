"""
pytest 全局配置与 fixture 定义

所有 fixture 均为函数级别（function scope），确保每个测试用例
使用独立实例，避免状态污染。
"""
import pytest

from agent_manage.agent import Agent, AgentStatus
from agent_manage.manager import AgentManager
from tests.fixtures.agent_fixtures import make_agent, make_manager
from tests.helpers.builders import AgentBuilder
from tests.mocks.mock_hooks import CallTracker
from tests.mocks.mock_storage import MockStorage


# ------------------------------------------------------------------
# 基础 Agent fixture
# ------------------------------------------------------------------


@pytest.fixture
def idle_agent() -> Agent:
    """处于 IDLE 状态的干净 Agent"""
    return make_agent()


@pytest.fixture
def running_agent() -> Agent:
    """预设为 RUNNING 状态的 Agent（不触发钩子）"""
    return make_agent(status=AgentStatus.RUNNING)


@pytest.fixture
def agent_with_config() -> Agent:
    """携带自定义配置的 Agent"""
    return make_agent(
        agent_id="config-agent",
        name="ConfigAgent",
        config={"model": "claude-sonnet-4-6", "max_tokens": 2048},
    )


# ------------------------------------------------------------------
# AgentManager fixture
# ------------------------------------------------------------------


@pytest.fixture
def empty_manager() -> AgentManager:
    """空的 AgentManager，适合测试创建逻辑"""
    return make_manager(pre_populate=False)


@pytest.fixture
def populated_manager() -> AgentManager:
    """预填充了 3 个 Agent 的 Manager，适合测试读取/删除逻辑"""
    return make_manager(pre_populate=True)


@pytest.fixture
def manager_with_mock_storage() -> tuple[AgentManager, MockStorage]:
    """
    使用 MockStorage 的 Manager，返回 (manager, storage) 元组，
    测试可以在操作后检查 storage.set_calls / del_calls。
    """
    storage = MockStorage()
    manager = AgentManager(storage=storage)
    storage.reset_call_log()  # 清除初始化噪音
    return manager, storage


# ------------------------------------------------------------------
# 钩子 / 回调 fixture
# ------------------------------------------------------------------


@pytest.fixture
def call_tracker() -> CallTracker:
    """通用调用追踪器，可注入到任何需要回调的地方"""
    return CallTracker()


@pytest.fixture
def agent_with_hooks(call_tracker: CallTracker) -> tuple[Agent, CallTracker]:
    """
    绑定了 on_start 和 on_stop 钩子的 Agent。
    返回 (agent, tracker)，tracker 同时追踪两个钩子的调用。
    """
    agent = (
        AgentBuilder()
        .with_id("hooked-agent")
        .on_start(call_tracker)
        .on_stop(call_tracker)
        .build()
    )
    return agent, call_tracker
