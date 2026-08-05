"""Orange widget for DASCore analytic-signal transforms."""

from __future__ import annotations

from typing import ClassVar

from Orange.widgets.widget import Msg

from derzug.core.patchmethodwidget import PatchMethodWidget
from derzug.nodes.analytic import _OPTIONS, NODE_SPEC


class Analytic(PatchMethodWidget):
    """Apply Hilbert-derived transforms to an input patch."""

    node_spec = NODE_SPEC
    want_main_area = False

    authoritative_state = True

    error_key = "transform_failed"
    _OPTIONS: ClassVar[tuple[object, ...]] = _OPTIONS

    class Error(PatchMethodWidget.Error):
        """Errors shown by the widget."""

        transform_failed = Msg("Analytic transform failed: {}")


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Analytic).run()
