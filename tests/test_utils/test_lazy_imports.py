"""Tests for lightweight utility-package imports."""

from __future__ import annotations

import subprocess
import sys


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
