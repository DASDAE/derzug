"""Orange widget for applying DASCore detrend to patches."""

from __future__ import annotations

from typing import ClassVar

from Orange.widgets.widget import Msg

from derzug.core.patchmethodwidget import PatchMethodWidget
from derzug.nodes.detrend import _OPTIONS, NODE_SPEC


class Detrend(PatchMethodWidget):
    """Apply DASCore detrending to an input patch."""

    node_spec = NODE_SPEC
    name = "Detrend"
    description = "Apply DASCore detrending to a patch"
    icon = "icons/Detrend.svg"
    category = "Processing"
    keywords = ("detrend", "trend", "linear", "constant")
    priority = 21
    want_main_area = False

    authoritative_state = True

    method_name = "detrend"
    call_style = "positional_dim"
    error_key = "detrend_failed"
    _OPTIONS: ClassVar[tuple[object, ...]] = _OPTIONS

    class Error(PatchMethodWidget.Error):
        """Errors shown by the widget."""

        detrend_failed = Msg("Detrend failed: {}")


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Detrend).run()
