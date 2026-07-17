"""Tests for the shared widget execution runtime."""

from __future__ import annotations

import threading

import pytest
from AnyQt.QtCore import QObject

from derzug.core.widget_runtime import (
    _SHARED_EXECUTOR,
    WidgetExecutionRequest,
    WidgetExecutionRuntime,
)


class _Harness:
    """Collect runtime callbacks for assertions."""

    def __init__(self, owner: QObject, *, dedicated_worker: bool = False) -> None:
        self.results: list[object] = []
        self.errors: list[Exception] = []
        self.empty_results = 0
        self.preflight_errors: list[Exception] = []
        self.worker_unavailable = 0
        self.runtime = WidgetExecutionRuntime(
            owner,
            execute_request=lambda request: request.execute(),
            apply_result=self.results.append,
            apply_error=self.errors.append,
            apply_empty_result=self._on_empty,
            handle_preflight_error=self.preflight_errors.append,
            handle_worker_unavailable=self._on_unavailable,
            dedicated_worker=dedicated_worker,
        )

    def _on_empty(self) -> None:
        self.empty_results += 1

    def _on_unavailable(self) -> None:
        self.worker_unavailable += 1


@pytest.fixture
def owner(qtbot):
    """Return a QObject owner for the runtime's Qt bridge."""
    obj = QObject()
    yield obj
    obj.deleteLater()


def _request(value: object):
    """Return a build_request callable producing an immediate result."""
    return lambda: WidgetExecutionRequest(execute=lambda: value)


def _blocking_request(
    started: threading.Event,
    release: threading.Event,
    value: object,
):
    """Return a build_request whose execution blocks until released."""

    def _execute() -> object:
        started.set()
        release.wait(timeout=5)
        return value

    return lambda: WidgetExecutionRequest(execute=_execute)


class TestDispatch:
    """Tests for WidgetExecutionRuntime.dispatch."""

    def test_result_applied(self, qtbot, owner):
        """A dispatched request delivers its result on the owner thread."""
        harness = _Harness(owner)
        harness.runtime.dispatch(_request("done"))
        qtbot.waitUntil(lambda: bool(harness.results), timeout=5000)
        assert harness.results == ["done"]
        assert harness.runtime.active_execution_token is None

    def test_running_execution_queues_latest_request(self, qtbot, owner):
        """Dispatch during a running execution queues only the newest request."""
        harness = _Harness(owner)
        started = threading.Event()
        release = threading.Event()
        harness.runtime.dispatch(_blocking_request(started, release, "a"))
        assert started.wait(timeout=5)
        b_ran = threading.Event()

        def _b_request():
            def _execute():
                b_ran.set()
                return "b"

            return WidgetExecutionRequest(execute=_execute)

        harness.runtime.dispatch(_b_request)
        harness.runtime.dispatch(_request("c"))
        release.set()
        qtbot.waitUntil(lambda: bool(harness.results), timeout=5000)
        # The running result is stale and the superseded queued request never
        # executes; only the latest queued request delivers a result.
        assert harness.results == ["c"]
        assert not b_ran.is_set()

    def test_never_runs_two_executions_concurrently(self, qtbot, owner):
        """One runtime never overlaps two executions even under redispatch."""
        harness = _Harness(owner)
        active = threading.Semaphore(1)
        overlapped = threading.Event()
        started = threading.Event()
        release = threading.Event()

        def _tracked_request(value, block: bool):
            def _execute():
                if not active.acquire(blocking=False):
                    overlapped.set()
                    return value
                try:
                    if block:
                        started.set()
                        release.wait(timeout=5)
                    return value
                finally:
                    active.release()

            return lambda: WidgetExecutionRequest(execute=_execute)

        harness.runtime.dispatch(_tracked_request("a", block=True))
        assert started.wait(timeout=5)
        harness.runtime.dispatch(_tracked_request("b", block=False))
        release.set()
        qtbot.waitUntil(lambda: bool(harness.results), timeout=5000)
        assert harness.results == ["b"]
        assert not overlapped.is_set()


class TestInvalidate:
    """Tests for WidgetExecutionRuntime.invalidate."""

    def test_invalidate_drops_pending_and_inflight(self, qtbot, owner):
        """Invalidation discards the running result and any queued request."""
        harness = _Harness(owner)
        started = threading.Event()
        release = threading.Event()
        harness.runtime.dispatch(_blocking_request(started, release, "a"))
        assert started.wait(timeout=5)
        harness.runtime.dispatch(_request("b"))
        harness.runtime.invalidate()
        release.set()
        qtbot.wait(100)
        assert harness.results == []
        assert harness.runtime.active_execution_token is None


class TestShutdown:
    """Tests for WidgetExecutionRuntime.shutdown."""

    def test_shutdown_drops_pending_request(self, qtbot, owner):
        """Shutdown discards queued requests and suppresses late results."""
        harness = _Harness(owner)
        started = threading.Event()
        release = threading.Event()
        harness.runtime.dispatch(_blocking_request(started, release, "a"))
        assert started.wait(timeout=5)
        harness.runtime.dispatch(_request("b"))
        harness.runtime.shutdown()
        release.set()
        qtbot.wait(100)
        assert harness.results == []
        assert harness.runtime.teardown_started

    def test_dedicated_worker_uses_private_executor(self, qtbot, owner):
        """Dedicated-worker runtimes never touch the shared executor."""
        harness = _Harness(owner, dedicated_worker=True)
        harness.runtime.dispatch(_request("done"))
        qtbot.waitUntil(lambda: bool(harness.results), timeout=5000)
        executor = harness.runtime._executor
        assert executor is not None
        assert executor is not _SHARED_EXECUTOR
        harness.runtime.shutdown()
        assert executor._shutdown
        assert harness.runtime._executor is None
