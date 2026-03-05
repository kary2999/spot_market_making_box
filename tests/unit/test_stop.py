"""Unit tests for the stop feature.

Covers:
1. Normal stop flow (Agent.stop / AgentManager.stop_agent / AgentManager.stop)
2. Stop when agent is executing a task (RUNNING state with concurrent access)
3. Idempotency of repeated stop calls
4. Timeout force-stop logic (AgentManager.stop_agent_with_timeout)
"""
from __future__ import annotations

import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from agent_manage import Agent, AgentManager, AgentStatus, AgentType
from agent_manage.exceptions import AgentNotFoundError


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_running_agent(name: str = "worker", agent_type: AgentType = AgentType.TASK) -> Agent:
    """Return an Agent already in RUNNING state."""
    agent = Agent(name=name, agent_type=agent_type)
    agent.start()
    return agent


def _register_running(manager: AgentManager, name: str = "worker") -> Agent:
    """Register a RUNNING agent in the manager and return it."""
    agent = Agent(name=name, agent_type=AgentType.TASK)
    manager.register(agent)
    manager.start_agent(agent.agent_id)
    return agent


# ===========================================================================
# Scenario 1: Normal stop flow
# ===========================================================================

class TestNormalStop:
    """Agent.stop() and AgentManager.stop_agent() happy-path behaviour."""

    def test_agent_stop_transitions_to_stopped(self):
        agent = _make_running_agent()
        agent.stop()
        assert agent.status == AgentStatus.STOPPED

    def test_agent_stop_returns_none(self):
        agent = _make_running_agent()
        result = agent.stop()
        assert result is None

    def test_manager_stop_agent_returns_agent(self, manager, chat_agent):
        manager.register(chat_agent)
        manager.start_agent(chat_agent.agent_id)
        result = manager.stop_agent(chat_agent.agent_id)
        assert result is chat_agent

    def test_manager_stop_agent_transitions_to_stopped(self, manager, chat_agent):
        manager.register(chat_agent)
        manager.start_agent(chat_agent.agent_id)
        manager.stop_agent(chat_agent.agent_id)
        assert chat_agent.status == AgentStatus.STOPPED

    def test_manager_stop_nonexistent_raises(self, manager):
        with pytest.raises(AgentNotFoundError):
            manager.stop_agent("no-such-id")

    def test_manager_stop_all_stops_every_running_agent(self, manager):
        agents = [_register_running(manager, name=f"agent-{i}") for i in range(3)]
        manager.stop()
        # After stop() the registry is cleared; check states before clearing
        # (we captured the agent refs above)
        for agent in agents:
            assert agent.status == AgentStatus.STOPPED

    def test_manager_stop_clears_registry(self, manager):
        _register_running(manager, name="a")
        manager.stop()
        assert manager.list_agents() == []

    def test_manager_stop_runs_shutdown_hooks(self, manager):
        hook = MagicMock()
        manager.on_shutdown(hook)
        manager.stop()
        hook.assert_called_once()

    def test_manager_stop_skips_non_running_agents(self, manager):
        idle = Agent(name="idle-bot", agent_type=AgentType.CHAT)
        manager.register(idle)
        # Should not raise even though the agent is not RUNNING
        manager.stop()
        # idle agent is left in its original state before registry is cleared
        assert idle.status == AgentStatus.IDLE


# ===========================================================================
# Scenario 2: Stop while agent is executing a task
# ===========================================================================

