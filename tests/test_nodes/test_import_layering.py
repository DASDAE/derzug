"""The one layering check `tach` cannot make: transitively imported Qt.

`tach check` (see ``tach.toml``) owns the layering rule itself — it reads the
first-party import graph statically, so it catches lazy imports buried in
function bodies and direction violations between two Qt-free layers, neither of
which a runtime probe can see.

What it cannot see is a *third-party* package that pulls Qt in behind its own
import. Nothing in ``tach.toml`` can express "the node layer must not end up
with PyQt6 in ``sys.modules``", because to tach that import belongs to some
other distribution entirely. So one runtime assertion stays: import the node
layer in a fresh interpreter and look at what actually loaded.

Fresh interpreter because the root ``tests/conftest.py`` boots a
``QApplication`` for the whole suite; an in-process check would always pass.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

QT_ROOTS = (
    "AnyQt",
    "Orange",
    "PyQt5",
    "PyQt6",
    "PySide2",
    "PySide6",
    "orangecanvas",
    "orangewidget",
    "pyqtgraph",
)

_ASSERT_NO_QT = f"""
    import sys

    qt_roots = {QT_ROOTS!r}
    leaked = sorted({{
        name for name in sys.modules if name.split(".")[0] in qt_roots
    }})
    if leaked:
        raise SystemExit("Qt leaked into the core layer: " + ", ".join(leaked))
"""


def run_isolated(body: str) -> subprocess.CompletedProcess:
    """Run one snippet in a fresh interpreter and return the completed process."""
    script = textwrap.dedent(body) + textwrap.dedent(_ASSERT_NO_QT)
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        check=False,
    )


class TestNoTransitiveQt:
    """Loading and running the node layer must not pull Qt in by any route."""

    def test_building_every_node_stays_qt_free(self):
        """Discover every spec, generate its schemas, and build its task.

        Deliberately exercises the layer rather than merely importing it: a
        dependency that imports Qt only on first use would otherwise pass.
        """
        result = run_isolated(
            """
            from derzug.nodes.registry import load_node_specs

            specs = load_node_specs()
            assert specs, "no node specs were discovered"
            for spec in specs:
                spec.params_schema()
                spec.view_schema()
                if spec.task_factory is None:
                    continue
                task = spec.build_task()
                task.resolved_scalar_input_variables()
                task.resolved_scalar_output_variables()
            """
        )
        assert result.returncode == 0, result.stderr

    def test_importing_every_workflow_submodule_stays_qt_free(self):
        """Importing all of ``derzug.workflow`` pulls in no Qt module."""
        result = run_isolated(
            """
            import importlib
            import pkgutil

            import derzug.workflow

            for info in pkgutil.iter_modules(derzug.workflow.__path__):
                importlib.import_module(f"derzug.workflow.{info.name}")
            """
        )
        assert result.returncode == 0, result.stderr

    def test_guard_detects_a_real_leak(self):
        """The probe itself fails when something does import Qt."""
        result = run_isolated("import AnyQt.QtCore  # noqa: F401")
        assert result.returncode != 0
        assert "Qt leaked into the core layer" in result.stdout + result.stderr
