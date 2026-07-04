"""Orange widget for DASCore analytic-signal transforms."""

from __future__ import annotations

from typing import ClassVar

from Orange.widgets.widget import Msg

from derzug.core.patchmethodwidget import ComboOption, PatchMethodWidget


class Analytic(PatchMethodWidget):
    """Apply Hilbert-derived transforms to an input patch."""

    name = "Analytic"
    description = "Apply Hilbert-derived transforms to a patch"
    icon = "icons/Analytic.svg"
    category = "Transform"
    keywords = ("transform", "hilbert", "envelope", "analytic")
    priority = 21.2
    want_main_area = False

    authoritative_state = True

    call_style = "positional_dim"
    error_key = "transform_failed"
    _OPTIONS: ClassVar[tuple[ComboOption, ...]] = (
        ComboOption(
            "transform",
            ("hilbert", "envelope"),
            role="method",
            label="Transform:",
            combo_attr="_transform_combo",
        ),
    )

    class Error(PatchMethodWidget.Error):
        """Errors shown by the widget."""

        transform_failed = Msg("Analytic transform failed: {}")


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Analytic).run()
