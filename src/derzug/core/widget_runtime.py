"""Shared async execution runtime for widget-backed workflow execution."""

from __future__ import annotations

import os
from collections.abc import Callable
from concurrent.futures import CancelledError, Future, ThreadPoolExecutor
from dataclasses import dataclass
from threading import RLock

from AnyQt.QtCore import QObject, Signal

from derzug.workflow import Pipe, Task

_SHARED_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(2, min(4, os.cpu_count() or 2)),
    thread_name_prefix="DerZugWorker",
)

# Widgets running unbounded or untrusted work (arbitrary user scripts) execute
# on this separate process-global pool so a hung task cannot starve the general
# widget work on the shared pool. Both pools are long-lived singletons cleaned
# up once at interpreter exit; worker threads spawn lazily on first submit.
_ISOLATED_EXECUTOR = ThreadPoolExecutor(
    max_workers=max(2, min(4, os.cpu_count() or 2)),
    thread_name_prefix="DerZugIsolatedWorker",
)


@dataclass(frozen=True)
class WidgetExecutionRequest:
    """Pure execution request captured on the main thread for worker execution."""

    workflow_obj: Task | Pipe | None = None
    input_values: dict[str, object] | None = None
    output_names: tuple[str, ...] = ()
    execute: Callable[[], object] | None = None


class _AsyncExecutionBridge(QObject):
    """Marshal worker completions back to the widget thread."""

    result_ready = Signal(int, int, object)
    error_ready = Signal(int, int, object)


class _CompletionTarget:
    """Synchronize worker delivery with QObject teardown."""

    def __init__(self, bridge: _AsyncExecutionBridge) -> None:
        self._bridge: _AsyncExecutionBridge | None = bridge
        self._lock = RLock()

    def detach(self) -> None:
        """Prevent future worker callbacks from touching the Qt bridge."""
        with self._lock:
            self._bridge = None

    def emit_result(self, generation: int, token: int, result: object) -> None:
        """Emit one result while teardown cannot invalidate the bridge."""
        with self._lock:
            bridge = self._bridge
            if bridge is None:
                return
            try:
                bridge.result_ready.emit(generation, token, result)
            except RuntimeError:
                return

    def emit_error(self, generation: int, token: int, exc: Exception) -> None:
        """Emit one error while teardown cannot invalidate the bridge."""
        with self._lock:
            bridge = self._bridge
            if bridge is None:
                return
            try:
                bridge.error_ready.emit(generation, token, exc)
            except RuntimeError:
                return


