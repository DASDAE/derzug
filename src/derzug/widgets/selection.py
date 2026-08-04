"""Selection control panel for patch- and spool-based widgets.

The state these controls edit is Qt-free and lives in
:mod:`derzug.models.selection_state`; it is re-exported here so widgets keep
importing one module.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Any

from AnyQt.QtWidgets import (
    QCheckBox,
    QComboBox,
    QGridLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets import gui

from derzug.models.selection_state import (
    PatchSelectionBasis,
    PatchSelectionState,
    SelectionMode,
    SelectionState,
    SpoolFilterRowState,
    SpoolFilterState,
    _parse_coord_value,
    _text_matches_display_value,
    _values_equal,
)
from derzug.utils.display import format_display

__all__ = [
    "PatchSelectionBasis",
    "PatchSelectionState",
    "SelectionControlsMixin",
    "SelectionMode",
    "SelectionPanel",
    "SelectionState",
    "SpoolFilterRowState",
    "SpoolFilterState",
]


class SelectionPanel(QWidget):
    """Reusable left-side selection panel."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._sync_depth = 0
        self.patch_checkboxes: dict[str, QCheckBox] = {}
        self.patch_edits: dict[str, tuple[QLineEdit, QLineEdit]] = {}
        self._active_dims: tuple[str, ...] = ()
        self.spool_rows: list[tuple[QComboBox, QLineEdit, QPushButton]] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self.mode_label = QLabel("", self)
        self.hint_label = QLabel("", self)
        self.hint_label.setWordWrap(True)
        self.status_label = QLabel("", self)
        self.reset_button = QPushButton("Reset", self)
        layout.addWidget(self.mode_label)
        layout.addWidget(self.hint_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.reset_button)

        self.patch_basis_label = QLabel("Basis", self)
        self.patch_basis_combo = QComboBox(self)
        for basis in PatchSelectionBasis:
            self.patch_basis_combo.addItem(basis.value.title(), basis)
        layout.addWidget(self.patch_basis_label)
        layout.addWidget(self.patch_basis_combo)

        self.patch_widget = QWidget(self)
        self.patch_layout = QGridLayout(self.patch_widget)
        self.patch_layout.setContentsMargins(0, 0, 0, 0)
        self.patch_layout.setHorizontalSpacing(6)
        self.patch_layout.setVerticalSpacing(4)
        layout.addWidget(self.patch_widget)

        self.spool_widget = QWidget(self)
        self.spool_layout = QGridLayout(self.spool_widget)
        self.spool_layout.setContentsMargins(0, 0, 0, 0)
        self.spool_layout.setHorizontalSpacing(6)
        self.spool_layout.setVerticalSpacing(4)
        self.spool_layout.addWidget(QLabel("Field", self.spool_widget), 0, 0)
        self.spool_layout.addWidget(QLabel("Value", self.spool_widget), 0, 1)
        self.spool_layout.addWidget(QLabel("", self.spool_widget), 0, 2)
        self.spool_rows_container = QWidget(self.spool_widget)
        self.spool_rows_layout = QGridLayout(self.spool_rows_container)
        self.spool_rows_layout.setContentsMargins(0, 0, 0, 0)
        self.spool_rows_layout.setHorizontalSpacing(6)
        self.spool_rows_layout.setVerticalSpacing(4)
        self.spool_layout.addWidget(self.spool_rows_container, 1, 0, 1, 3)
        self.spool_add_button = QPushButton("+", self.spool_widget)
        self.spool_add_button.setToolTip("Add another spool filter row")
        self.spool_layout.addWidget(self.spool_add_button, 2, 0, 1, 3)
        layout.addWidget(self.spool_widget)

        self.on_patch_range_changed = None
        self.on_patch_enabled_changed = None
        self.on_patch_basis_changed = None
        self.on_spool_filter_changed = None
        self.on_spool_filter_add_requested = None
        self.on_spool_filter_remove_requested = None
        self.on_reset_requested = None

        self.patch_basis_combo.currentIndexChanged.connect(
            self._handle_patch_basis_changed
        )
        self.spool_add_button.clicked.connect(self._handle_spool_add_clicked)
        self.reset_button.clicked.connect(self._handle_reset_clicked)
        self.set_mode(SelectionMode.NONE)

    @contextmanager
    def syncing(self):
        """Suppress callbacks while updating widgets programmatically."""
        self._sync_depth += 1
        try:
            yield
        finally:
            self._sync_depth -= 1

    def is_syncing(self) -> bool:
        """Return True when widget values are being synced programmatically."""
        return self._sync_depth > 0

    def set_mode(self, mode: SelectionMode) -> None:
        """Update visibility and helper text for the active selection mode."""
        patch_mode = mode is SelectionMode.PATCH
        spool_mode = mode is SelectionMode.SPOOL
        self.patch_basis_label.setVisible(patch_mode)
        self.patch_basis_combo.setVisible(patch_mode)
        self.patch_basis_combo.setEnabled(patch_mode)
        self.patch_widget.setVisible(patch_mode)
        self.patch_widget.setEnabled(patch_mode)
        self.spool_widget.setVisible(spool_mode)
        self.spool_widget.setEnabled(spool_mode)
        self.reset_button.setEnabled(mode is not SelectionMode.NONE)
        if mode is SelectionMode.PATCH:
            self.mode_label.setText("Range selection")
            self.hint_label.setText(self._patch_hint_text())
        elif mode is SelectionMode.SPOOL:
            self.mode_label.setText("Metadata selection")
            self.hint_label.setText(
                "Values use Python literal syntax when possible; "
                "bare strings are treated as strings."
            )
        else:
            self.mode_label.setText("No selection source")
            self.hint_label.setText("")
            self.status_label.setText("")

    def set_status(self, text: str) -> None:
        """Set the small status/summary label."""
        self.status_label.setText(text)

    def set_patch_basis(self, basis: PatchSelectionBasis) -> None:
        """Write the current patch basis into the visible combo box."""
        with self.syncing():
            index = self.patch_basis_combo.findData(basis)
            if index >= 0:
                self.patch_basis_combo.setCurrentIndex(index)
        if self.patch_widget.isVisible():
            self.hint_label.setText(self._patch_hint_text())

    def rebuild_patch_rows(
        self,
        dims: tuple[str, ...],
        extents: dict[str, tuple[Any, Any]],
        preferred_dims: tuple[str, ...] = (),
    ) -> None:
        """Recreate patch-range controls with preferred dims listed first."""
        layout = self.patch_layout
        while layout.count():
            item = layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self.patch_checkboxes = {}
        self.patch_edits = {}
        self._active_dims = self._ordered_dims(dims, preferred_dims)

        if not self._active_dims:
            layout.addWidget(QLabel("No patch loaded", self.patch_widget), 0, 0)
            return

        for index, dim in enumerate(self._active_dims):
            row = index * 3
            checkbox = QCheckBox(self.patch_widget)
            label = QLabel(f"<b>{dim}</b>", self.patch_widget)
            min_label = QLabel("Min", self.patch_widget)
            max_label = QLabel("Max", self.patch_widget)
            low_edit = QLineEdit(self.patch_widget)
            high_edit = QLineEdit(self.patch_widget)
            low_edit.setPlaceholderText("")
            high_edit.setPlaceholderText("")
            checkbox.toggled.connect(
                lambda checked, dim_name=dim: self._handle_patch_enabled_changed(
                    dim_name, checked
                )
            )
            low_edit.editingFinished.connect(
                lambda dim_name=dim: self._handle_patch_range_changed(dim_name)
            )
            high_edit.editingFinished.connect(
                lambda dim_name=dim: self._handle_patch_range_changed(dim_name)
            )
            # Stack each dimension vertically so the control panel stays narrow.
            layout.addWidget(checkbox, row, 0)
            layout.addWidget(label, row, 1, 1, 3)
            layout.addWidget(min_label, row + 1, 0)
            layout.addWidget(low_edit, row + 1, 1, 1, 3)
            layout.addWidget(max_label, row + 2, 0)
            layout.addWidget(high_edit, row + 2, 1, 1, 3)
            self.patch_checkboxes[dim] = checkbox
            self.patch_edits[dim] = (low_edit, high_edit)

    def set_patch_ranges(
        self,
        ranges: dict[str, tuple[Any, Any]],
        extents: dict[str, tuple[Any, Any]],
        show_full_extent_dims: tuple[str, ...] = (),
    ) -> None:
        """Write current patch ranges into the visible line edits."""
        show_full_extent = set(show_full_extent_dims)
        with self.syncing():
            for dim, edits in self.patch_edits.items():
                if dim not in ranges:
                    continue
                if dim not in extents:
                    continue
                low_edit, high_edit = edits
                low, high = ranges[dim]
                full_low, full_high = extents[dim]
                if dim in show_full_extent:
                    desired_low = format_display(low)
                    desired_high = format_display(high)
                else:
                    desired_low = (
                        "" if _values_equal(low, full_low) else format_display(low)
                    )
                    desired_high = (
                        "" if _values_equal(high, full_high) else format_display(high)
                    )
                current_low = low_edit.text()
                current_high = high_edit.text()
                if desired_low == "":
                    low_edit.setText("")
                elif not _text_matches_display_value(current_low, full_low, low):
                    low_edit.setText(desired_low)
                if desired_high == "":
                    high_edit.setText("")
                elif not _text_matches_display_value(current_high, full_high, high):
                    high_edit.setText(desired_high)

    def set_patch_enabled(self, enabled: dict[str, bool]) -> None:
        """Write current patch enabled state into the visible controls."""
        with self.syncing():
            for dim, checkbox in self.patch_checkboxes.items():
                is_enabled = enabled.get(dim, True)
                checkbox.setChecked(is_enabled)
                low_edit, high_edit = self.patch_edits[dim]
                low_edit.setEnabled(is_enabled)
                high_edit.setEnabled(is_enabled)

    def set_patch_editable(self, editable: bool) -> None:
        """Set whether patch range controls are user editable."""
        patch_mode = self.patch_widget.isVisible()
        self.patch_basis_combo.setEnabled(patch_mode and editable)
        self.reset_button.setEnabled(
            self.reset_button.isEnabled() and not (patch_mode and not editable)
        )
        for dim, checkbox in self.patch_checkboxes.items():
            dim_enabled = checkbox.isChecked()
            checkbox.setEnabled(editable)
            low_edit, high_edit = self.patch_edits[dim]
            low_edit.setEnabled(dim_enabled and editable)
            high_edit.setEnabled(dim_enabled and editable)

    def set_spool_filters(
        self,
        options: tuple[str, ...],
        filters: list[tuple[str, str]],
    ) -> None:
        """Write spool filter state into the visible controls."""
        with self.syncing():
            while self.spool_rows_layout.count():
                item = self.spool_rows_layout.takeAt(0)
                widget = item.widget()
                if widget is not None:
                    widget.deleteLater()
            self.spool_rows = []
            rows = filters or [("", "")]
            for row_index, (key, raw_value) in enumerate(rows):
                combo = QComboBox(self.spool_rows_container)
                combo.addItems(options)
                if key in options:
                    combo.setCurrentText(key)
                else:
                    combo.setCurrentIndex(-1)
                combo.currentIndexChanged.connect(self._handle_spool_changed)
                value_edit = QLineEdit(self.spool_rows_container)
                value_edit.setPlaceholderText("Value")
                value_edit.setText(raw_value)
                value_edit.editingFinished.connect(self._handle_spool_changed)
                remove_button = QPushButton("-", self.spool_rows_container)
                remove_button.setToolTip("Remove this spool filter row")
                remove_button.clicked.connect(
                    lambda _checked=False, index=row_index: (
                        self._handle_spool_remove_clicked(index)
                    )
                )
                self.spool_rows_layout.addWidget(combo, row_index, 0)
                self.spool_rows_layout.addWidget(value_edit, row_index, 1)
                self.spool_rows_layout.addWidget(remove_button, row_index, 2)
                self.spool_rows.append((combo, value_edit, remove_button))
            for row_index, (_combo, _edit, remove_button) in enumerate(self.spool_rows):
                remove_button.setEnabled(len(self.spool_rows) > 1)

    @staticmethod
    def _ordered_dims(
        dims: tuple[str, ...],
        preferred_dims: tuple[str, ...],
    ) -> tuple[str, ...]:
        """Return dims with preferred ones first, preserving relative order."""
        preferred = [dim for dim in preferred_dims if dim in dims]
        remaining = [dim for dim in dims if dim not in preferred]
        return tuple(preferred + remaining)

    def _handle_patch_range_changed(self, dim: str) -> None:
        """Emit the current texts for a patch range row."""
        if self.is_syncing() or self.on_patch_range_changed is None:
            return
        low_edit, high_edit = self.patch_edits[dim]
        self.on_patch_range_changed(dim, low_edit.text(), high_edit.text())

    def _handle_patch_enabled_changed(self, dim: str, enabled: bool) -> None:
        """Emit the current enabled state for a patch range row."""
        if self.is_syncing():
            return
        low_edit, high_edit = self.patch_edits[dim]
        low_edit.setEnabled(enabled)
        high_edit.setEnabled(enabled)
        if self.on_patch_enabled_changed is not None:
            self.on_patch_enabled_changed(dim, enabled)

    def _handle_patch_basis_changed(self, *_args) -> None:
        """Emit the currently selected patch basis."""
        if self.is_syncing() or self.on_patch_basis_changed is None:
            return
        basis = self.patch_basis_combo.currentData()
        if isinstance(basis, PatchSelectionBasis):
            self.on_patch_basis_changed(basis)

    def _handle_spool_changed(self, *_args) -> None:
        """Emit the current spool filter values."""
        if self.is_syncing() or self.on_spool_filter_changed is None:
            return
        self.on_spool_filter_changed(
            [
                (combo.currentText().strip(), value_edit.text().strip())
                for combo, value_edit, _remove_button in self.spool_rows
            ]
        )

    def _handle_spool_add_clicked(self) -> None:
        """Request one additional spool filter row."""
        if self.is_syncing() or self.on_spool_filter_add_requested is None:
            return
        self.on_spool_filter_add_requested()

    def _handle_spool_remove_clicked(self, index: int) -> None:
        """Request removal of one spool filter row."""
        if self.is_syncing() or self.on_spool_filter_remove_requested is None:
            return
        self.on_spool_filter_remove_requested(index)

    def _handle_reset_clicked(self) -> None:
        """Invoke the reset callback."""
        if self.is_syncing() or self.on_reset_requested is None:
            return
        self.on_reset_requested()

    def _patch_hint_text(self) -> str:
        """Return the helper text for the active patch basis."""
        basis = self.patch_basis_combo.currentData()
        if basis is PatchSelectionBasis.RELATIVE:
            unit = "offsets from the first coordinate"
        elif basis is PatchSelectionBasis.SAMPLES:
            unit = "sample indices"
        else:
            unit = "coordinate values"
        return f"Edit min/max {unit}. \nLeave blank to use full extent."


