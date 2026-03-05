"""AgentManager: CRUD and lifecycle management for Agent instances."""
from __future__ import annotations

from typing import Dict, List, Optional

from .agent import Agent, AgentStatus, AgentType
from .exceptions import AgentNotFoundError, DuplicateAgentError


class AgentManager:
    """Manages a registry of Agent instances.

    Agents are keyed by their unique agent_id. Within a manager, agent
    names must be unique — attempting to register a duplicate name raises
    DuplicateAgentError.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, Agent] = {}

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def register(self, agent: Agent) -> Agent:
        """Register an agent in the manager.

        Raises:
            DuplicateAgentError: If an agent with the same name already exists.
        """
        for existing in self._agents.values():
            if existing.name == agent.name:
                raise DuplicateAgentError(agent.name)
        self._agents[agent.agent_id] = agent
        return agent

    def get(self, agent_id: str) -> Agent:
        """Retrieve an agent by ID.

        Raises:
            AgentNotFoundError: If no agent with agent_id exists.
        """
        if agent_id not in self._agents:
            raise AgentNotFoundError(agent_id)
        return self._agents[agent_id]

    def remove(self, agent_id: str) -> None:
        """Remove an agent from the manager.

        Raises:
            AgentNotFoundError: If no agent with agent_id exists.
        """
        if agent_id not in self._agents:
            raise AgentNotFoundError(agent_id)
        del self._agents[agent_id]

    def list_agents(
        self,
        status: Optional[AgentStatus] = None,
        agent_type: Optional[AgentType] = None,
    ) -> List[Agent]:
        """Return agents, optionally filtered by status and/or type."""
        agents = list(self._agents.values())
        if status is not None:
            agents = [a for a in agents if a.status == status]
        if agent_type is not None:
            agents = [a for a in agents if a.agent_type == agent_type]
        return agents

    # ------------------------------------------------------------------
    # Lifecycle helpers
    # ------------------------------------------------------------------

    def start_agent(self, agent_id: str) -> Agent:
        """Start the agent identified by agent_id."""
        agent = self.get(agent_id)
        agent.start()
        return agent

    def stop_agent(self, agent_id: str) -> Agent:
        """Stop the agent identified by agent_id."""
        agent = self.get(agent_id)
        agent.stop()
        return agent

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    def count(self) -> dict:
        """Return counts of agents grouped by status, plus a total.

        Example return value::

            {"total": 3, "idle": 1, "running": 2, "stopped": 0, "error": 0}
        """
        counts: dict = {s.value: 0 for s in AgentStatus}
        for agent in self._agents.values():
            counts[agent.status.value] += 1
        counts["total"] = len(self._agents)
        return counts
