"""Benchmarks for the cost of executing DerZug module bodies.

Scope note: only ``derzug.*`` entries are dropped from the import cache, so
these benchmarks measure DerZug's *own* module-body cost with third-party
dependencies already resolved. A newly added heavy third-party import would
only cost on the first round, which pytest-codspeed discards as warmup — the
guard for that invariant is the subprocess assertion in
``tests/test_utils/test_lazy_imports.py``, not this file.
"""

from __future__ import annotations

import importlib
import sys

import pytest

_TARGETS = ("derzug.workflow.pipe", "derzug.utils.spool", "derzug.cli")


def _derzug_modules() -> list[str]:
    """Return the DerZug entries currently in the import cache."""
    return [
        name for name in sys.modules if name == "derzug" or name.startswith("derzug.")
    ]


def _reimport(target: str) -> None:
    """Re-execute one DerZug module tree with the import cache dropped.

    The original entries are restored exactly afterwards -- every DerZug key
    created by the re-import is dropped, not merely overlaid -- so the freshly
    built classes never leak into other benchmarks. Two distinct ``Task``
    classes alive in one process would break every downstream ``isinstance``
    check.

    The cache bookkeeping costs a few hundred microseconds against module
    bodies measured in milliseconds, so it dilutes but does not mask a real
    regression.
    """
    saved = {name: sys.modules[name] for name in _derzug_modules()}
    for name in saved:
        del sys.modules[name]
    try:
        importlib.import_module(target)
    finally:
        for name in _derzug_modules():
            del sys.modules[name]
        sys.modules.update(saved)


@pytest.fixture(scope="module", autouse=True)
def _prime_imports() -> None:
    """Import every target once so bytecode compilation stays out of the region."""
    for target in _TARGETS:
        importlib.import_module(target)


class TestImportBenchmarks:
    """Benchmarks for DerZug module-body execution cost."""

    @pytest.mark.benchmark
    def test_import_workflow(self):
        """Re-execute the workflow package's module bodies."""
        _reimport("derzug.workflow.pipe")

    @pytest.mark.benchmark
    def test_import_spool_utils(self):
        """Re-execute the spool-utility module body."""
        _reimport("derzug.utils.spool")
