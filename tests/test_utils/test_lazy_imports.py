"""Tests for lightweight utility-package imports."""

from __future__ import annotations

import subprocess
import sys

_QT_ROOTS = "{'AnyQt', 'PyQt5', 'PyQt6', 'PySide6', 'pyqtgraph', 'Orange'}"


def test_core_modules_stay_qt_free():
    """The Qt-free workflow and utility modules must not pull in a Qt binding.

    ``benchmarks/core`` asserts the same invariant, but only for what that
    suite happens to import. This is the authoritative guard: a fresh
    interpreter with nothing else loaded.
    """
    code = (
        "import sys; "
        "import derzug.workflow.pipe, derzug.utils.spool, derzug.utils.sampling, "
        "derzug.utils.benchmarking; "
        f"leaked = {_QT_ROOTS} & {{n.split('.')[0] for n in sys.modules}}; "
        "assert not leaked, sorted(leaked)"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr


def test_utils_package_defers_heavy_widget_helpers():
    """Importing the utility namespace should not eagerly load widget machinery."""
    code = (
        "import sys; import derzug.utils; "
        "assert 'derzug.utils.code2widget' not in sys.modules; "
        "assert 'derzug.utils.display' not in sys.modules"
    )

    completed = subprocess.run(
        [sys.executable, "-c", code],
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == 0, completed.stderr
