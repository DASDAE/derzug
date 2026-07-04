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
