"""Orange widget for applying unary math transforms to a patch."""

from __future__ import annotations

from typing import ClassVar

from Orange.widgets.widget import Msg

from derzug.core.patchmethodwidget import ComboOption, PatchMethodWidget
from derzug.settings import Setting


class UFuncUnary(PatchMethodWidget):
    """Apply a selected unary element-wise math transform to an input patch."""

    name = "UFuncUnary"
    description = "Apply a unary element-wise transform to a patch"
    icon = "icons/UFunc.svg"
    category = "Processing"
    keywords = ("ufunc", "math", "unary", "abs", "log", "exp", "transform")
    priority = 22
    want_main_area = False

    selected_op = Setting("abs")

    _OPS: ClassVar[tuple[str, ...]] = (
        "abs",
        "real",
        "imag",
        "conj",
        "angle",
        "exp",
        "log",
        "log10",
        "log2",
    )

    uses_dim = False
    call_style = "plain"
    _OPTIONS: ClassVar[tuple[object, ...]] = (
        ComboOption(
            "selected_op",
            _OPS,
            role="method",
            label="Operation:",
            combo_attr="_op_combo",
        ),
    )

    class Error(PatchMethodWidget.Error):
        """Errors shown by the widget."""

        operation_failed = Msg("UFunc operation '{}' failed: {}")

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the operation-specific banner."""
        op = self.selected_op if self.selected_op in self._OPS else self._OPS[0]
        self._show_exception("operation_failed", exc, op)


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(UFuncUnary).run()
