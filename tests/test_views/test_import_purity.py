"""Guard: importing the views layer must not mutate global orangecanvas state.

DerZug's canvas monkeypatches are installed lazily at app-window startup via
``ensure_canvas_patches_installed``. Importing ``derzug.views.orange`` (which
many unrelated modules do) must never apply them. This runs in a fresh
interpreter so it is unaffected by other tests that build a main window.
"""

from __future__ import annotations

import os
import subprocess
import sys


def test_importing_views_orange_does_not_install_canvas_patches():
    """A fresh import of the views module leaves the patch flag unset."""
    code = (
        "import derzug.views.orange as o\n"
        "assert o._CANVAS_PATCHES_INSTALLED is False, 'patches ran at import'\n"
        "assert hasattr(o, 'ensure_canvas_patches_installed')\n"
        "print('IMPORT_PURE')\n"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
        env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
    )
    assert result.returncode == 0, result.stderr
    assert "IMPORT_PURE" in result.stdout
