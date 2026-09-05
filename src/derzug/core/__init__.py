"""
DerZug core modules.
"""

# Signal summaries must be registered before any widget class body runs, or
# Orange permanently disables auto-summary for that signal. Every widget
# imports a `derzug.core` module, so registering here makes that unconditional
# without `derzug.widgets` having to reach up into `derzug.views`.
from derzug.core import summary as _summary  # noqa: F401
from derzug.core.patchdimwidget import PatchDimWidget as PatchDimWidget
from derzug.core.patchwidget import PatchWidget as PatchWidget
from derzug.core.zugwidget import ZugWidget as ZugWidget

__all__ = (
    "PatchDimWidget",
    "PatchWidget",
    "ZugWidget",
)
