"""Generic selection widget for DASCore patch and spool objects."""

from __future__ import annotations

from copy import deepcopy
from typing import ClassVar

import dascore as dc
from AnyQt.QtCore import QTimer
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.models.annotations import AnnotationSet
from derzug.models.selection import SelectParams
from derzug.orange import Setting
from derzug.utils.spool import (
    extract_single_patch,
    filter_contents_by_annotations,
)
from derzug.widgets.selection import (
    PatchSelectionBasis,
    SelectionControlsMixin,
    SelectionMode,
    SelectionState,
)
from derzug.workflow import Task
from derzug.workflow.widget_tasks import PatchSelectionTask


class SelectTask(Task):
    """Workflow task mirroring Select's persisted patch/spool semantics."""

    input_variables: ClassVar[dict[str, object]] = {
        "patch": object,
        "spool": object,
        "annotation_set": object,
        "select_params": object,
    }
    output_variables: ClassVar[dict[str, object]] = {
        "patch": object,
        "spool": object,
    }

    patch_selection_payload: dict[str, object] | None = None
    spool_filters: tuple[tuple[str, str], ...] = ()
    unpack_single_patch: bool = True

    def run(self, patch=None, spool=None, annotation_set=None, select_params=None):
        """Apply persisted selection state to a patch or spool input."""
        if patch is not None:
            if select_params is not None:
                return {"patch": select_params.apply_to_patch(patch), "spool": None}
            selected = PatchSelectionTask(
                selection_payload=self.patch_selection_payload
            ).run(patch)
            return {"patch": selected, "spool": None}

        if spool is not None:
            selected = spool
            if annotation_set is not None:
                contents = spool.get_contents()
                filtered = filter_contents_by_annotations(contents, annotation_set)
                if len(filtered) != len(contents):
                    if filtered.empty:
                        selected = dc.spool([])
                    else:
                        wanted_rows = set(map(int, filtered.index))
                        selected = dc.spool(
                            [
                                patch_value
                                for row, patch_value in enumerate(spool)
                                if row in wanted_rows
                            ]
                        )
            state = SelectionState()
            state.set_spool_source(selected)
            state.set_spool_filters(list(self.spool_filters))
            selected = state.apply_to_spool(selected)
            selected_patch = None
            if self.unpack_single_patch:
                selected_patch = extract_single_patch(selected)
            return {"patch": selected_patch, "spool": selected}

        return {"patch": None, "spool": None}


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
    saved_patch_selection = Setting({}, schema_only=True)
    saved_selection_basis = Setting("", schema_only=True)
    saved_selection_ranges = Setting([], schema_only=True)
    saved_spool_filters = Setting([], schema_only=True)

    def __setattr__(self, name, value) -> None:
        """Track restored settings so late patch selection restore stays atomic."""
        super().__setattr__(name, value)
        if name not in {
            "saved_patch_selection",
            "saved_selection_basis",
            "saved_selection_ranges",
        }:
            return
        if not getattr(self, "_saved_patch_setting_sync_enabled", False):
            return
        if name == "saved_patch_selection":
            self._sync_pending_saved_patch_selection_payload()
            if not self._restore_pending_saved_patch_selection_if_ready():
                self._queue_pending_saved_patch_selection_apply()
            return
        self._queue_pending_saved_patch_selection_apply()

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        general = Msg("Selection error: {}")

    class Warning(ZugWidget.Warning):
        """Warnings shown by the widget."""

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)
        spool = Input("Spool", dc.BaseSpool)
        annotation_set = Input("Annotations", AnnotationSet)
        select_params = Input("Select Params", SelectParams)

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
        self._patch: dc.Patch | None = None
        self._spool: dc.BaseSpool | None = None
        self._annotation_set: AnnotationSet | None = None
        self._external_select_params: SelectParams | None = None
        self._manual_patch_selection_payload_before_params: (
            dict[str, object] | None
        ) = None
        self._input_kind: str | None = None
        self._preview_selected = None
        self._compact_width_done = False
        self._pending_saved_patch_selection_payload: dict[str, object] | None = None
        self._saved_patch_apply_queued = False
        self._saved_patch_setting_sync_enabled = False
        self._suspend_saved_patch_setting_sync = False
        self._prime_saved_selection_state()
        self._saved_patch_setting_sync_enabled = True
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
        self._apply_settings_to_controls()
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
        self._sync_pending_saved_patch_selection_payload()
        if self._external_select_params is not None:
            applied = self._apply_external_select_params_if_ready()
        else:
            applied = self._restore_pending_saved_patch_selection_if_ready()
        if not applied:
            self._selection_set_patch_source(patch, notify=False, refresh_ui=False)
            self._queue_pending_saved_patch_selection_apply()
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

    @Inputs.select_params
    def set_select_params(self, select_params: SelectParams | None) -> None:
        """Receive externally supplied patch.select parameters."""
        if select_params is not None and self._external_select_params is None:
            self._manual_patch_selection_payload_before_params = (
                self._current_patch_selection_payload()
            )
        self._external_select_params = select_params
        self._selection_set_patch_editable(select_params is None)
        if select_params is None:
            self._restore_manual_selection_after_params()
        else:
            self._apply_external_select_params_if_ready()
        self._emit_selected_output()

    def _selection_on_state_changed(self) -> None:
        """Recompute the current selected output and preview."""
        self._pending_saved_patch_selection_payload = None
        self._persist_selection_settings()
        self._emit_selected_output()

    def _apply_settings_to_controls(self) -> None:
        """Hydrate visible controls from persisted widget settings."""
        self._set_checkbox_value(self.unpack_checkbox, self.unpack_single_patch)

    def _sync_settings_from_controls(self) -> None:
        """Persist visible selection controls back into widget settings."""
        self.unpack_single_patch = bool(self.unpack_checkbox.isChecked())
        self._persist_selection_settings()

    def _rebind_dynamic_controls(self) -> None:
        """Rebuild selection controls after a new input source arrives."""
        self._selection_refresh_panel()

    def _emit_selected_output(self) -> None:
        """Trigger the standard run lifecycle so _on_result is always the send site."""
        self.run()

    def _run(self):
        # Compute the current selection result, or None when no input is connected.
        task, input_values = self._current_task_and_inputs()
        if task is None:
            return None
        try:
            return self._execute_task_or_pipe(
                task,
                input_values=input_values,
                output_names=("patch", "spool"),
            )
        except Exception as exc:
            self._show_exception("general", exc)
            return self._selection_fallback_result()

    def _on_result(self, result) -> None:
        """Send the selection result on both output channels."""
        patch = result.get("patch") if isinstance(result, dict) else None
        spool = result.get("spool") if isinstance(result, dict) else None
        self._preview_selected = spool if self._input_kind == "spool" else patch
        self.Outputs.spool.send(spool)
        self.Outputs.patch.send(patch)
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
        self._rebind_dynamic_controls()
        self._apply_settings_to_controls()
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
        payload = self.saved_patch_selection
        if isinstance(payload, dict):
            basis_name = str(payload.get("basis", "")).strip()
            rows = payload.get("rows")
            if basis_name and isinstance(rows, list) and rows:
                return {"basis": basis_name, "rows": deepcopy(rows)}
        basis_name = str(self.saved_selection_basis or "").strip()
        rows = (
            self.saved_selection_ranges
            if isinstance(self.saved_selection_ranges, list)
            else []
        )
        if not basis_name or not rows:
            return None
        return {"basis": basis_name, "rows": deepcopy(rows)}

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
        """Load persisted settings that do not require a bound patch source."""
        self._sync_pending_saved_patch_selection_payload()
        saved_filters = self._load_saved_spool_filter_state()
        if saved_filters:
            self._selection_state.set_spool_filters(saved_filters)

    def _sync_pending_saved_patch_selection_payload(self) -> None:
        """Refresh the staged saved patch selection payload from widget settings."""
        if self._suspend_saved_patch_setting_sync:
            return
        self._pending_saved_patch_selection_payload = (
            self._load_saved_patch_selection_state()
        )

    def _queue_pending_saved_patch_selection_apply(self) -> None:
        """Coalesce saved patch restore until the current Qt event turn finishes."""
        if self._saved_patch_apply_queued:
            return
        self._saved_patch_apply_queued = True
        QTimer.singleShot(0, self._flush_pending_saved_patch_selection_apply)

    def _flush_pending_saved_patch_selection_apply(self) -> None:
        """Refresh and apply any saved patch selection after queued restores land."""
        self._saved_patch_apply_queued = False
        self._sync_pending_saved_patch_selection_payload()
        self._restore_pending_saved_patch_selection_if_ready()

    def _saved_patch_selection_matches_live_state(
        self,
        payload: dict[str, object] | None,
    ) -> bool:
        """Return True when the saved patch-selection rows already match live state."""
        if not isinstance(payload, dict):
            return False
        basis_name = str(payload.get("basis", "")).strip()
        requires_bound_patch = basis_name != PatchSelectionBasis.ABSOLUTE.value
        if requires_bound_patch and self._selection_state.patch_source is None:
            return False
        if (
            requires_bound_patch
            and self._selection_state.mode is not SelectionMode.PATCH
        ):
            return False
        live_payload = self._selection_state.patch_settings_payload(
            include_inactive=True
        )
        if not isinstance(live_payload, dict):
            return False
        if live_payload.get("basis") != payload.get("basis"):
            return False
        live_rows = {
            str(row.get("dim")): row
            for row in live_payload.get("rows", [])
            if isinstance(row, dict) and row.get("dim")
        }
        for saved_row in payload.get("rows", []):
            if not isinstance(saved_row, dict):
                return False
            dim = str(saved_row.get("dim", "")).strip()
            if not dim or live_rows.get(dim) != saved_row:
                return False
        return True

    def _restore_saved_patch_selection_payload(
        self,
        payload: dict[str, object] | None,
    ) -> bool:
        """Rebuild live patch state atomically from saved payload plus current patch."""
        patch = self._patch
        if payload is None or patch is None:
            return False
        if self._saved_patch_selection_matches_live_state(payload):
            self._pending_saved_patch_selection_payload = None
            return False
        restored_state = SelectionState()
        if not restored_state.prime_patch_state_from_settings(payload):
            return False
        restored_state.set_patch_source(patch)
        self._selection_state = restored_state
        self._pending_saved_patch_selection_payload = None
        self._selection_refresh_panel()
        return True

    def _reconcile_saved_patch_selection_state(self) -> bool:
        """Compatibility shim for tests calling the old restore helper directly."""
        payload = (
            self._pending_saved_patch_selection_payload
            or self._load_saved_patch_selection_state()
        )
        return self._restore_saved_patch_selection_payload(payload)

    def _restore_pending_saved_patch_selection_if_ready(self) -> bool:
        """Apply staged saved patch settings once a patch input is available."""
        if self._input_kind != "patch" or self._patch is None:
            return False
        if self._pending_saved_patch_selection_payload is None:
            self._sync_pending_saved_patch_selection_payload()
        if self._pending_saved_patch_selection_payload is None:
            return False
        if not self._restore_saved_patch_selection_payload(
            self._pending_saved_patch_selection_payload
        ):
            return False
        self._emit_selected_output()
        return True

    def _persist_selection_settings(self) -> None:
        """Mirror the current selection controls into schema-backed settings."""
        if self._input_kind == "patch":
            payload = self._selection_state.patch_settings_payload(
                include_inactive=True
            )
            self._suspend_saved_patch_setting_sync = True
            try:
                if payload is None:
                    self.saved_patch_selection = {}
                    self.saved_selection_basis = ""
                    self.saved_selection_ranges = []
                else:
                    self.saved_patch_selection = deepcopy(payload)
                    self.saved_selection_basis = str(payload.get("basis", "")).strip()
                    rows = payload.get("rows")
                    self.saved_selection_ranges = (
                        deepcopy(rows) if isinstance(rows, list) else []
                    )
            finally:
                self._suspend_saved_patch_setting_sync = False
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

    def get_task(self) -> Task:
        """Return the compiled selection semantics for the current widget state."""
        return self._selection_task()

    def _selection_task(self) -> SelectTask:
        """Return the current canonical selection task."""
        patch_payload = self._current_patch_selection_payload()
        spool_filters = self._current_spool_filter_state()
        return SelectTask(
            patch_selection_payload=patch_payload,
            spool_filters=tuple(spool_filters),
            unpack_single_patch=bool(self.unpack_single_patch),
        )

    def _current_patch_selection_payload(self) -> dict[str, object] | None:
        """Return live patch selection payload, falling back to persisted settings."""
        if self._input_kind != "patch":
            return self._load_saved_patch_selection_state()
        return self._selection_state.patch_settings_payload(include_inactive=True)

    def _current_spool_filter_state(self) -> list[tuple[str, str]]:
        """Return live spool filter state, falling back to persisted settings."""
        if self._input_kind != "spool":
            return self._load_saved_spool_filter_state()
        return [
            (row.key, row.raw_value)
            for row in self._selection_state.spool.filters
            if row.key or row.raw_value
        ]

    def _current_task_and_inputs(
        self,
    ) -> tuple[SelectTask | None, dict[str, object]]:
        """Return the current selection task and its input payload."""
        if self._input_kind == "patch":
            if self._patch is None:
                return None, {}
            return (
                self._selection_task(),
                {
                    "patch": self._patch,
                    "spool": None,
                    "annotation_set": None,
                    "select_params": self._external_select_params,
                },
            )
        if self._input_kind == "spool":
            if self._spool is None:
                return None, {}
            return (
                self._selection_task(),
                {
                    "patch": None,
                    "spool": self._spool,
                    "annotation_set": self._annotation_set,
                    "select_params": None,
                },
            )
        return None, {}

    def _apply_external_select_params_if_ready(self) -> bool:
        """Apply connected SelectParams to the live patch selection state."""
        if (
            self._external_select_params is None
            or self._input_kind != "patch"
            or self._patch is None
        ):
            return False
        state = SelectionState()
        state.apply_select_params(self._external_select_params, self._patch)
        self._selection_state = state
        self._selection_refresh_panel()
        return True

    def _restore_manual_selection_after_params(self) -> None:
        """Restore editable patch controls after external params disconnect."""
        if self._input_kind != "patch" or self._patch is None:
            return
        payload = self._manual_patch_selection_payload_before_params
        self._manual_patch_selection_payload_before_params = None
        if payload is not None and self._restore_saved_patch_selection_payload(payload):
            return
        self._selection_set_patch_source(self._patch, notify=False, refresh_ui=False)

    def _selection_fallback_result(self) -> dict[str, object]:
        """Return the current unfiltered input as a safe fallback result."""
        if self._input_kind == "patch":
            return {"patch": self._patch, "spool": None}
        if self._input_kind == "spool":
            return {
                "patch": self._extract_output_patch(self._spool),
                "spool": self._spool,
            }
        return {"patch": None, "spool": None}


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Select).run()
