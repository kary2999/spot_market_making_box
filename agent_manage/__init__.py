# agent_manage: AI Agent management core module
from .agent import Agent, AgentStatus, AgentType
from .exceptions import AgentAlreadyRunningError, AgentError, AgentNotFoundError, DuplicateAgentError
from .manager import AgentManager

# Module-level default manager instance and convenience stop() function.
_default_manager: AgentManager = AgentManager()


def stop(*, install_signal_handlers: bool = False) -> None:
    """Gracefully stop the default AgentManager instance.

    Stops all running agents, runs registered shutdown hooks, and clears
    the registry. Pass ``install_signal_handlers=True`` to also catch
    SIGTERM/SIGINT (main thread only).
    """
    _default_manager.stop(install_signal_handlers=install_signal_handlers)


__all__ = [
    "Agent",
    "AgentStatus",
    "AgentType",
    "AgentManager",
    "AgentAlreadyRunningError",
    "AgentError",
    "AgentNotFoundError",
    "DuplicateAgentError",
    "stop",
]
