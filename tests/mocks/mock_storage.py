"""
MockStorage —— 模拟持久化存储

可以替换 AgentManager 内部的 _storage 字典，
并额外记录所有读写操作，便于在测试中断言存储交互行为。
"""
from __future__ import annotations

from typing import Any, Iterator


class MockStorage(dict):
    """
    继承 dict 以保持与真实 storage 完全兼容，
    同时记录所有 __setitem__ / __delitem__ 操作。
    """

    def __init__(self, *args: Any, **kwargs: Any):
        super().__init__(*args, **kwargs)
        self.set_calls: list[str] = []   # 记录每次 set 的 key
        self.del_calls: list[str] = []   # 记录每次 delete 的 key
        self.get_calls: list[str] = []   # 记录每次 get 的 key

    def __setitem__(self, key: str, value: Any) -> None:
        self.set_calls.append(key)
        super().__setitem__(key, value)

    def __delitem__(self, key: str) -> None:
        self.del_calls.append(key)
        super().__delitem__(key)

    def __getitem__(self, key: str) -> Any:
        self.get_calls.append(key)
        return super().__getitem__(key)

    def reset_call_log(self) -> None:
        """在测试的 arrange 阶段重置调用记录，排除初始化噪音"""
        self.set_calls.clear()
        self.del_calls.clear()
        self.get_calls.clear()
