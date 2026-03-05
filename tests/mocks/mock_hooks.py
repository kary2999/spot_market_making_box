"""
可记录调用次数和参数的 mock 钩子

用于测试 Agent 的 _on_start / _on_stop 回调是否被正确触发。
"""
from __future__ import annotations

from typing import Any, Callable


class CallTracker:
    """通用调用追踪器，可作为任意回调的 mock 替代品"""

    def __init__(self) -> None:
        self.call_count: int = 0
        self.call_args: list[tuple[Any, ...]] = []
        self.call_kwargs: list[dict[str, Any]] = []

    def __call__(self, *args: Any, **kwargs: Any) -> None:
        self.call_count += 1
        self.call_args.append(args)
        self.call_kwargs.append(kwargs)

    @property
    def called(self) -> bool:
        return self.call_count > 0

    @property
    def last_args(self) -> tuple[Any, ...] | None:
        return self.call_args[-1] if self.call_args else None

    def assert_called_once(self) -> None:
        assert self.call_count == 1, f"Expected 1 call, got {self.call_count}"

    def assert_not_called(self) -> None:
        assert self.call_count == 0, f"Expected 0 calls, got {self.call_count}"

    def reset(self) -> None:
        self.call_count = 0
        self.call_args.clear()
        self.call_kwargs.clear()


def make_hook(tracker: CallTracker | None = None) -> tuple[Callable, CallTracker]:
    """
    便捷工厂：返回 (hook函数, 追踪器) 元组

    Example::

        hook, tracker = make_hook()
        agent = make_agent()
        agent._on_start = hook
        agent.start()
        tracker.assert_called_once()
    """
    if tracker is None:
        tracker = CallTracker()
    return tracker, tracker
