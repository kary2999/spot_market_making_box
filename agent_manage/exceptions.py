# Custom exception hierarchy for agent_manage operations


class AgentError(Exception):
    """Base exception for all agent-related errors."""


class AgentNotFoundError(AgentError):
    """Raised when a requested agent_id does not exist in the manager."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent '{agent_id}' not found")
        self.agent_id = agent_id


class DuplicateAgentError(AgentError):
    """Raised when registering an agent whose name is already taken."""

    def __init__(self, name: str) -> None:
        super().__init__(f"An agent named '{name}' already exists")
        self.name = name


class AgentAlreadyRunningError(AgentError, ValueError):
    """Raised when attempting to start an agent that is already running."""

    def __init__(self, agent_id: str) -> None:
        super().__init__(f"Agent '{agent_id}' is already running")
        self.agent_id = agent_id
