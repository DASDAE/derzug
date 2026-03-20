"""Generic selection widget for DASCore patch and spool objects."""

from __future__ import annotations

import dascore as dc
from AnyQt.QtCore import QTimer
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.models.annotations import AnnotationSet
from derzug.orange import Setting
from derzug.utils.spool import extract_single_patch, filter_contents_by_annotations
from derzug.widgets.selection import SelectionControlsMixin, SelectionMode


class Select(SelectionControlsMixin, ZugWidget):
    """Select subsets of patches or spools using shared left-side controls."""

    name = "Select"
    want_main_area = False
    description = "Select subsets of patches or spools"
    icon = "icons/SelectRows.svg"
    category = "Processing"
    keywords = ("select", "patch", "spool", "subset", "filter")
    priority = 23
    unpack_single_patch = Setting(True)
    saved_selection_basis = Setting("", schema_only=True)
    saved_selection_ranges = Setting([], schema_only=True)
    saved_spool_filters = Setting([], schema_only=True)

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        general = Msg("Selection error: {}")

    class Warning(ZugWidget.Warning):
        """Warnings shown by the widget."""

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)
        spool = Input("Spool", dc.BaseSpool)
        annotation_set = Input("Annotations", AnnotationSet, auto_summary=False)

    class Outputs:
        """Output signal definitions."""

        patch = Output(
            "Patch",
            dc.Patch,
            doc=(
                "If a length 1 spool is emitted, unpack it into a patch and serve "
                "on patch output when unpacking is enabled."
            ),
        )
        spool = Output("Spool", dc.BaseSpool)

    def __init__(self) -> None:
        super().__init__()
        self._init_selection_controls()
        self._prime_saved_selection_state()
        self._patch: dc.Patch | None = None
        self._spool: dc.BaseSpool | None = None
        self._annotation_set: AnnotationSet | None = None
        self._input_kind: str | None = None
        self._preview_selected = None
        self._compact_width_done = False

        params_box = gui.widgetBox(self.controlArea, "Parameters")
        self._build_selection_panel(params_box)
        self.unpack_checkbox = gui.checkBox(
            params_box,
            self,
            "unpack_single_patch",
            "Unpack len1 spool",
            callback=self._emit_selected_output,
        )
        self.unpack_checkbox.setToolTip(self.Outputs.patch.doc or "")
        self._selection_set_status("")

    def showEvent(self, event) -> None:
        """Compact the initial Select window width after the first visible layout."""
        super().showEvent(event)
        if not self._compact_width_done:
            QTimer.singleShot(0, self._compact_initial_width)

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive a patch input and expose patch-range selection controls."""
        self._input_kind = "patch"
        self._patch = patch
        self._spool = None
        self._selection_set_patch_source(patch, notify=False, refresh_ui=False)
        self._emit_selected_output()

    @Inputs.spool
    def set_spool(self, spool: dc.BaseSpool | None) -> None:
        """Receive a spool input and expose metadata selection controls."""
        self._input_kind = "spool"
        self._spool = spool
        self._patch = None
        self._selection_set_spool_source(spool, notify=False, refresh_ui=False)
        self._emit_selected_output()

    @Inputs.annotation_set
    def set_annotation_set(self, annotation_set: AnnotationSet | None) -> None:
        """Receive annotations used to constrain spool selection by overlap."""
        self._annotation_set = annotation_set
        self._emit_selected_output()

    def _selection_on_state_changed(self) -> None:
        """Recompute the current selected output and preview."""
        self._persist_selection_settings()
        self._emit_selected_output()

    def _emit_selected_output(self) -> None:
        """Emit the selected object on the output channel matching the input kind."""
        self.Error.clear()
        if self._input_kind == "patch":
            if self._patch is None:
                self._preview_selected = None
                self.Outputs.spool.send(None)
                self.Outputs.patch.send(None)
                self._request_ui_refresh()
                return
            try:
                selected = self._selection_apply_to_patch(self._patch)
            except Exception as exc:
                self._show_exception("general", exc)
                selected = self._patch
            self._preview_selected = selected
            self.Outputs.spool.send(None)
            self.Outputs.patch.send(selected)
            self._request_ui_refresh()
            return

        if self._input_kind == "spool":
            if self._spool is None:
                self._preview_selected = None
                self.Outputs.spool.send(None)
                self.Outputs.patch.send(None)
                self._request_ui_refresh()
                return
            try:
                selected = self._apply_annotation_filter_to_spool(self._spool)
                selected = self._selection_apply_to_spool(selected)
            except Exception as exc:
                self._show_exception("general", exc)
                selected = self._spool
            self._preview_selected = selected
            self.Outputs.spool.send(selected)
            self.Outputs.patch.send(self._extract_output_patch(selected))
            self._request_ui_refresh()
            return

        self._preview_selected = None
        self.Outputs.spool.send(None)
        self.Outputs.patch.send(None)
        self._request_ui_refresh()

    def _apply_annotation_filter_to_spool(self, spool: dc.BaseSpool) -> dc.BaseSpool:
        """Return only spool rows whose contents overlap the current annotations."""
        annotation_set = self._annotation_set
        if annotation_set is None:
            return spool
        contents = spool.get_contents()
        filtered = filter_contents_by_annotations(contents, annotation_set)
        if len(filtered) == len(contents):
            return spool
        if filtered.empty:
            return dc.spool([])
        wanted_rows = set(map(int, filtered.index))
        return dc.spool(
            [patch for row, patch in enumerate(spool) if row in wanted_rows]
        )

    def _refresh_ui(self) -> None:
        """Refresh the left-side selection controls and status text."""
        self._selection_refresh_panel()
        self.unpack_checkbox.setVisible(self._input_kind == "spool")
        self.unpack_checkbox.setEnabled(self._input_kind == "spool")
        self._selection_set_status(
            self._build_status_text(selected=self._preview_selected)
        )

    def _extract_output_patch(self, spool: dc.BaseSpool | None) -> dc.Patch | None:
        """Return the patch output when the emitted spool has length one."""
        if not self.unpack_single_patch or spool is None:
            return None
        return extract_single_patch(spool)

    def _load_saved_patch_selection_state(self) -> dict[str, object] | None:
        """Return serialized patch selection settings staged from widget state."""
        basis_name = str(self.saved_selection_basis or "").strip()
        rows = (
            self.saved_selection_ranges
            if isinstance(self.saved_selection_ranges, list)
            else []
        )
        if not basis_name or not rows:
            return None
        return {"basis": basis_name, "rows": rows}

    def _load_saved_spool_filter_state(self) -> list[tuple[str, str]]:
        """Return persisted spool filter rows from widget settings."""
        rows = (
            self.saved_spool_filters
            if isinstance(self.saved_spool_filters, list)
            else []
        )
        restored: list[tuple[str, str]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = str(row.get("key", "")).strip()
            raw_value = str(row.get("raw_value", ""))
            if not key and not raw_value:
                continue
            restored.append((key, raw_value))
        return restored

    def _prime_saved_selection_state(self) -> None:
        """Stage workflow-backed selection settings before any input arrives."""
        if self._selection_state.prime_patch_state_from_settings(
            self._load_saved_patch_selection_state()
        ):
            self._selection_state.mode = SelectionMode.NONE
        saved_filters = self._load_saved_spool_filter_state()
        if saved_filters:
            self._selection_state.set_spool_filters(saved_filters)

    def _persist_selection_settings(self) -> None:
        """Mirror the current selection controls into schema-backed settings."""
        if self._input_kind == "patch":
            payload = self._selection_state.patch_settings_payload(
                include_inactive=True
            )
            if payload is None:
                self.saved_selection_basis = ""
                self.saved_selection_ranges = []
            else:
                self.saved_selection_basis = str(payload["basis"])
                self.saved_selection_ranges = list(payload["rows"])
            return

        if self._input_kind == "spool":
            self.saved_spool_filters = [
                {"key": row.key, "raw_value": row.raw_value}
                for row in self._selection_state.spool.filters
                if row.key or row.raw_value
            ]

    def _build_status_text(self, selected=None) -> str:
        """Return one compact status line for the current selection state."""
        if self._input_kind == "patch":
            if self._patch is None:
                return ""
            active = self._selection_state.patch_kwargs()
            basis = self._selection_state.patch.basis.value
            return f"{basis} basis, {len(active)} active range filter(s)"

        if self._input_kind == "spool":
            if self._spool is None:
                return ""
            source_count = len(self._spool.get_contents())
            result_count = (
                len(selected.get_contents()) if selected is not None else source_count
            )
            return f"{result_count} of {source_count} spool item(s) selected"

        return ""

    def _compact_initial_width(self) -> None:
        """Shrink one newly shown Select window to the width its controls need."""
        if self._compact_width_done or not self._is_ui_visible():
            return
        window = self.window()
        if window.isFullScreen() or window.isMaximized():
            self._compact_width_done = True
            return
        target_width = max(window.minimumWidth(), self.sizeHint().width())
        if window.width() > target_width:
            window.resize(target_width, window.height())
        self._compact_width_done = True


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Select).run()
