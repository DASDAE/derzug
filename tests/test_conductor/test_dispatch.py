"""Tests for the Conductor main-thread dispatcher."""

from __future__ import annotations

import threading

from AnyQt.QtCore import QThread
from derzug.conductor.dispatch import MainThreadDispatcher


def _run_in_worker(target):
    """Run ``target`` in a worker thread and return the created thread."""
    thread = threading.Thread(target=target)
    thread.start()
    return thread


def test_run_executes_on_the_main_thread(qapp, qtbot):
    """A call from a worker thread is marshalled onto the Qt main thread."""
    dispatcher = MainThreadDispatcher()
    main_thread = QThread.currentThread()
    out: dict[str, object] = {}

    def worker():
        out["ran_on"] = dispatcher.run(QThread.currentThread)
        out["value"] = dispatcher.run(lambda x: x + 1, 41)

    thread = _run_in_worker(worker)
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=3000)
    thread.join()

    assert out["ran_on"] is main_thread
    assert out["value"] == 42


def test_run_propagates_exceptions_to_the_caller(qapp, qtbot):
    """An exception raised on the main thread re-raises on the calling thread."""
    dispatcher = MainThreadDispatcher()
    out: dict[str, object] = {}

    def boom():
        raise ValueError("boom")

    def worker():
        try:
            dispatcher.run(boom)
        except ValueError as exc:
            out["error"] = str(exc)

    thread = _run_in_worker(worker)
    qtbot.waitUntil(lambda: not thread.is_alive(), timeout=3000)
    thread.join()

    assert out["error"] == "boom"


def test_run_is_direct_on_the_main_thread(qapp):
    """Calling from the main thread runs directly and does not deadlock."""
    dispatcher = MainThreadDispatcher()
    assert dispatcher.run(lambda: 5) == 5


def test_run_refuses_new_calls_after_stop(qapp):
    """A stopped dispatcher rejects calls instead of queueing them forever."""
    dispatcher = MainThreadDispatcher()
    dispatcher.stop()
    try:
        dispatcher.run(lambda: 5)
    except RuntimeError as exc:
        assert "stopped" in str(exc)
    else:
        raise AssertionError("expected RuntimeError after stop()")


def test_run_times_out_when_main_thread_is_blocked(qapp):
    """A worker call fails with TimeoutError when the main thread never services it."""
    dispatcher = MainThreadDispatcher(timeout=0.2)
    out: dict[str, object] = {}

    def worker():
        try:
            dispatcher.run(lambda: 5)
        except TimeoutError as exc:
            out["error"] = exc

    thread = _run_in_worker(worker)
    # Block the main thread in join(): the queued invocation is never serviced,
    # so the worker must time out rather than wait forever.
    thread.join()
    assert isinstance(out.get("error"), TimeoutError)


def test_timed_out_call_is_cancelled_before_main_thread_services_it(qapp):
    """A timed-out mutation must not execute later when the event loop resumes."""
    dispatcher = MainThreadDispatcher(timeout=0.2)
    mutations: list[str] = []

    def worker():
        try:
            dispatcher.run(mutations.append, "late")
        except TimeoutError:
            pass

    thread = _run_in_worker(worker)
    thread.join()  # keep the main thread blocked until the dispatch times out
    qapp.processEvents()  # now deliver the cancelled queued invocation
    assert mutations == []


def test_stop_releases_a_waiting_caller(qapp):
    """stop() unblocks a worker already waiting on the main thread."""
    import time

    dispatcher = MainThreadDispatcher(timeout=30.0)
    out: dict[str, object] = {}

    def worker():
        try:
            dispatcher.run(lambda: 5)
        except RuntimeError as exc:
            out["error"] = exc

    thread = _run_in_worker(worker)
    time.sleep(0.1)  # let the worker enter its wait
    dispatcher.stop()
    thread.join(timeout=3)
    assert not thread.is_alive()
    assert isinstance(out.get("error"), RuntimeError)
