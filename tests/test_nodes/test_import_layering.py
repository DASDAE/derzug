"""The layering guard: ``derzug.nodes`` and ``derzug.workflow`` stay Qt-free.

Each check runs in a fresh interpreter. The root ``tests/conftest.py`` boots a
``QApplication`` for the suite, so an in-process ``sys.modules`` assertion would
be meaningless here.
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


class TestNodeLayerIsQtFree:
    """Importing and using the node layer must never pull Qt in."""

    def test_registry_and_all_specs_import_qt_free(self):
        """Loading every discoverable node spec imports no Qt module."""
        result = run_isolated(
            """
            from derzug.nodes.registry import load_node_specs

            specs = load_node_specs()
            assert specs, "no node specs were discovered"
            for spec in specs:
                spec.params_schema()
                spec.view_schema()
            """
        )
        assert result.returncode == 0, result.stderr

    def test_default_tasks_build_qt_free(self):
        """Every spec's default task builds without importing Qt."""
        result = run_isolated(
            """
            from derzug.nodes.registry import load_node_specs

            for spec in load_node_specs():
                if spec.task_factory is None:
                    continue
                task = spec.build_task()
                task.resolved_scalar_input_variables()
                task.resolved_scalar_output_variables()
            """
        )
        assert result.returncode == 0, result.stderr

    def test_every_workflow_submodule_imports_qt_free(self):
        """Importing all of ``derzug.workflow`` imports no Qt module."""
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
        """The guard itself fails when something does import Qt."""
        result = run_isolated("import AnyQt.QtCore  # noqa: F401")
        assert result.returncode != 0
        assert "Qt leaked into the core layer" in result.stdout + result.stderr
