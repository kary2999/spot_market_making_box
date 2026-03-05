# mocks 包：提供可控的外部依赖替代品
from .mock_storage import MockStorage
from .mock_hooks import CallTracker, make_hook

__all__ = ["MockStorage", "CallTracker", "make_hook"]