class WidgetExecutionRuntime:
    """Own worker-thread execution, lifecycle, and stale-result suppression."""

    def __init__(
        self,
        owner: QObject,
        *,
        execute_request: Callable[[WidgetExecutionRequest], object],
        apply_result: Callable[[object], None],
        apply_error: Callable[[Exception], None],
        apply_empty_result: Callable[[], None],
        handle_preflight_error: Callable[[Exception], None],
        handle_worker_unavailable: Callable[[], None],
        dedicated_worker: bool = False,
    ) -> None:
        self._execute_request = execute_request
        self._apply_result = apply_result
        self._apply_error = apply_error
        self._apply_empty_result = apply_empty_result
        self._handle_preflight_error = handle_preflight_error
        self._handle_worker_unavailable = handle_worker_unavailable
        self._bridge = _AsyncExecutionBridge(owner)
        self._bridge.result_ready.connect(self._on_result_ready)
        self._bridge.error_ready.connect(self._on_error_ready)
        self._completion_target = _CompletionTarget(self._bridge)
        # Dedicated-worker runtimes isolate unbounded work (arbitrary user
        # scripts) on a separate process-global pool so a hung task can never
        # occupy a shared worker needed by other widgets.
        self._executor: ThreadPoolExecutor | None = (
            _ISOLATED_EXECUTOR if dedicated_worker else _SHARED_EXECUTOR
        )
        self._future: Future | None = None
        self._pending_build_request: (
            Callable[[], WidgetExecutionRequest | None] | None
        ) = None
        self._execution_generation = 0
        self._latest_execution_token = 0
        self._active_execution_token: int | None = None
        self._teardown_started = False

    @property
    def active_execution_token(self) -> int | None:
        """Return the currently active execution token, if any."""
        return self._active_execution_token

    @property
    def teardown_started(self) -> bool:
        """Return True once shutdown has begun."""
        return self._teardown_started

    def dispatch(
        self,
        build_request: Callable[[], WidgetExecutionRequest | None],
    ) -> None:
        """Build and dispatch one execution request to the worker."""
        if self._teardown_started:
            return
        future = self._future
        if future is not None and not future.done() and not future.cancel():
            # The current future is already running and cannot be cancelled.
            # Queue this request (latest wins) so at most one execution per
            # widget is ever in flight, and mark the running execution stale
            # so its late result is discarded on arrival.
            self._latest_execution_token += 1
            self._active_execution_token = self._latest_execution_token
            self._pending_build_request = build_request
            return
        self._pending_build_request = None
        try:
            request = build_request()
        except Exception as exc:
            if self._teardown_started:
                return
            self._invalidate_current_execution()
            self._handle_preflight_error(exc)
            return
        if request is None:
            if self._teardown_started:
                return
            self._invalidate_current_execution()
            self._apply_empty_result()
            return
        executor = self._executor
        if executor is None or self._teardown_started:
            self._handle_worker_unavailable()
            return

        generation = self._execution_generation
        self._latest_execution_token += 1
        token = self._latest_execution_token
        self._active_execution_token = token
        completion_target = self._completion_target

        def _done_callback(
            done_future: Future,
            *,
            run_generation: int,
            run_token: int,
        ) -> None:
            try:
                result = done_future.result()
            except CancelledError:
                return
            except Exception as exc:  # pragma: no cover
                completion_target.emit_error(run_generation, run_token, exc)
                return
            completion_target.emit_result(run_generation, run_token, result)

        self._future = executor.submit(self._execute_request, request)
        self._future.add_done_callback(
            lambda done_future, run_generation=generation, run_token=token: (
                _done_callback(
                    done_future,
                    run_generation=run_generation,
                    run_token=run_token,
                )
            )
        )

    def invalidate(self) -> None:
        """Discard any queued or in-flight execution without applying results.

        Late worker completions for previously dispatched requests are
        suppressed; a request queued behind a running execution is dropped.
        """
        self._invalidate_current_execution()

    def _invalidate_current_execution(self) -> None:
        """Cancel and release the current future, making late delivery stale."""
        self._pending_build_request = None
        self._latest_execution_token += 1
        self._active_execution_token = None
        future = self._future
        if future is not None and not future.done() and not future.cancel():
            # Still running and uncancellable: keep tracking the future so
            # dispatch keeps queueing behind it; its result is now stale.
            return
        self._future = None

    def shutdown(self) -> None:
        """Invalidate queued completions without blocking the GUI thread."""
        self._teardown_started = True
        self._execution_generation += 1
        self._completion_target.detach()
        self._pending_build_request = None
        future = self._future
        if future is not None and not future.done():
            future.cancel()
        self._future = None
        # The executors are process-global singletons shared across widgets, so
        # only detach this runtime from its pool; never shut the pool down.
        self._executor = None
        self._active_execution_token = None

    def _run_pending_dispatch(self) -> bool:
        """Dispatch the queued request now that the worker slot is free."""
        pending = self._pending_build_request
        if pending is None:
            return False
        self._pending_build_request = None
        self.dispatch(pending)
        return True

    def _on_result_ready(self, generation: int, token: int, result: object) -> None:
        """Apply the newest worker result on the widget thread."""
        if self._teardown_started:
            return
        if generation != self._execution_generation:
            return
        # A queued request supersedes this completion: the finished future is
        # done, so dispatching now submits immediately with fresh state.
        if self._run_pending_dispatch():
            return
        if token != self._latest_execution_token:
            return
        self._future = None
        self._active_execution_token = None
        self._apply_result(result)

    def _on_error_ready(
        self,
        generation: int,
        token: int,
        exc: Exception,
    ) -> None:
        """Apply the newest worker exception on the widget thread."""
        if self._teardown_started:
            return
        if generation != self._execution_generation:
            return
        if self._run_pending_dispatch():
            return
        if token != self._latest_execution_token:
            return
        self._future = None
        self._active_execution_token = None
        self._apply_error(exc)
