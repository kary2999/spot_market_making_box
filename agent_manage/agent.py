"""Agent entity model with AgentType enum and lifecycle state machine."""
from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Any, Callable, Optional


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class AgentType(str, Enum):
    CHAT = "chat"
    TASK = "task"
    MONITOR = "monitor"


class Agent:
    """Single AI Agent with lifecycle state machine.

    Supports two construction styles:

    Legacy style (agent_type required):
        Agent(name="bot", agent_type=AgentType.CHAT)

    Simple style (id and config):
        Agent(id="x", name="bot", config={})
    """

    def __init__(
        self,
        name: str,
        agent_type: AgentType = AgentType.CHAT,
        model: str = "claude-sonnet-4-6",
        agent_id: Optional[str] = None,
        status: AgentStatus = AgentStatus.IDLE,
        created_at: Optional[float] = None,
        metadata: Optional[dict[str, Any]] = None,
        # Simple-mode kwargs
        id: Optional[str] = None,
        config: Optional[dict[str, Any]] = None,
        _on_start: Optional[Callable] = None,
        _on_stop: Optional[Callable] = None,
    ) -> None:
        self.name = name
        self.agent_type = agent_type
        self.model = model
        self.status = status
        self.created_at = created_at if created_at is not None else time.time()
        self._on_start = _on_start
        self._on_stop = _on_stop

        # Determine construction mode
        if id is not None:
            self.agent_id = id
            self._simple_mode = True
        elif agent_id is not None:
            self.agent_id = agent_id
            self._simple_mode = False
        else:
            self.agent_id = str(uuid.uuid4())
            self._simple_mode = False

        # metadata / config share the same dict
        if config is not None:
            self.metadata = config
            self._simple_mode = True
        elif metadata is not None:
            self.metadata = metadata
        else:
            self.metadata = {}

    # ------------------------------------------------------------------
    # Simple-mode property aliases
    # ------------------------------------------------------------------

    @property
    def id(self) -> str:
        """Alias for agent_id used by the simplified API."""
        return self.agent_id

    @property
    def config(self) -> dict[str, Any]:
        """Alias for metadata used by the simplified API."""
        return self.metadata

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Transition agent to RUNNING.

        Raises:
            AgentAlreadyRunningError: If agent is already running.
            ValueError: If agent is in error state.
        """
        if self.status == AgentStatus.RUNNING:
            from .exceptions import AgentAlreadyRunningError
            raise AgentAlreadyRunningError(self.agent_id)
        if self.status == AgentStatus.ERROR:
            raise ValueError(
                f"Agent '{self.agent_id}' is in error state; call reset() first"
            )
        self.status = AgentStatus.RUNNING
        if self._on_start is not None:
            self._on_start(self)

    def stop(self) -> None:
        """Transition agent to STOPPED.

        Idempotent: calling stop() on an already-stopped agent is a no-op.

        Raises:
            ValueError: If agent is in a state other than RUNNING or STOPPED.
        """
        if self.status == AgentStatus.STOPPED:
            return
        if self.status != AgentStatus.RUNNING:
            raise ValueError(f"Agent '{self.agent_id}' is not running")
        self.status = AgentStatus.STOPPED
        if self._on_stop is not None:
            self._on_stop(self)

    def reset(self) -> None:
        """Reset agent back to IDLE, clearing any error or stopped state."""
        self.status = AgentStatus.IDLE

    def set_error(self, message: str = "") -> None:
        """Transition agent to ERROR and record the error message."""
        self.status = AgentStatus.ERROR
        if message:
            self.metadata["error"] = message
            if self._simple_mode:
                # Simple-mode callers check config["last_error"]
                self.metadata["last_error"] = message

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize agent to a plain dictionary (suitable for JSON output)."""
        if self._simple_mode:
            return {
                "id": self.agent_id,
                "name": self.name,
                "config": self.metadata,
                "status": self.status.value,
                "created_at": self.created_at,
            }
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "agent_type": self.agent_type.value,
            "model": self.model,
            "status": self.status.value,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