class SelectionControlsMixin:
    """Reusable selection state and left-panel UI for patch/spool widgets."""

    def _init_selection_controls(self) -> None:
        """Initialize selection state before building the panel."""
        self._selection_state = SelectionState()
        self._selection_preferred_patch_dims: tuple[str, ...] = ()
        self._selection_sync_depth = 0
        self._selection_panel: SelectionPanel | None = None
        self._selection_patch_checkboxes: dict[str, QCheckBox] = {}
        self._selection_patch_edits: dict[str, tuple[QLineEdit, QLineEdit]] = {}
        self._selection_patch_editable = True

    @contextmanager
    def _selection_sync_guard(self):
        """Suppress recursive selection updates while syncing state and visuals."""
        self._selection_sync_depth += 1
        try:
            yield
        finally:
            self._selection_sync_depth -= 1

    def _selection_is_syncing(self) -> bool:
        """Return True when selection state is being synchronized programmatically."""
        return self._selection_sync_depth > 0

    @property
    def _selection_mode(self) -> str | None:
        """Compatibility shim for tests and host widgets."""
        if self._selection_state.mode is SelectionMode.NONE:
            return None
        return self._selection_state.mode.value

    @property
    def _selection_spool_options(self) -> tuple[str, ...]:
        """Compatibility shim exposing current spool options."""
        return self._selection_state.spool.options

    @property
    def _selection_spool_key(self) -> str:
        """Compatibility shim exposing current spool key."""
        return self._selection_state.spool.filters[0].key

    @property
    def _selection_spool_raw(self) -> str:
        """Compatibility shim exposing current spool raw value."""
        return self._selection_state.spool.filters[0].raw_value

    @property
    def _selection_spool_combo(self):
        """Compatibility shim exposing the first spool filter combo."""
        if self._selection_panel is None or not self._selection_panel.spool_rows:
            return None
        return self._selection_panel.spool_rows[0][0]

    @property
    def _selection_spool_value_edit(self):
        """Compatibility shim exposing the first spool filter value edit."""
        if self._selection_panel is None or not self._selection_panel.spool_rows:
            return None
        return self._selection_panel.spool_rows[0][1]

    @property
    def _selection_patch_basis(self) -> str:
        """Compatibility shim exposing the current patch basis."""
        return self._selection_state.patch.basis.value

    @property
    def _selection_patch_enabled(self) -> dict[str, bool]:
        """Compatibility shim exposing per-dimension enabled state."""
        return dict(self._selection_state.patch.enabled)

    def _build_selection_panel(self, parent, *, title: str = "Select") -> QWidget:
        """Create the shared selection controls under an existing parent box."""
        section = gui.widgetBox(parent, title)
        panel = SelectionPanel(section)
        panel.on_patch_range_changed = self._on_selection_patch_range_changed
        panel.on_patch_enabled_changed = self._on_selection_patch_enabled_changed
        panel.on_patch_basis_changed = self._on_selection_patch_basis_changed
        panel.on_spool_filter_changed = self._on_selection_spool_changed
        panel.on_spool_filter_add_requested = self._on_selection_spool_add_requested
        panel.on_spool_filter_remove_requested = (
            self._on_selection_spool_remove_requested
        )
        panel.on_reset_requested = self._on_selection_reset_requested
        section.layout().addWidget(panel)
        self._selection_panel = panel
        self._selection_patch_checkboxes = panel.patch_checkboxes
        return section

    def _selection_set_preferred_patch_dims(self, dims: tuple[str, ...]) -> None:
        """Set patch dims that should appear first in the left panel."""
        self._selection_preferred_patch_dims = dims

    def _selection_set_patch_source(
        self,
        patch,
        *,
        notify: bool = True,
        refresh_ui: bool = True,
    ) -> None:
        """Seed patch-mode selection state from the current patch extents."""
        self._selection_state.set_patch_source(patch)
        self._selection_refresh_panel()
        if refresh_ui:
            self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_set_spool_source(
        self,
        spool,
        *,
        notify: bool = True,
        refresh_ui: bool = True,
    ) -> None:
        """Seed spool-mode selection state from the current spool contents."""
        self._selection_state.set_spool_source(spool)
        self._selection_refresh_panel()
        if refresh_ui:
            self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_refresh_panel(self) -> None:
        """Push the current typed selection state into the Qt controls."""
        if self._selection_panel is None:
            return
        panel = self._selection_panel
        panel.set_mode(self._selection_state.mode)
        panel.set_patch_basis(self._selection_state.patch.basis)
        panel.rebuild_patch_rows(
            tuple(self._selection_state.patch.extents),
            self._selection_state.patch.extents,
            self._selection_preferred_patch_dims,
        )
        panel.set_patch_enabled(self._selection_state.patch.enabled)
        panel.set_patch_ranges(
            self._selection_state.patch.ranges,
            self._selection_state.patch.extents,
            self._selection_show_full_extent_dims(),
        )
        panel.set_spool_filters(
            self._selection_state.spool.options,
            [
                (filter_row.key, filter_row.raw_value)
                for filter_row in self._selection_state.spool.filters
            ],
        )
        panel.set_patch_editable(self._selection_patch_editable)
        self._selection_patch_checkboxes = panel.patch_checkboxes
        self._selection_patch_edits = panel.patch_edits

    def _selection_set_patch_editable(self, editable: bool) -> None:
        """Set whether patch controls are editable by the user."""
        self._selection_patch_editable = bool(editable)
        if self._selection_panel is not None:
            self._selection_panel.set_patch_editable(self._selection_patch_editable)

    def _selection_show_full_extent_dims(self) -> tuple[str, ...]:
        """Return dims whose full-extent ranges should be shown, not blanked."""
        return ()

    def _selection_request_panel_refresh(self) -> None:
        """Request a visible selection-panel refresh through the host widget."""
        self._selection_refresh_panel()
        self._request_ui_refresh()

    def _selection_set_status(self, text: str) -> None:
        """Update the small status label shown in the selection panel."""
        if self._selection_panel is not None:
            self._selection_panel.set_status(text)

    def _selection_apply_to_patch(self, patch):
        """Apply the current patch-mode ranges to a patch."""
        return self._selection_state.apply_to_patch(patch)

    def _selection_apply_to_spool(self, spool):
        """Apply the current spool filter to a spool."""
        return self._selection_state.apply_to_spool(spool)

    def _selection_update_patch_range(
        self,
        dim: str,
        low: Any,
        high: Any,
        *,
        notify: bool = True,
    ) -> None:
        """Update a single patch dimension range and refresh the visible controls."""
        self._selection_state.update_patch_range(dim, low, high)
        self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_update_patch_range_absolute(
        self,
        dim: str,
        low: Any,
        high: Any,
        *,
        notify: bool = True,
    ) -> None:
        """Update a patch range from absolute coordinate values."""
        self._selection_state.update_patch_range_absolute(dim, low, high)
        self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_update_patch_range_absolute_from_roi(
        self,
        dim: str,
        low: Any,
        high: Any,
        *,
        notify: bool = True,
    ) -> None:
        """Update a patch range from ROI-driven absolute coordinate values."""
        self._selection_state.update_patch_range_absolute_from_roi(dim, low, high)
        self._selection_refresh_panel()
        if notify:
            self._selection_on_state_changed()

    def _selection_reset_patch_dims(
        self,
        dims: tuple[str, ...],
        *,
        notify: bool = True,
    ) -> None:
        """Reset selected patch dims back to their full extents."""
        self._selection_state.reset_patch_dims(dims)
        self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_set_patch_dim_enabled(
        self,
        dim: str,
        enabled: bool,
        *,
        notify: bool = True,
    ) -> None:
        """Enable or disable one patch dimension and refresh the controls."""
        self._selection_state.set_patch_dim_enabled(dim, enabled)
        self._selection_request_panel_refresh()
        if notify:
            self._selection_on_state_changed()

    def _selection_current_patch_range(self, dim: str) -> tuple[Any, Any] | None:
        """Return the current range for a patch dimension."""
        return self._selection_state.current_patch_range(dim)

    def _selection_patch_extent(self, dim: str) -> tuple[Any, Any] | None:
        """Return the full extent for a patch dimension."""
        return self._selection_state.patch_extent(dim)

    def _selection_current_patch_absolute_range(
        self,
        dim: str,
    ) -> tuple[Any, Any] | None:
        """Return the current patch range in absolute coordinate values."""
        return self._selection_state.current_patch_absolute_range(dim)

    def _selection_patch_absolute_extent(
        self,
        dim: str,
    ) -> tuple[Any, Any] | None:
        """Return the full patch extent in absolute coordinate values."""
        return self._selection_state.patch_absolute_extent(dim)

    def _on_selection_patch_range_changed(
        self,
        dim: str,
        low_text: str,
        high_text: str,
    ) -> None:
        """Handle user edits to a patch range row."""
        if self._selection_is_syncing() or not self._selection_patch_editable:
            return
        extent = self._selection_state.patch_extent(dim)
        if extent is None:
            return
        try:
            low = _parse_coord_value(low_text, extent[0], extent[0])
            high = _parse_coord_value(high_text, extent[1], extent[1])
        except Exception as exc:
            self._selection_report_error(str(exc))
            self._selection_request_panel_refresh()
            return
        self._selection_state.update_patch_range(dim, low, high)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_patch_basis_changed(self, basis: PatchSelectionBasis) -> None:
        """Handle user changes to the patch selection basis."""
        if self._selection_is_syncing() or not self._selection_patch_editable:
            return
        self._selection_state.set_patch_basis(basis)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_patch_enabled_changed(self, dim: str, enabled: bool) -> None:
        """Handle user toggles of a patch dimension checkbox."""
        if self._selection_is_syncing() or not self._selection_patch_editable:
            return
        self._selection_state.set_patch_dim_enabled(dim, enabled)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_spool_changed(self, filters: list[tuple[str, str]]) -> None:
        """Handle user edits to the spool filter controls."""
        if self._selection_is_syncing():
            return
        self._selection_state.set_spool_filters(filters)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_spool_add_requested(self) -> None:
        """Handle requests to add one spool filter row."""
        if self._selection_is_syncing():
            return
        self._selection_state.add_spool_filter()
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_spool_remove_requested(self, index: int) -> None:
        """Handle requests to remove one spool filter row."""
        if self._selection_is_syncing():
            return
        self._selection_state.remove_spool_filter(index)
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _on_selection_reset_requested(self) -> None:
        """Reset the current selection back to full extents / no filter."""
        if (
            not self._selection_patch_editable
            and self._selection_state.mode is SelectionMode.PATCH
        ):
            return
        self._selection_state.reset()
        self._selection_request_panel_refresh()
        self._selection_on_state_changed()

    def _selection_report_error(self, message: str) -> None:
        """Route selection UI errors to the widget's general error slot if present."""
        error_slot = getattr(getattr(self, "Error", None), "general", None)
        if error_slot is not None:
            error_slot(message)

    def _selection_on_state_changed(self) -> None:
        """Hook for host widgets to react when selection controls change."""
        return None
