"""Fixtures and invariants for the Qt-free benchmark suite."""

from __future__ import annotations

import os
import sys
from collections.abc import Iterator

import pytest

# _bench_tasks imports derzug, and this module is imported before
# pytest_configure records the Qt baseline below. Importing it lazily inside
# the fixtures keeps DerZug's own imports on the measured side of that
# snapshot, so the invariant can actually see a leak they introduce.

_QT_ROOTS = frozenset(
    {
        "AnyQt",
        "Orange",
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "orangecanvas",
        "orangewidget",
        "pyqtgraph",
    }
)

_QT_BASELINE: pytest.StashKey[frozenset[str]] = pytest.StashKey()


def _loaded_qt_roots() -> frozenset[str]:
    """Return the Qt root packages currently present in the import cache."""
    return frozenset({name.split(".")[0] for name in sys.modules} & _QT_ROOTS)


@pytest.hookimpl(trylast=True)
def pytest_configure(config: pytest.Config) -> None:
    """Record which Qt packages were already imported before collection.

    Plugins are configured before collection and ``pytest-qt`` imports a Qt
    binding from its own ``pytest_configure``. Those imports are not the
    suite's doing, so the invariant below compares against this baseline
    rather than against an empty set. ``trylast`` is required: conftest hooks
    would otherwise run before the plugin hooks and snapshot too early.
    """
    config.stash[_QT_BASELINE] = _loaded_qt_roots()


@pytest.fixture(scope="session", autouse=True)
def _assert_core_stays_qt_free(request: pytest.FixtureRequest) -> Iterator[None]:
    """Fail the core suite when its own code drags in a Qt binding.

    Skipped when the Qt tree was collected in the same run, since that suite
    legitimately imports Qt into the shared interpreter.
    """
    yield
    items = getattr(request.session, "items", ())
    qt_collected = any(
        "benchmarks/qt" in str(item.path).replace(os.sep, "/") for item in items
    )
    if qt_collected:
        return
    baseline = request.config.stash.get(_QT_BASELINE, frozenset())
    leaked = sorted(_loaded_qt_roots() - baseline)
    assert not leaked, f"core benchmarks imported Qt modules: {leaked}"


@pytest.fixture(scope="session")
def chain_pipe():
    """Return a 50-node linear pipe."""
    from _bench_tasks import build_chain

    return build_chain(50)


@pytest.fixture(scope="session")
def diamond_pipe():
    """Return a fan-out/fan-in pipe with 15 nodes per branch."""
    from _bench_tasks import build_diamond

    return build_diamond(15)


@pytest.fixture(scope="session")
def stream_pipe():
    """Return a producer/consumer pipe exercising the generator runtime."""
    from _bench_tasks import build_stream_pipe

    return build_stream_pipe()
