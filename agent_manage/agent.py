"""Agent entity model with AgentType enum and lifecycle state machine."""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class AgentStatus(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class AgentType(str, Enum):
    CHAT = "chat"
    TASK = "task"
    MONITOR = "monitor"


@dataclass
class Agent:
    """Single AI Agent with lifecycle state machine.

    Attributes:
        name: Human-readable agent name (must be unique within a manager).
        agent_type: Functional role of the agent.
        model: Underlying LLM model identifier.
        agent_id: Auto-generated UUID, unique per instance.
        status: Current lifecycle status.
        created_at: Unix timestamp of creation.
        metadata: Arbitrary key-value store (e.g. error messages).
    """

    name: str
    agent_type: AgentType
    model: str = "claude-sonnet-4-6"
    agent_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    status: AgentStatus = AgentStatus.IDLE
    created_at: float = field(default_factory=time.time)
    metadata: dict[str, Any] = field(default_factory=dict)

    # ------------------------------------------------------------------
    # State machine
    # ------------------------------------------------------------------

    def start(self) -> None:
        """Transition agent to RUNNING.

        Raises:
            ValueError: If agent is already running or in error state.
        """
        if self.status == AgentStatus.RUNNING:
            raise ValueError(f"Agent '{self.agent_id}' is already running")
        if self.status == AgentStatus.ERROR:
            raise ValueError(
                f"Agent '{self.agent_id}' is in error state; call reset() first"
            )
        self.status = AgentStatus.RUNNING

    def stop(self) -> None:
        """Transition agent to STOPPED.

        Raises:
            ValueError: If agent is not currently running.
        """
        if self.status != AgentStatus.RUNNING:
            raise ValueError(f"Agent '{self.agent_id}' is not running")
        self.status = AgentStatus.STOPPED

    def reset(self) -> None:
        """Reset agent back to IDLE, clearing any error or stopped state."""
        self.status = AgentStatus.IDLE

    def set_error(self, message: str = "") -> None:
        """Transition agent to ERROR and record the error message in metadata."""
        self.status = AgentStatus.ERROR
        if message:
            self.metadata["error"] = message

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize agent to a plain dictionary (suitable for JSON output)."""
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "agent_type": self.agent_type.value,
            "model": self.model,
            "status": self.status.value,
            "created_at": self.created_at,
            "metadata": self.metadata,
        }
