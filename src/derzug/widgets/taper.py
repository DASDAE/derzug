"""Orange widget for applying DASCore taper to patches."""

from __future__ import annotations

from typing import ClassVar

from Orange.widgets.widget import Msg

from derzug.core.patchmethodwidget import ComboOption, PatchMethodWidget, SpinOption
from derzug.settings import Setting


class Taper(PatchMethodWidget):
    """Apply a taper window to a patch along a selected dimension."""

    name = "Taper"
    description = "Apply a taper window to a patch along a selected dimension"
    icon = "icons/Taper.svg"
    category = "Processing"
    keywords = ("taper", "window", "hann", "pre-fft", "cosine")
    priority = 21.4
    want_main_area = False

    p = Setting(0.05)
    window_type = Setting("hann")

    method_name = "taper"
    call_style = "keyword_dim"
    error_key = "taper_failed"
    _OPTIONS: ClassVar[tuple[object, ...]] = (
        SpinOption(
            "p",
            minimum=0.0,
            maximum=0.4,
            step=0.01,
            decimals=3,
            role="dim_value",
            label="Taper fraction (p):",
            spin_attr="_p_spin",
        ),
        ComboOption(
            "window_type",
            ("hann", "hamming", "blackman", "nuttall"),
            role="kwarg",
            label="Window type:",
            combo_attr="_window_combo",
        ),
    )

    class Error(PatchMethodWidget.Error):
        """Errors shown by the widget."""

        taper_failed = Msg("Taper failed: {}")


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Taper).run()
