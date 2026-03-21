"""Guard AnyQt bugs before QtGui is imported.

AnyQt <= 0.2.1 has a missing comma in ``_ctypes.find_library``'s macOS
branch, causing ``load_qtlib("QtGui")`` to return ``None``.  The fixer
``fix_pyqt6_qtgui_qaction_menu`` then crashes with ``TypeError`` at import
time of ``AnyQt.QtGui``.  Wrapping it in a try/except lets the rest of the
import proceed; ``QAction.setMenu`` will be absent on that platform, but no
derzug code path requires it.
"""

from __future__ import annotations

try:
    from AnyQt import _fixes as _anyqt_fixes

    _orig = _anyqt_fixes.fix_pyqt6_qtgui_qaction_menu

    def _guarded(namespace: dict, _o=_orig) -> None:
        try:
            _o(namespace)
        except TypeError:
            pass

    _anyqt_fixes.fix_pyqt6_qtgui_qaction_menu = _guarded
    del _orig, _guarded
except Exception:
    pass
