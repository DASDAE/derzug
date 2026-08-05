"""Orange widget for applying DASCore taper to patches."""

from __future__ import annotations

from typing import ClassVar

from Orange.widgets.widget import Msg

from derzug.core.patchmethodwidget import PatchMethodWidget
from derzug.nodes.taper import _OPTIONS, NODE_SPEC


class Taper(PatchMethodWidget):
    """Apply a taper window to a patch along a selected dimension."""

    node_spec = NODE_SPEC
    want_main_area = False

    authoritative_state = True

    error_key = "taper_failed"
    _OPTIONS: ClassVar[tuple[object, ...]] = _OPTIONS

    class Error(PatchMethodWidget.Error):
        """Errors shown by the widget."""

        taper_failed = Msg("Taper failed: {}")


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Taper).run()
