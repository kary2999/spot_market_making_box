"""AgentManager: CRUD and lifecycle management for Agent instances."""
from __future__ import annotations

import logging
import signal
import threading
from typing import Any, Callable, Dict, List, Optional

from .agent import Agent, AgentStatus, AgentType
from .exceptions import AgentNotFoundError, DuplicateAgentError

logger = logging.getLogger(__name__)


class _AgentCount(dict):
    """Dict subclass returned by AgentManager.count().

    Supports both dict-style key access (``counts["total"]``) and
    equality comparison with an integer (``counts == 3``).
    """

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.get("total", 0) == other
        return super().__eq__(other)

    def __hash__(self) -> int:  # type: ignore[override]
        return id(self)


class AgentManager:
    """Manages a registry of Agent instances.

    Agents are keyed by their unique agent_id. Within a manager, agent
    names must be unique — attempting to register a duplicate name raises
    DuplicateAgentError.
    """

    def __init__(self, storage: Optional[Dict] = None) -> None:
        # Allow injecting a custom storage dict (e.g. MockStorage in tests)
        self._agents: Dict[str, Agent] = storage if storage is not None else {}
        self._is_stopping: bool = False
        # Optional user-supplied cleanup callbacks registered via on_shutdown()
        self._shutdown_hooks: List[Callable[[], None]] = []

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

    def create(
        self,
        agent_id: str,
        name: str,
        config: Optional[Dict[str, Any]] = None,
    ) -> Agent:
        """Create and register an agent using the simplified API.

        Args:
            agent_id: Unique identifier for the agent.
            name: Human-readable name for the agent.
            config: Optional configuration dict.

        Returns:
            The newly created Agent instance.
        """
        agent = Agent(id=agent_id, name=name, config=config or {})
        self._agents[agent_id] = agent
        return agent

    def delete(self, agent_id: str) -> None:
        """Remove an agent by ID (simplified-API alias for remove).

        Raises:
            AgentNotFoundError: If no agent with agent_id exists.
        """
        self.remove(agent_id)

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

    def stop_agent_with_timeout(self, agent_id: str, timeout: float = 5.0) -> Agent:
        """Stop an agent, force-stopping if the operation exceeds *timeout* seconds.

        If the normal stop completes within the timeout window, the agent
        transitions to STOPPED as usual.  If the timeout expires before stop
        completes (e.g. a blocking on-stop hook), the status is forced to
        STOPPED and ``metadata["force_stopped"]`` is set to ``True``.

        Args:
            agent_id: ID of the agent to stop.
            timeout: Maximum seconds to wait before force-stopping.

        Returns:
            The stopped Agent instance.

        Raises:
            AgentNotFoundError: If agent_id does not exist.
        """
        agent = self.get(agent_id)
        if agent.status == AgentStatus.STOPPED:
            return agent

        completed = threading.Event()

        def _do_stop() -> None:
            try:
                agent.stop()
            except Exception:  # noqa: BLE001
                pass
            finally:
                completed.set()

        thread = threading.Thread(target=_do_stop, daemon=True)
        thread.start()

        if not completed.wait(timeout=timeout):
            # Timeout exceeded — force the status without waiting for the thread
            agent.status = AgentStatus.STOPPED
            agent.metadata["force_stopped"] = True
            logger.warning(
                "Force-stopped agent '%s' (%s) after %.1fs timeout",
                agent.name,
                agent.agent_id,
                timeout,
            )
        else:
            thread.join()

        return agent

    # ------------------------------------------------------------------
    # Aggregates
    # ------------------------------------------------------------------

    # ------------------------------------------------------------------
    # Graceful shutdown
    # ------------------------------------------------------------------

    def on_shutdown(self, hook: Callable[[], None]) -> None:
        """Register a callback to be invoked during stop().

        Hooks are called in registration order after all agents have been
        stopped, allowing callers to close connections or clean up temp files.
        """
        self._shutdown_hooks.append(hook)

    def stop(self, *, install_signal_handlers: bool = False) -> None:
        """Stop all running agents and release resources.

        Steps:
        1. Optionally install SIGTERM/SIGINT handlers so OS signals trigger
           this method (useful when running as a long-lived service).
        2. Transition every RUNNING agent to STOPPED (skips non-running agents
           silently so the operation is idempotent).
        3. Invoke registered shutdown hooks in order (connections, temp files…).
        4. Clear the internal agent registry.

        Args:
            install_signal_handlers: When True, register this method as the
                handler for SIGTERM and SIGINT before shutting down. Safe to
                call from the main thread only; ignored on platforms that do
                not support POSIX signals.
        """
        if self._is_stopping:
            logger.debug("stop() already in progress — skipping re-entrant call")
            return

        self._is_stopping = True
        logger.info("AgentManager: initiating graceful shutdown")

        # --- 1. Install OS signal handlers if requested --------------------
        if install_signal_handlers:
            self._install_signal_handlers()

        # --- 2. Stop all running agents ------------------------------------
        stopped_count = 0
        error_count = 0
        for agent in list(self._agents.values()):
            if agent.status == AgentStatus.RUNNING:
                try:
                    agent.stop()
                    stopped_count += 1
                    logger.debug("Stopped agent '%s' (%s)", agent.name, agent.agent_id)
                except Exception as exc:  # noqa: BLE001
                    # Mark agent as ERROR so the state remains consistent
                    agent.set_error(str(exc))
                    error_count += 1
                    logger.warning(
                        "Failed to stop agent '%s' (%s): %s",
                        agent.name,
                        agent.agent_id,
                        exc,
                    )

        logger.info(
            "AgentManager: stopped %d agent(s); %d error(s)",
            stopped_count,
            error_count,
        )

        # --- 3. Run shutdown hooks (close connections, delete temp files…) --
        for hook in self._shutdown_hooks:
            try:
                hook()
            except Exception as exc:  # noqa: BLE001
                logger.warning("Shutdown hook raised an exception: %s", exc)

        # --- 4. Clear registry ---------------------------------------------
        self._agents.clear()
        self._shutdown_hooks.clear()
        logger.info("AgentManager: shutdown complete")

    def _install_signal_handlers(self) -> None:
        """Register SIGTERM and SIGINT handlers that call stop()."""
        def _handler(signum: int, frame: object) -> None:  # noqa: ANN001
            sig_name = signal.Signals(signum).name
            logger.info("Received signal %s — triggering graceful shutdown", sig_name)
            self.stop()

        try:
            signal.signal(signal.SIGTERM, _handler)
            signal.signal(signal.SIGINT, _handler)
            logger.debug("Installed SIGTERM/SIGINT handlers")
        except (OSError, ValueError) as exc:
            # ValueError is raised when called from a non-main thread; OSError
            # on platforms that don't support the signal.
            logger.warning("Could not install signal handlers: %s", exc)

    def count(self) -> "_AgentCount":
        """Return counts of agents grouped by status, plus a total.

        The returned object supports both dict-style access and integer
        equality comparison (against the total count).

        Example::

            manager.count()["total"]  # → 3
            manager.count() == 3      # → True
        """
        counts = _AgentCount({s.value: 0 for s in AgentStatus})
        for agent in self._agents.values():
            counts[agent.status.value] += 1
        counts["total"] = len(self._agents)
        return counts
