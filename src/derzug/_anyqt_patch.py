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
    # Pytest imports AnyQt.QtCore in conftest before derzug.views.orange on macOS.
    # At that point AnyQt has already copied the original fixer into GLOBAL_FIXES,
    # so replacing only the module attribute is too late for later QtGui imports.
    for _api_name, _fixers in list(_anyqt_fixes.GLOBAL_FIXES.items()):
        _anyqt_fixes.GLOBAL_FIXES[_api_name] = [
            _guarded if fixer is _orig else fixer for fixer in _fixers
        ]
    del _api_name, _fixers, _orig, _guarded
except Exception:
    pass