class TestStopWhileExecuting:
    """Stop an agent while it is actively working in a background thread."""

    def test_stop_interrupts_running_task(self):
        """Background task detects STOPPED status and exits cleanly."""
        agent = _make_running_agent()
        task_observed_stop = threading.Event()

        def background_task() -> None:
            while agent.status == AgentStatus.RUNNING:
                time.sleep(0.005)
            task_observed_stop.set()

        thread = threading.Thread(target=background_task, daemon=True)
        thread.start()

        # Small delay so the task loop is definitely running
        time.sleep(0.01)
        agent.stop()

        assert task_observed_stop.wait(timeout=1.0), "Background task never saw STOPPED"
        assert agent.status == AgentStatus.STOPPED

    def test_stop_via_manager_while_task_runs(self, manager):
        """manager.stop_agent() works while a task monitors the agent status."""
        agent = _register_running(manager, name="task-runner")
        stopped_event = threading.Event()

        def monitor() -> None:
            while agent.status == AgentStatus.RUNNING:
                time.sleep(0.005)
            stopped_event.set()

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()

        time.sleep(0.01)
        manager.stop_agent(agent.agent_id)

        assert stopped_event.wait(timeout=1.0)
        assert agent.status == AgentStatus.STOPPED

    def test_concurrent_stop_calls_are_safe(self):
        """Multiple threads calling stop() concurrently must not corrupt state."""
        agent = _make_running_agent()
        errors: list[Exception] = []

        def try_stop() -> None:
            try:
                agent.stop()
            except ValueError:
                # Only the first thread succeeds; others raise ValueError — that's fine
                pass
            except Exception as exc:
                errors.append(exc)

        threads = [threading.Thread(target=try_stop) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        assert errors == [], f"Unexpected exceptions: {errors}"
        assert agent.status == AgentStatus.STOPPED


# ===========================================================================
# Scenario 3: Idempotency of repeated stop calls
# ===========================================================================

class TestStopIdempotency:
    """Repeated stop calls must not raise and must leave agent in STOPPED."""

    def test_double_stop_on_agent_is_noop(self):
        agent = _make_running_agent()
        agent.stop()
        agent.stop()  # second call — must be a no-op
        assert agent.status == AgentStatus.STOPPED

    def test_triple_stop_on_agent_is_noop(self):
        agent = _make_running_agent()
        for _ in range(3):
            agent.stop()
        assert agent.status == AgentStatus.STOPPED

    def test_stop_already_stopped_does_not_raise(self):
        agent = _make_running_agent()
        agent.stop()
        try:
            agent.stop()
        except Exception as exc:
            pytest.fail(f"Second stop() raised unexpectedly: {exc}")

    def test_manager_stop_is_idempotent(self, manager):
        """AgentManager.stop() called twice must not raise."""
        _register_running(manager, name="alpha")
        manager.stop()
        manager.stop()  # second call — guarded by _is_stopping flag

    def test_manager_stop_hooks_called_only_once(self, manager):
        """Shutdown hooks must NOT be invoked on the second stop() call."""
        hook = MagicMock()
        manager.on_shutdown(hook)
        _register_running(manager, name="beta")
        manager.stop()
        manager.stop()
        hook.assert_called_once()

    def test_manager_stop_agent_idempotent_after_stop(self, manager):
        """stop_agent() on an already-stopped agent (idempotent Agent.stop)."""
        agent = _register_running(manager, name="gamma")
        manager.stop_agent(agent.agent_id)
        manager.stop_agent(agent.agent_id)  # Agent.stop is a no-op for STOPPED
        assert agent.status == AgentStatus.STOPPED


# ===========================================================================
# Scenario 4: Timeout force-stop logic
# ===========================================================================

class TestStopWithTimeout:
    """AgentManager.stop_agent_with_timeout() — normal and forced paths."""

    def test_normal_stop_within_timeout(self, manager):
        agent = _register_running(manager, name="quick")
        result = manager.stop_agent_with_timeout(agent.agent_id, timeout=2.0)
        assert result.status == AgentStatus.STOPPED
        assert result.metadata.get("force_stopped") is not True

    def test_already_stopped_agent_is_returned_immediately(self, manager):
        agent = _register_running(manager, name="done")
        manager.stop_agent(agent.agent_id)  # stop first
        result = manager.stop_agent_with_timeout(agent.agent_id, timeout=1.0)
        assert result.status == AgentStatus.STOPPED

    def test_force_stop_sets_metadata_flag(self, manager):
        """When timeout elapses before stop completes, force_stopped is flagged."""
        agent = _register_running(manager, name="slow")

        # Patch threading.Event.wait to always return False (timeout expired)
        with patch("threading.Event.wait", return_value=False):
            result = manager.stop_agent_with_timeout(agent.agent_id, timeout=0.001)

        assert result.status == AgentStatus.STOPPED
        assert result.metadata.get("force_stopped") is True

    def test_force_stop_transitions_agent_to_stopped(self, manager):
        agent = _register_running(manager, name="frozen")

        with patch("threading.Event.wait", return_value=False):
            manager.stop_agent_with_timeout(agent.agent_id, timeout=0.001)

        assert agent.status == AgentStatus.STOPPED

    def test_timeout_stop_nonexistent_agent_raises(self, manager):
        with pytest.raises(AgentNotFoundError):
            manager.stop_agent_with_timeout("ghost-id", timeout=1.0)

    def test_stop_completes_before_short_timeout(self, manager):
        """Verify normal path succeeds when timeout is tight but sufficient."""
        agent = _register_running(manager, name="nimble")
        # Agent.stop() is synchronous and near-instant; even 0.5 s is ample
        result = manager.stop_agent_with_timeout(agent.agent_id, timeout=0.5)
        assert result.status == AgentStatus.STOPPED

    def test_force_stop_does_not_block_indefinitely(self, manager):
        """Ensure the method returns promptly even if the inner thread hangs."""
        agent = _register_running(manager, name="hanging")

        start = time.monotonic()
        with patch("threading.Event.wait", return_value=False):
            manager.stop_agent_with_timeout(agent.agent_id, timeout=0.1)
        elapsed = time.monotonic() - start

        # With mocked wait the call should return almost instantly
        assert elapsed < 1.0


# ===========================================================================
# Scenario 5: Module-level stop() exported from agent_manage
# ===========================================================================

class TestModuleLevelStop:
    """agent_manage.stop() delegates to the default manager instance."""

    def test_stop_is_callable(self):
        import agent_manage
        assert callable(agent_manage.stop)

    def test_stop_is_in_all(self):
        import agent_manage
        assert "stop" in agent_manage.__all__

    def test_stop_calls_default_manager_stop(self):
        import agent_manage
        with patch.object(agent_manage._default_manager, "stop") as mock_stop:
            agent_manage.stop()
        mock_stop.assert_called_once_with(install_signal_handlers=False)

    def test_stop_passes_install_signal_handlers_flag(self):
        import agent_manage
        with patch.object(agent_manage._default_manager, "stop") as mock_stop:
            agent_manage.stop(install_signal_handlers=True)
        mock_stop.assert_called_once_with(install_signal_handlers=True)


# ===========================================================================
# Scenario 6: Signal handler installation
# ===========================================================================

class TestSignalHandlers:
    """_install_signal_handlers() registers SIGTERM/SIGINT on main thread."""

    def test_install_signal_handlers_sets_sigterm(self, manager):
        import signal as _signal
        with patch("signal.signal") as mock_signal:
            manager._install_signal_handlers()
        calls = [c.args[0] for c in mock_signal.call_args_list]
        assert _signal.SIGTERM in calls

    def test_install_signal_handlers_sets_sigint(self, manager):
        import signal as _signal
        with patch("signal.signal") as mock_signal:
            manager._install_signal_handlers()
        calls = [c.args[0] for c in mock_signal.call_args_list]
        assert _signal.SIGINT in calls

    def test_stop_with_install_signal_handlers_true(self, manager):
        """stop(install_signal_handlers=True) must call _install_signal_handlers."""
        with patch.object(manager, "_install_signal_handlers") as mock_install:
            manager.stop(install_signal_handlers=True)
        mock_install.assert_called_once()

    def test_stop_without_install_signal_handlers(self, manager):
        """stop(install_signal_handlers=False) must NOT call _install_signal_handlers."""
        with patch.object(manager, "_install_signal_handlers") as mock_install:
            manager.stop(install_signal_handlers=False)
        mock_install.assert_not_called()

    def test_install_signal_handlers_tolerates_oserror(self, manager):
        """OSError from signal.signal (unsupported platform) must not propagate."""
        with patch("signal.signal", side_effect=OSError("not supported")):
            manager._install_signal_handlers()  # should not raise

    def test_install_signal_handlers_tolerates_valueerror(self, manager):
        """ValueError raised from a non-main thread must not propagate."""
        with patch("signal.signal", side_effect=ValueError("not main thread")):
            manager._install_signal_handlers()  # should not raise

    def test_signal_handler_triggers_stop(self, manager):
        """The installed handler must call manager.stop() when invoked."""
        import signal as _signal
        captured = {}

        def fake_signal(signum, handler):
            captured[signum] = handler

        with patch("signal.signal", side_effect=fake_signal):
            manager._install_signal_handlers()

        with patch.object(manager, "stop") as mock_stop:
            handler = captured[_signal.SIGTERM]
            handler(_signal.SIGTERM, None)
        mock_stop.assert_called_once()


# ===========================================================================
# Scenario 7: Error handling during shutdown
# ===========================================================================

class TestShutdownErrorHandling:
    """Errors in hooks or agent.stop() must not abort the full shutdown."""

    def test_failing_hook_does_not_abort_shutdown(self, manager):
        """A hook that raises must not prevent subsequent hooks from running."""
        good_hook = MagicMock()
        bad_hook = MagicMock(side_effect=RuntimeError("boom"))

        manager.on_shutdown(bad_hook)
        manager.on_shutdown(good_hook)
        manager.stop()  # must not raise

        good_hook.assert_called_once()

    def test_failing_hook_registry_still_cleared(self, manager):
        manager.on_shutdown(MagicMock(side_effect=RuntimeError("boom")))
        _register_running(manager, name="x")
        manager.stop()
        assert manager.list_agents() == []

    def test_agent_stop_raises_transitions_to_error(self, manager):
        """If agent.stop() raises, the agent is marked ERROR, not left RUNNING."""
        agent = _register_running(manager, name="buggy")
        with patch.object(agent, "stop", side_effect=RuntimeError("stop failed")):
            manager.stop()
        assert agent.status == AgentStatus.ERROR

    def test_agent_stop_error_does_not_abort_other_agents(self, manager):
        """Failure stopping one agent must not prevent others from stopping."""
        good = _register_running(manager, name="good")
        buggy = _register_running(manager, name="buggy")
        with patch.object(buggy, "stop", side_effect=RuntimeError("oops")):
            manager.stop()
        assert good.status == AgentStatus.STOPPED

    def test_multiple_hooks_all_called_despite_errors(self, manager):
        """All hooks are attempted even when earlier ones fail."""
        hooks = [MagicMock(side_effect=RuntimeError("err")) for _ in range(3)]
        for h in hooks:
            manager.on_shutdown(h)
        manager.stop()
        for h in hooks:
            h.assert_called_once()


# ===========================================================================
# Scenario 8: Re-entrancy guard (_is_stopping flag)
# ===========================================================================

class TestReentrancyGuard:
    """stop() must detect and skip a second concurrent/nested invocation."""

    def test_is_stopping_flag_set_during_stop(self, manager):
        """_is_stopping becomes True as soon as stop() is entered."""
        observed: list[bool] = []

        def hook():
            observed.append(manager._is_stopping)

        manager.on_shutdown(hook)
        manager.stop()
        assert observed == [True]

    def test_reentrant_stop_from_hook_is_noop(self, manager):
        """A hook that calls manager.stop() again must not recurse."""
        call_count = 0

        def reentrant_hook():
            nonlocal call_count
            call_count += 1
            manager.stop()  # re-entrant call — must be skipped

        manager.on_shutdown(reentrant_hook)
        manager.stop()
        assert call_count == 1  # hook ran exactly once

    def test_second_stop_after_first_completes_is_noop(self, manager):
        """After stop() finishes, a second call should be a no-op (guard stays set)."""
        hook = MagicMock()
        manager.on_shutdown(hook)
        manager.stop()
        manager.stop()  # guard is still True
        hook.assert_called_once()
