"""Orange widget for common DASCore coordinate operations on patches."""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar

import dascore as dc
from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)
from dascore.core.coords import get_coord
from Orange.widgets import gui
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import WidgetExecutionRequest, ZugWidget
from derzug.orange import Setting
from derzug.utils.parsing import parse_coord_text_value
from derzug.workflow import Task


@dataclass(frozen=True)
class _CoordsPreviewState:
    """Derived main-area summary text for the Coords widget."""

    input_text: str
    active_text: str
    output_text: str


class CoordsTask(Task):
    """Portable coordinate-operation task for the Coords widget."""

    input_variables: ClassVar[dict[str, object]] = {"patch": object}
    output_variables: ClassVar[dict[str, object]] = {"patch": object}

    operation: str = "rename_coords"
    rename_rows: tuple[tuple[str, str], ...] = ()
    set_dims_rows: tuple[tuple[str, str], ...] = ()
    set_coords_applied_dim: str = ""
    set_coords_applied_start: str = ""
    set_coords_applied_stop: str = ""
    set_coords_applied_step: str = ""
    drop_coords_selected: tuple[str, ...] = ()
    sort_coords_selected: tuple[str, ...] = ()
    sort_reverse: bool = False
    snap_coords_selected: tuple[str, ...] = ()
    snap_reverse: bool = False
    flip_dims_selected: tuple[str, ...] = ()
    flip_data: bool = True
    flip_coords: bool = True
    transpose_order: tuple[str, ...] = ()

    @staticmethod
    def _normalize_rows(rows: tuple[tuple[str, str], ...]) -> list[tuple[str, str]]:
        return [
            (str(left or "").strip(), str(right or "").strip()) for left, right in rows
        ]

    @staticmethod
    def _validate_mapping(
        rows: tuple[tuple[str, str], ...],
        *,
        valid_left: tuple[str, ...],
        valid_right: tuple[str, ...] | None,
        reject_duplicate_right: bool,
    ) -> dict[str, str]:
        mapping: dict[str, str] = {}
        valid_left_set = set(valid_left)
        valid_right_set = None if valid_right is None else set(valid_right)
        used_right: set[str] = set()
        for left, right in CoordsTask._normalize_rows(rows):
            if not left and not right:
                continue
            if not left or not right:
                raise ValueError("both columns must be filled")
            if left not in valid_left_set:
                raise ValueError(f"'{left}' is not available")
            if valid_right_set is not None and right not in valid_right_set:
                raise ValueError(f"'{right}' is not available")
            if left in mapping:
                raise ValueError(f"duplicate source '{left}'")
            if reject_duplicate_right and right in used_right:
                raise ValueError(f"duplicate target '{right}'")
            mapping[left] = right
            used_right.add(right)
        if not mapping:
            raise ValueError("at least one mapping is required")
        return mapping

    @staticmethod
    def _validate_selection(
        selected: tuple[str, ...], valid: tuple[str, ...]
    ) -> list[str]:
        valid_set = set(valid)
        out = [str(item) for item in selected]
        invalid = [name for name in out if name not in valid_set]
        if invalid:
            raise ValueError(", ".join(invalid))
        return out

    @staticmethod
    def _parse_set_coord_value(text: str, sample: object) -> object:
        return parse_coord_text_value(str(text), sample, None)

    def _resolved_coord(self, patch):
        dim = self.set_coords_applied_dim
        if dim not in patch.dims:
            raise ValueError(f"'{dim}' is not an available dimension")
        coord = patch.coords.get_coord(dim)
        parsed: dict[str, object] = {}
        for label, raw in (
            ("start", self.set_coords_applied_start),
            ("stop", self.set_coords_applied_stop),
            ("step", self.set_coords_applied_step),
        ):
            text = str(raw).strip()
            if not text:
                continue
            parsed[label] = self._parse_set_coord_value(text, getattr(coord, label))
        if not parsed:
            raise ValueError("at least one of start, stop, and step is required")
        if set(parsed) == {"start"}:
            parsed["step"] = coord.step
        elif set(parsed) == {"stop"}:
            parsed["step"] = coord.step
        elif set(parsed) == {"step"}:
            parsed["start"] = coord.start
        kwargs = {
            "shape": patch.shape[patch.dims.index(dim)],
            "units": coord.units,
            "dtype": coord.dtype,
            **parsed,
        }
        return get_coord(**kwargs)

    def run(self, patch):
        """Apply the selected coordinate operation to one patch."""
        operation = str(self.operation or "rename_coords")
        available_dims = tuple(patch.dims)
        available_coords = tuple(patch.coords.coord_map)
        non_dim_coords = tuple(
            name for name in available_coords if name not in available_dims
        )

        if operation == "rename_coords":
            mapping = self._validate_mapping(
                self.rename_rows,
                valid_left=available_coords,
                valid_right=None,
                reject_duplicate_right=True,
            )
            return patch.rename_coords(**mapping)
        if operation == "drop_coords":
            selected = self._validate_selection(
                self.drop_coords_selected,
                non_dim_coords,
            )
            return patch if not selected else patch.drop_coords(*selected)
        if operation == "sort_coords":
            selected = self._validate_selection(
                self.sort_coords_selected,
                available_coords,
            )
            return (
                patch
                if not selected
                else patch.sort_coords(*selected, reverse=bool(self.sort_reverse))
            )
        if operation == "snap_coords":
            selected = self._validate_selection(
                self.snap_coords_selected,
                available_coords,
            )
            return (
                patch
                if not selected
                else patch.snap_coords(*selected, reverse=bool(self.snap_reverse))
            )
        if operation == "set_coords":
            if not self.set_coords_applied_dim:
                return patch
            return patch.update_coords(
                **{self.set_coords_applied_dim: self._resolved_coord(patch)}
            )
        if operation == "set_dims":
            mapping = self._validate_mapping(
                self.set_dims_rows,
                valid_left=available_dims,
                valid_right=available_coords,
                reject_duplicate_right=True,
            )
            return patch.set_dims(**mapping)
        if operation == "flip":
            selected = self._validate_selection(
                self.flip_dims_selected,
                available_coords,
            )
            if not selected or (not self.flip_data and not self.flip_coords):
                return patch
            dim_names = tuple(name for name in selected if name in available_dims)
            if self.flip_data and len(dim_names) != len(selected):
                invalid = [name for name in selected if name not in available_dims]
                raise ValueError(
                    "data flip requires dimension coordinates; "
                    f"non-dim coords selected: {', '.join(invalid)}"
                )
            out = patch
            if self.flip_data and dim_names:
                out = out.flip(*dim_names, flip_coords=False)
            if self.flip_coords:
                out = out.update(coords=out.coords.flip(*tuple(selected)))
            return out
        if operation == "transpose":
            order = list(self.transpose_order)
            dims = list(available_dims)
            if not order:
                return patch
            if sorted(order) != sorted(dims):
                raise ValueError("dimension order does not match the input patch")
            return patch.transpose(*order)
        raise ValueError(f"Unknown coords operation '{operation}'")


class Coords(ZugWidget):
    """Apply coordinate-structure operations to an input patch."""

    name = "Coords"
    description = "Apply coordinate operations to a patch"
    icon = "icons/Coords.svg"
    category = "Processing"
    keywords = (
        "coords",
        "coordinates",
        "flip",
        "rename",
        "transpose",
        "sort",
        "snap",
        "set_coords",
    )
    priority = 24.5

    operation = Setting("rename_coords")
    rename_rows = Setting([["", ""]])
    set_dims_rows = Setting([["", ""]])
    set_coords_dim = Setting("")
    set_coords_start = Setting("")
    set_coords_stop = Setting("")
    set_coords_step = Setting("")
    set_coords_applied_dim = Setting("")
    set_coords_applied_start = Setting("")
    set_coords_applied_stop = Setting("")
    set_coords_applied_step = Setting("")
    drop_coords_selected = Setting([])
    sort_coords_selected = Setting([])
    sort_reverse = Setting(False)
    snap_coords_selected = Setting([])
    snap_reverse = Setting(False)
    flip_dims_selected = Setting([])
    flip_data = Setting(True)
    flip_coords = Setting(True)
    transpose_order = Setting([])

    _OPERATIONS: ClassVar[tuple[tuple[str, str], ...]] = (
        ("rename_coords", "Rename"),
        ("drop_coords", "Drop"),
        ("sort_coords", "Sort"),
        ("snap_coords", "Snap"),
        ("set_coords", "Set Coords"),
        ("set_dims", "Set Dims"),
        ("flip", "Flip"),
        ("transpose", "Transpose"),
    )

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        invalid_operation = Msg("Unknown coords operation '{}'")
        invalid_mapping = Msg("Invalid {} settings: {}")
        invalid_selection = Msg("Invalid {} selection: {}")
        invalid_set_coords = Msg("Invalid set_coords settings: {}")
        operation_failed = Msg("Coords operation '{}' failed: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch, doc="Patch to modify")

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch, doc="Patch after coord operation")

    def __init__(self) -> None:
        super().__init__()
        self._patch: dc.Patch | None = None
        self._last_result: dc.Patch | None = None
        self._available_dims: tuple[str, ...] = ()
        self._available_coords: tuple[str, ...] = ()
        self._available_non_dim_coords: tuple[str, ...] = ()
        self._ui_sync = False

        box = gui.widgetBox(self.controlArea, "Parameters")
        gui.widgetLabel(box, "Operation:")
        self._operation_combo = QComboBox(box)
        self._operation_combo.addItems(label for _, label in self._OPERATIONS)
        box.layout().addWidget(self._operation_combo)

        self._stack = QStackedWidget(box)
        box.layout().addWidget(self._stack)
        self._stack.addWidget(self._build_rename_page())
        self._stack.addWidget(self._build_drop_page())
        self._stack.addWidget(self._build_sort_page())
        self._stack.addWidget(self._build_snap_page())
        self._stack.addWidget(self._build_set_coords_page())
        self._stack.addWidget(self._build_set_dims_page())
        self._stack.addWidget(self._build_flip_page())
        self._stack.addWidget(self._build_transpose_page())

        summary_panel = QWidget(self.mainArea)
        summary_layout = QFormLayout(summary_panel)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        summary_layout.setSpacing(6)
        self._input_label = QLabel("none", summary_panel)
        self._input_label.setWordWrap(True)
        self._active_label = QLabel("", summary_panel)
        self._active_label.setWordWrap(True)
        self._output_label = QLabel("none", summary_panel)
        self._output_label.setWordWrap(True)
        summary_layout.addRow("Input", self._input_label)
        summary_layout.addRow("Active", self._active_label)
        summary_layout.addRow("Output", self._output_label)
        self.mainArea.layout().addWidget(summary_panel)

        self._apply_settings_to_controls()
        self._rebind_dynamic_controls()
        preview = self._build_preview_state()
        self._input_label.setText(preview.input_text)
        self._active_label.setText(preview.active_text)
        self._output_label.setText(preview.output_text)

        self._operation_combo.currentTextChanged.connect(self._on_operation_changed)

    def _apply_settings_to_controls(self) -> None:
        """Hydrate visible controls from persisted widget settings."""
        operation = self._coerce_operation()
        self._set_current_operation_ui(operation)
        self._refresh_tables()
        self._refresh_coord_lists()
        self._refresh_transpose_list()

    def _sync_settings_from_controls(self) -> None:
        """Persist current control values back into widget settings.

        Coords already mirrors control edits into settings through targeted
        callbacks. Keeping this hook intentionally narrow avoids erasing invalid
        or not-yet-available saved values during input rebinding.
        """

    def _rebind_dynamic_controls(self) -> None:
        """Rebuild patch-dependent controls and reapply persisted values."""
        self._sync_patch_metadata()
        self._refresh_tables()
        self._refresh_coord_lists()
        self._refresh_transpose_list()

    def _build_rename_page(self) -> QWidget:
        """Return the page for coordinate renaming."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self._rename_table = self._build_mapping_table(("From", "To"))
        self._rename_table.itemChanged.connect(self._on_rename_table_changed)
        layout.addWidget(self._rename_table)
        layout.addLayout(
            self._build_table_buttons(
                self._rename_table,
                self._add_rename_row,
                self._remove_rename_row,
            )
        )
        return page

    def _build_drop_page(self) -> QWidget:
        """Return the page for dropping non-dimensional coordinates."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        gui.widgetLabel(page, "Coordinates:")
        self._drop_list = QListWidget(page)
        self._drop_list.itemChanged.connect(self._on_drop_list_changed)
        layout.addWidget(self._drop_list)
        return page

    def _build_sort_page(self) -> QWidget:
        """Return the page for sorting coordinates."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        gui.widgetLabel(page, "Coordinates:")
        self._sort_list = QListWidget(page)
        self._sort_list.itemChanged.connect(self._on_sort_list_changed)
        layout.addWidget(self._sort_list)
        self._sort_reverse_cb = QCheckBox("Reverse order", page)
        self._sort_reverse_cb.toggled.connect(self._on_sort_reverse_changed)
        layout.addWidget(self._sort_reverse_cb)
        return page

    def _build_snap_page(self) -> QWidget:
        """Return the page for snapping coordinates to regular spacing."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        gui.widgetLabel(page, "Coordinates:")
        self._snap_list = QListWidget(page)
        self._snap_list.itemChanged.connect(self._on_snap_list_changed)
        layout.addWidget(self._snap_list)
        self._snap_reverse_cb = QCheckBox("Reverse order", page)
        self._snap_reverse_cb.toggled.connect(self._on_snap_reverse_changed)
        layout.addWidget(self._snap_reverse_cb)
        return page

    def _build_set_dims_page(self) -> QWidget:
        """Return the page for remapping dimensions to coordinates."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        self._set_dims_table = self._build_mapping_table(("Dimension", "Coordinate"))
        self._set_dims_table.itemChanged.connect(self._on_set_dims_table_changed)
        layout.addWidget(self._set_dims_table)
        layout.addLayout(
            self._build_table_buttons(
                self._set_dims_table,
                self._add_set_dims_row,
                self._remove_set_dims_row,
            )
        )
        return page

    def _build_set_coords_page(self) -> QWidget:
        """Return the page for rebuilding one dimension coordinate."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)

        form = QFormLayout()
        self._set_coords_dim_combo = QComboBox(page)
        self._set_coords_dim_combo.currentTextChanged.connect(
            self._on_set_coords_dim_changed
        )
        form.addRow("Dimension", self._set_coords_dim_combo)

        self._set_coords_start_edit = QLineEdit(page)
        self._set_coords_start_edit.textEdited.connect(
            lambda text: self._on_set_coords_text_changed("start", text)
        )
        self._set_coords_start_edit.editingFinished.connect(self._apply_set_coords)
        form.addRow("Start", self._set_coords_start_edit)

        self._set_coords_stop_edit = QLineEdit(page)
        self._set_coords_stop_edit.textEdited.connect(
            lambda text: self._on_set_coords_text_changed("stop", text)
        )
        self._set_coords_stop_edit.editingFinished.connect(self._apply_set_coords)
        form.addRow("Stop", self._set_coords_stop_edit)

        self._set_coords_step_edit = QLineEdit(page)
        self._set_coords_step_edit.textEdited.connect(
            lambda text: self._on_set_coords_text_changed("step", text)
        )
        self._set_coords_step_edit.editingFinished.connect(self._apply_set_coords)
        form.addRow("Step", self._set_coords_step_edit)
        layout.addLayout(form)
        layout.addStretch(1)
        return page

    def _build_transpose_page(self) -> QWidget:
        """Return the page for transposing dimensions."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        gui.widgetLabel(page, "Dimension order:")
        self._transpose_list = QListWidget(page)
        self._transpose_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self._transpose_list.itemSelectionChanged.connect(
            self._update_transpose_button_state
        )
        layout.addWidget(self._transpose_list)

        buttons = QHBoxLayout()
        self._transpose_up_btn = QPushButton("Up", page)
        self._transpose_down_btn = QPushButton("Down", page)
        self._transpose_reset_btn = QPushButton("Reset", page)
        self._transpose_up_btn.clicked.connect(lambda: self._move_transpose_item(-1))
        self._transpose_down_btn.clicked.connect(lambda: self._move_transpose_item(1))
        self._transpose_reset_btn.clicked.connect(self._reset_transpose_order)
        buttons.addWidget(self._transpose_up_btn)
        buttons.addWidget(self._transpose_down_btn)
        buttons.addWidget(self._transpose_reset_btn)
        layout.addLayout(buttons)
        return page

    def _build_flip_page(self) -> QWidget:
        """Return the page for flipping data and/or coords along coordinates."""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        gui.widgetLabel(page, "Coordinates:")
        self._flip_list = QListWidget(page)
        self._flip_list.itemChanged.connect(self._on_flip_list_changed)
        layout.addWidget(self._flip_list)
        self._flip_data_cb = QCheckBox("Flip data", page)
        self._flip_data_cb.toggled.connect(self._on_flip_data_changed)
        layout.addWidget(self._flip_data_cb)
        self._flip_coords_cb = QCheckBox("Flip coordinate values", page)
        self._flip_coords_cb.toggled.connect(self._on_flip_coords_changed)
        layout.addWidget(self._flip_coords_cb)
        return page

    @staticmethod
    def _build_mapping_table(headers: tuple[str, str]) -> QTableWidget:
        """Create a compact two-column mapping table."""
        table = QTableWidget(0, 2)
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setStretchLastSection(True)
        table.verticalHeader().setVisible(False)
        table.setSelectionBehavior(QAbstractItemView.SelectRows)
        return table

    @staticmethod
    def _build_table_buttons(
        _table: QTableWidget,
        add_callback,
        remove_callback,
    ) -> QHBoxLayout:
        """Return add/remove buttons for a mapping table."""
        layout = QHBoxLayout()
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(add_callback)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(remove_callback)
        layout.addWidget(add_btn)
        layout.addWidget(remove_btn)
        layout.addStretch(1)
        return layout

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive an input patch and rerun the selected coordinate operation."""
        self._patch = patch
        self._sync_patch_metadata()
        self._rehydrate_set_coords_state()
        self._apply_settings_to_controls()
        self.run()

    def _sync_patch_metadata(self) -> None:
        """Sync patch-derived metadata used by both UI and run-time validation."""
        if self._patch is None:
            self._available_dims = ()
            self._available_coords = ()
            self._available_non_dim_coords = ()
        else:
            self._available_dims = tuple(self._patch.dims)
            self._available_coords = tuple(self._patch.coords.coord_map)
            self._available_non_dim_coords = tuple(
                name
                for name in self._available_coords
                if name not in self._available_dims
            )
        order = [dim for dim in self.transpose_order if dim in self._available_dims]
        seen = set(order)
        order.extend(dim for dim in self._available_dims if dim not in seen)
        self.transpose_order = order
        if self.set_coords_dim not in self._available_dims:
            self.set_coords_dim = (
                self._available_dims[0] if self._available_dims else ""
            )
        if (
            self.set_coords_applied_dim
            and self.set_coords_applied_dim not in self._available_dims
        ):
            self.set_coords_applied_dim = ""
            self.set_coords_applied_start = ""
            self.set_coords_applied_stop = ""
            self.set_coords_applied_step = ""

    def _rehydrate_set_coords_state(self) -> None:
        """Rebuild applied set-coords state from saved draft fields for this patch."""
        if self._patch is None or self._coerce_operation() != "set_coords":
            return

        if not any(
            value.strip()
            for value in (
                self.set_coords_start,
                self.set_coords_stop,
                self.set_coords_step,
            )
        ):
            self.set_coords_applied_dim = ""
            self.set_coords_applied_start = ""
            self.set_coords_applied_stop = ""
            self.set_coords_applied_step = ""
            return

        applied = self._validated_set_coords_applied_state()
        if applied is None:
            self.set_coords_applied_dim = ""
            self.set_coords_applied_start = ""
            self.set_coords_applied_stop = ""
            self.set_coords_applied_step = ""
            return

        (
            self.set_coords_applied_dim,
            self.set_coords_applied_start,
            self.set_coords_applied_stop,
            self.set_coords_applied_step,
        ) = applied

    def _refresh_ui(self) -> None:
        """Refresh all visible controls and summaries from current state."""
        self._apply_settings_to_controls()
        self._rebind_dynamic_controls()
        preview = self._build_preview_state(self._last_result)
        self._input_label.setText(preview.input_text)
        self._active_label.setText(preview.active_text)
        self._output_label.setText(preview.output_text)

    def _refresh_tables(self) -> None:
        """Push stored mapping rows into both mapping tables."""
        self._sync_table_rows(self._rename_table, self.rename_rows)
        self._sync_table_rows(self._set_dims_table, self.set_dims_rows)

    def _sync_table_rows(self, table: QTableWidget, rows: object) -> None:
        """Replace table contents from serialized settings rows."""
        normalized = self._normalize_rows(rows)
        self._ui_sync = True
        table.setRowCount(len(normalized))
        for row_num, (left, right) in enumerate(normalized):
            table.setItem(row_num, 0, QTableWidgetItem(left))
            table.setItem(row_num, 1, QTableWidgetItem(right))
        self._ui_sync = False

    def _refresh_coord_lists(self) -> None:
        """Push available coord choices and checked state into list widgets."""
        self._sync_checkable_list(
            self._drop_list,
            self._available_non_dim_coords,
            self.drop_coords_selected,
        )
        self._sync_checkable_list(
            self._sort_list,
            self._available_coords,
            self.sort_coords_selected,
        )
        self._sync_checkable_list(
            self._snap_list,
            self._available_coords,
            self.snap_coords_selected,
        )
        self._sync_checkable_list(
            self._flip_list,
            self._available_coords,
            self.flip_dims_selected,
        )
        self._sync_set_coords_controls()

        self._ui_sync = True
        self._sort_reverse_cb.setChecked(bool(self.sort_reverse))
        self._snap_reverse_cb.setChecked(bool(self.snap_reverse))
        self._flip_data_cb.setChecked(bool(self.flip_data))
        self._flip_coords_cb.setChecked(bool(self.flip_coords))
        self._ui_sync = False

    def _sync_set_coords_controls(self) -> None:
        """Push stored set-coords state into the form controls."""
        self._ui_sync = True
        self._set_coords_dim_combo.clear()
        self._set_coords_dim_combo.addItems(self._available_dims)
        if self.set_coords_dim in self._available_dims:
            self._set_combo_value(self._set_coords_dim_combo, self.set_coords_dim)
        elif self._available_dims:
            self._set_coords_dim_combo.setCurrentIndex(0)
        else:
            self._set_coords_dim_combo.setCurrentIndex(-1)
        self._set_line_edit_value(self._set_coords_start_edit, self.set_coords_start)
        self._set_line_edit_value(self._set_coords_stop_edit, self.set_coords_stop)
        self._set_line_edit_value(self._set_coords_step_edit, self.set_coords_step)
        enabled = bool(self._available_dims)
        self._set_coords_dim_combo.setEnabled(enabled)
        self._set_coords_start_edit.setEnabled(enabled)
        self._set_coords_stop_edit.setEnabled(enabled)
        self._set_coords_step_edit.setEnabled(enabled)
        self._ui_sync = False

    def _sync_checkable_list(
        self,
        widget: QListWidget,
        options: tuple[str, ...],
        selected: object,
    ) -> None:
        """Replace the items in a checkable list widget."""
        selected_set = {str(item) for item in (selected or [])}
        self._ui_sync = True
        widget.clear()
        for option in options:
            item = QListWidgetItem(option, widget)
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if option in selected_set else Qt.Unchecked)
        self._ui_sync = False

    @staticmethod
    def _checked_items(widget: QListWidget) -> list[str]:
        """Return checked item labels from one list widget."""
        return [
            widget.item(index).text()
            for index in range(widget.count())
            if widget.item(index).checkState() == Qt.Checked
        ]

    def _refresh_transpose_list(self) -> None:
        """Push the saved dimension order into the transpose list."""
        dims = self._available_dims
        order = [dim for dim in self.transpose_order if dim in dims]
        seen = set(order)
        order.extend(dim for dim in dims if dim not in seen)
        self.transpose_order = order

        self._ui_sync = True
        self._transpose_list.clear()
        self._transpose_list.addItems(order)
        if order:
            self._transpose_list.setCurrentRow(0)
        self._ui_sync = False
        self._update_transpose_button_state()

    def _coerce_operation(self) -> str:
        """Return the selected operation or reset to the default value."""
        names = [name for name, _ in self._OPERATIONS]
        if self.operation in names:
            return self.operation
        default = names[0]
        self._show_error_message("invalid_operation", self.operation)
        self.operation = default
        return default

    def _set_current_operation_ui(self, operation: str) -> None:
        """Select the current operation in the combo box and stack."""
        names = [name for name, _ in self._OPERATIONS]
        labels = [label for _, label in self._OPERATIONS]
        index = names.index(operation)
        self._ui_sync = True
        self._operation_combo.setCurrentText(labels[index])
        self._stack.setCurrentIndex(index)
        self._ui_sync = False

    def _on_operation_changed(self, label: str) -> None:
        """Persist the active operation and rerun."""
        if self._ui_sync:
            return
        label_to_name = {display: name for name, display in self._OPERATIONS}
        self.operation = label_to_name[label]
        self._stack.setCurrentIndex(
            [display for _, display in self._OPERATIONS].index(label)
        )
        self.run()

    def _add_rename_row(self) -> None:
        """Append a blank rename-mapping row."""
        rows = self._normalize_rows(self.rename_rows)
        rows.append(["", ""])
        self.rename_rows = rows
        self._sync_table_rows(self._rename_table, rows)

    def _remove_rename_row(self) -> None:
        """Remove the selected rename-mapping row."""
        self.rename_rows = self._remove_selected_table_row(
            self._rename_table,
            self.rename_rows,
        )
        self._sync_table_rows(self._rename_table, self.rename_rows)
        self.run()

    def _add_set_dims_row(self) -> None:
        """Append a blank set-dims row."""
        rows = self._normalize_rows(self.set_dims_rows)
        rows.append(["", ""])
        self.set_dims_rows = rows
        self._sync_table_rows(self._set_dims_table, rows)

    def _remove_set_dims_row(self) -> None:
        """Remove the selected set-dims row."""
        self.set_dims_rows = self._remove_selected_table_row(
            self._set_dims_table,
            self.set_dims_rows,
        )
        self._sync_table_rows(self._set_dims_table, self.set_dims_rows)
        self.run()

    @staticmethod
    def _remove_selected_table_row(
        table: QTableWidget,
        rows: object,
    ) -> list[list[str]]:
        """Remove the selected row from serialized table data."""
        normalized = Coords._normalize_rows(rows)
        row = table.currentRow()
        if row < 0:
            row = len(normalized) - 1
        if 0 <= row < len(normalized):
            normalized.pop(row)
        return normalized

    @staticmethod
    def _normalize_rows(rows: object) -> list[list[str]]:
        """Return a normalized list-of-two-strings representation."""
        output: list[list[str]] = []
        for row in rows or []:
            if isinstance(row, list | tuple) and len(row) >= 2:
                output.append([str(row[0]), str(row[1])])
        return output

    def _on_rename_table_changed(self, _item: QTableWidgetItem) -> None:
        """Persist rename table edits and rerun."""
        if self._ui_sync:
            return
        self.rename_rows = self._table_rows(self._rename_table)
        self.run()

    def _on_set_dims_table_changed(self, _item: QTableWidgetItem) -> None:
        """Persist set-dims table edits and rerun."""
        if self._ui_sync:
            return
        self.set_dims_rows = self._table_rows(self._set_dims_table)
        self.run()

    def _on_set_coords_dim_changed(self, value: str) -> None:
        """Persist the selected set-coords dimension and reapply draft values."""
        if self._ui_sync:
            return
        self.set_coords_dim = value
        self._request_ui_refresh()
        self._apply_set_coords()

    def _on_set_coords_text_changed(self, field: str, value: str) -> None:
        """Persist set-coords draft text without auto-running."""
        if self._ui_sync:
            return
        setattr(self, f"set_coords_{field}", value)
        self._request_ui_refresh()

    def _apply_set_coords(self) -> None:
        """Validate and apply the current sparse set-coords draft values."""
        if self._patch is None:
            return
        if not any(
            value.strip()
            for value in (
                self.set_coords_start,
                self.set_coords_stop,
                self.set_coords_step,
            )
        ):
            self.set_coords_applied_dim = ""
            self.set_coords_applied_start = ""
            self.set_coords_applied_stop = ""
            self.set_coords_applied_step = ""
            self._request_ui_refresh()
            self.run()
            return
        applied = self._validated_set_coords_applied_state()
        if applied is None:
            self._request_ui_refresh()
            return

        (
            self.set_coords_applied_dim,
            self.set_coords_applied_start,
            self.set_coords_applied_stop,
            self.set_coords_applied_step,
        ) = applied
        self._request_ui_refresh()
        self.run()

    @staticmethod
    def _table_rows(table: QTableWidget) -> list[list[str]]:
        """Serialize all table rows to plain strings."""
        rows: list[list[str]] = []
        for row_num in range(table.rowCount()):
            left_item = table.item(row_num, 0)
            right_item = table.item(row_num, 1)
            rows.append(
                [
                    left_item.text() if left_item is not None else "",
                    right_item.text() if right_item is not None else "",
                ]
            )
        return rows

    def _on_drop_list_changed(self, _item: QListWidgetItem) -> None:
        """Persist drop selections and rerun."""
        if self._ui_sync:
            return
        self.drop_coords_selected = self._checked_items(self._drop_list)
        self.run()

    def _on_sort_list_changed(self, _item: QListWidgetItem) -> None:
        """Persist sort selections and rerun."""
        if self._ui_sync:
            return
        self.sort_coords_selected = self._checked_items(self._sort_list)
        self.run()

    def _on_snap_list_changed(self, _item: QListWidgetItem) -> None:
        """Persist snap selections and rerun."""
        if self._ui_sync:
            return
        self.snap_coords_selected = self._checked_items(self._snap_list)
        self.run()

    def _on_flip_list_changed(self, _item: QListWidgetItem) -> None:
        """Persist flip selections and rerun."""
        if self._ui_sync:
            return
        self.flip_dims_selected = self._checked_items(self._flip_list)
        self.run()

    def _on_flip_data_changed(self, value: bool) -> None:
        """Persist the flip-data flag and rerun."""
        if self._ui_sync:
            return
        self.flip_data = bool(value)
        self.run()

    def _on_sort_reverse_changed(self, value: bool) -> None:
        """Persist the sort reverse flag and rerun."""
        if self._ui_sync:
            return
        self.sort_reverse = bool(value)
        self.run()

    def _on_snap_reverse_changed(self, value: bool) -> None:
        """Persist the snap reverse flag and rerun."""
        if self._ui_sync:
            return
        self.snap_reverse = bool(value)
        self.run()

    def _on_flip_coords_changed(self, value: bool) -> None:
        """Persist the flip-coords flag and rerun."""
        if self._ui_sync:
            return
        self.flip_coords = bool(value)
        self.run()

    @staticmethod
    def _checked_items(widget: QListWidget) -> list[str]:
        """Return the currently checked item texts."""
        selected: list[str] = []
        for index in range(widget.count()):
            item = widget.item(index)
            if item.checkState() == Qt.Checked:
                selected.append(item.text())
        return selected

    def _move_transpose_item(self, delta: int) -> None:
        """Move the selected transpose item up or down."""
        row = self._transpose_list.currentRow()
        target = row + delta
        if row < 0 or target < 0 or target >= self._transpose_list.count():
            return
        item = self._transpose_list.takeItem(row)
        self._transpose_list.insertItem(target, item)
        self._transpose_list.setCurrentRow(target)
        self.transpose_order = self._transpose_items()
        self.run()

    def _reset_transpose_order(self) -> None:
        """Reset transpose order to the input patch dimension order."""
        self.transpose_order = list(self._available_dims)
        self._refresh_transpose_list()
        self.run()

    def _update_transpose_button_state(self) -> None:
        """Enable transpose move buttons only when the selection can move."""
        row = self._transpose_list.currentRow()
        count = self._transpose_list.count()
        self._transpose_up_btn.setEnabled(row > 0)
        self._transpose_down_btn.setEnabled(0 <= row < count - 1)
        self._transpose_reset_btn.setEnabled(bool(count))

    def _transpose_items(self) -> list[str]:
        """Return the current transpose list order."""
        return [
            self._transpose_list.item(index).text()
            for index in range(self._transpose_list.count())
        ]

    def _supports_async_execution(self) -> bool:
        """Run coordinate operations off-thread by default."""
        return True

    def _build_execution_request(self) -> WidgetExecutionRequest | None:
        """Build one coordinate-operation execution request."""
        patch = self._patch
        if patch is None:
            return None
        return self._build_task_execution_request(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    def _handle_execution_exception(self, exc: Exception) -> None:
        """Route worker failures to the coordinate-operation banner."""
        self._show_exception(
            "operation_failed",
            exc,
            self._operation_label(self._coerce_operation()),
        )

    def _run(self) -> dc.Patch | None:
        """Apply the active coordinate operation to the current patch."""
        patch = self._patch
        if patch is None:
            return None
        return self._execute_workflow_object(
            self._validated_task(),
            input_values={"patch": patch},
            output_names=("patch",),
        )

    def _validated_task(self) -> CoordsTask | None:
        """Return the current validated coordinate task, or None on invalid state."""
        operation = self._coerce_operation()
        self._set_current_operation_ui(operation)
        if operation == "rename_coords":
            mapping = self._validated_mapping(
                self.rename_rows,
                label="rename",
                valid_left=self._available_coords,
                valid_right=None,
                reject_duplicate_right=True,
            )
            if mapping is None:
                return None
            rename_rows = tuple(mapping.items())
            return CoordsTask(operation=operation, rename_rows=rename_rows)
        if operation == "drop_coords":
            selected = self._validated_selection(
                self.drop_coords_selected,
                self._available_non_dim_coords,
                label="drop",
            )
            if selected is None:
                return None
            return CoordsTask(
                operation=operation,
                drop_coords_selected=tuple(selected),
            )
        if operation == "sort_coords":
            selected = self._validated_selection(
                self.sort_coords_selected,
                self._available_coords,
                label="sort",
            )
            if selected is None:
                return None
            return CoordsTask(
                operation=operation,
                sort_coords_selected=tuple(selected),
                sort_reverse=bool(self.sort_reverse),
            )
        if operation == "snap_coords":
            selected = self._validated_selection(
                self.snap_coords_selected,
                self._available_coords,
                label="snap",
            )
            if selected is None:
                return None
            return CoordsTask(
                operation=operation,
                snap_coords_selected=tuple(selected),
                snap_reverse=bool(self.snap_reverse),
            )
        if operation == "set_coords":
            if not self.set_coords_applied_dim:
                return CoordsTask(operation=operation)
            coord = self._validated_set_coords_coord()
            if coord is None:
                return None
            return CoordsTask(
                operation=operation,
                set_coords_applied_dim=str(self.set_coords_applied_dim or ""),
                set_coords_applied_start=str(self.set_coords_applied_start or ""),
                set_coords_applied_stop=str(self.set_coords_applied_stop or ""),
                set_coords_applied_step=str(self.set_coords_applied_step or ""),
            )
        if operation == "set_dims":
            mapping = self._validated_mapping(
                self.set_dims_rows,
                label="set_dims",
                valid_left=self._available_dims,
                valid_right=self._available_coords,
                reject_duplicate_right=True,
            )
            if mapping is None:
                return None
            return CoordsTask(
                operation=operation,
                set_dims_rows=tuple(mapping.items()),
            )
        if operation == "flip":
            selected = self._validated_selection(
                self.flip_dims_selected,
                self._available_coords,
                label="flip",
            )
            if selected is None:
                return None
            return CoordsTask(
                operation=operation,
                flip_dims_selected=tuple(selected),
                flip_data=bool(self.flip_data),
                flip_coords=bool(self.flip_coords),
            )
        order = self._validated_transpose_order()
        if order is None:
            return None
        return CoordsTask(
            operation=operation,
            transpose_order=tuple(order),
        )

    def _task_snapshot(self) -> CoordsTask:
        """Return the stored coordinate-operation state without patch validation."""
        operation = self._coerce_operation()
        return CoordsTask(
            operation=operation,
            rename_rows=tuple(
                (str(left), str(right))
                for left, right in self._normalize_rows(self.rename_rows)
            ),
            set_dims_rows=tuple(
                (str(left), str(right))
                for left, right in self._normalize_rows(self.set_dims_rows)
            ),
            set_coords_applied_dim=str(self.set_coords_applied_dim or ""),
            set_coords_applied_start=str(self.set_coords_applied_start or ""),
            set_coords_applied_stop=str(self.set_coords_applied_stop or ""),
            set_coords_applied_step=str(self.set_coords_applied_step or ""),
            drop_coords_selected=tuple(self.drop_coords_selected or ()),
            sort_coords_selected=tuple(self.sort_coords_selected or ()),
            sort_reverse=bool(self.sort_reverse),
            snap_coords_selected=tuple(self.snap_coords_selected or ()),
            snap_reverse=bool(self.snap_reverse),
            flip_dims_selected=tuple(self.flip_dims_selected or ()),
            flip_data=bool(self.flip_data),
            flip_coords=bool(self.flip_coords),
            transpose_order=tuple(self.transpose_order or ()),
        )

    def _validated_mapping(
        self,
        rows: object,
        *,
        label: str,
        valid_left: tuple[str, ...],
        valid_right: tuple[str, ...] | None,
        reject_duplicate_right: bool,
    ) -> dict[str, str] | None:
        """Validate mapping-table rows and return kwargs for DASCore."""
        mapping: dict[str, str] = {}
        used_right: set[str] = set()
        valid_left_set = set(valid_left)
        valid_right_set = None if valid_right is None else set(valid_right)

        for left, right in self._normalize_rows(rows):
            left = left.strip()
            right = right.strip()
            if not left and not right:
                continue
            if not left or not right:
                self._show_error_message(
                    "invalid_mapping",
                    label,
                    "both columns must be filled",
                )
                return None
            if left not in valid_left_set:
                self._show_error_message(
                    "invalid_mapping",
                    label,
                    f"'{left}' is not available",
                )
                return None
            if valid_right_set is not None and right not in valid_right_set:
                self._show_error_message(
                    "invalid_mapping",
                    label,
                    f"'{right}' is not available",
                )
                return None
            if left in mapping:
                self._show_error_message(
                    "invalid_mapping",
                    label,
                    f"duplicate source '{left}'",
                )
                return None
            if reject_duplicate_right and right in used_right:
                self._show_error_message(
                    "invalid_mapping",
                    label,
                    f"duplicate target '{right}'",
                )
                return None
            mapping[left] = right
            used_right.add(right)

        if not mapping:
            self._show_error_message(
                "invalid_mapping",
                label,
                "at least one mapping is required",
            )
            return None
        return mapping

    def _validated_selection(
        self,
        selected: object,
        valid: tuple[str, ...],
        *,
        label: str,
    ) -> list[str] | None:
        """Validate serialized coord-name selections."""
        selected_names = [str(item) for item in (selected or [])]
        valid_set = set(valid)
        invalid = [name for name in selected_names if name not in valid_set]
        if invalid:
            self._show_error_message(
                "invalid_selection",
                label,
                ", ".join(invalid),
            )
            return None
        return selected_names

    def _validated_transpose_order(self) -> list[str] | None:
        """Validate the transpose dimension order against the input patch."""
        order = list(self.transpose_order)
        dims = list(self._available_dims)
        if not dims:
            return []
        if sorted(order) != sorted(dims):
            self._show_error_message(
                "invalid_selection",
                "transpose",
                "dimension order does not match the input patch",
            )
            return None
        self.transpose_order = order
        return order

    def _apply_flip(self, selected: list[str]) -> dc.Patch:
        """Apply the configured flip behavior to data and/or coordinates."""
        assert self._patch is not None
        coord_names = tuple(selected)
        dim_names = tuple(name for name in coord_names if name in self._available_dims)

        if self.flip_data and len(dim_names) != len(coord_names):
            invalid = [name for name in coord_names if name not in self._available_dims]
            raise ValueError(
                "data flip requires dimension coordinates; "
                f"non-dim coords selected: {', '.join(invalid)}"
            )

        patch = self._patch
        if self.flip_data and dim_names:
            patch = patch.flip(*dim_names, flip_coords=False)
        if self.flip_coords:
            patch = patch.update(coords=patch.coords.flip(*coord_names))
        return patch

    def _validated_set_coords_coord(self):
        """Return the replacement coordinate resolved from sparse applied state."""
        dim = self.set_coords_applied_dim
        if dim not in self._available_dims:
            self._show_error_message(
                "invalid_set_coords",
                f"'{dim}' is not an available dimension",
            )
            return None

        coord = self._patch.coords.get_coord(dim)
        axis_len = self._patch.shape[self._available_dims.index(dim)]
        sparse_values = self._parse_set_coords_values(
            self.set_coords_applied_start,
            self.set_coords_applied_stop,
            self.set_coords_applied_step,
            coord,
        )
        if sparse_values is None:
            return None

        kwargs = {
            "shape": axis_len,
            "units": coord.units,
            "dtype": coord.dtype,
            **self._completed_set_coords_kwargs(sparse_values, coord),
        }
        try:
            return get_coord(**kwargs)
        except Exception as exc:
            self._show_error_message("invalid_set_coords", str(exc))
            return None

    def _validated_set_coords_applied_state(
        self,
    ) -> tuple[str, str, str, str] | None:
        """Validate the current draft values and return sparse applied state."""
        dim = self.set_coords_dim
        if dim not in self._available_dims:
            self._show_error_message("invalid_set_coords", "select a valid dimension")
            return None

        coord = self._patch.coords.get_coord(dim)
        sparse_values = self._parse_set_coords_values(
            self.set_coords_start,
            self.set_coords_stop,
            self.set_coords_step,
            coord,
        )
        if sparse_values is None:
            return None
        if not sparse_values:
            self._show_error_message(
                "invalid_set_coords",
                "at least one of start, stop, and step is required",
            )
            return None
        return (
            dim,
            self.set_coords_start.strip(),
            self.set_coords_stop.strip(),
            self.set_coords_step.strip(),
        )

    def _parse_set_coords_values(
        self,
        start_text: str,
        stop_text: str,
        step_text: str,
        coord,
    ) -> dict[str, object] | None:
        """Parse sparse set-coords text values for one dimension."""
        parsed: dict[str, object] = {}
        raw_values = {
            "start": str(start_text).strip(),
            "stop": str(stop_text).strip(),
            "step": str(step_text).strip(),
        }
        for label, raw in raw_values.items():
            if not raw:
                continue
            sample = getattr(coord, label)
            value = self._parse_set_coords_value(raw, sample, label)
            if value is None:
                return None
            parsed[label] = value
        return parsed

    @staticmethod
    def _completed_set_coords_kwargs(
        sparse_values: dict[str, object],
        coord,
    ) -> dict[str, object]:
        """Fill single-field set-coords updates from the current coordinate."""
        names = set(sparse_values)
        if names == {"start"}:
            return {"start": sparse_values["start"], "step": coord.step}
        if names == {"stop"}:
            return {"stop": sparse_values["stop"], "step": coord.step}
        if names == {"step"}:
            return {"start": coord.start, "step": sparse_values["step"]}
        return dict(sparse_values)

    def _parse_set_coords_value(
        self,
        text: str,
        sample: object,
        label: str,
    ) -> object | None:
        """Parse one optional set-coords draft/applied value."""
        try:
            return parse_coord_text_value(str(text), sample, None)
        except Exception as exc:
            self._show_error_message(
                "invalid_set_coords",
                f"could not parse {label}: {exc}",
            )
            return None

    def _on_result(self, result: dc.Patch | None) -> None:
        """Send the output patch and refresh the textual preview."""
        self._last_result = result
        self.Outputs.patch.send(result)
        self._request_ui_refresh()

    def _build_preview_state(
        self, result: dc.Patch | None = None
    ) -> _CoordsPreviewState:
        """Return the current main-area summary text without touching Qt."""
        if self._patch is None:
            return _CoordsPreviewState(
                input_text="none",
                active_text=self._active_summary(),
                output_text="none",
            )
        return _CoordsPreviewState(
            input_text=self._patch_summary(self._patch),
            active_text=self._active_summary(),
            output_text="none" if result is None else self._patch_summary(result),
        )

    @staticmethod
    def _patch_summary(patch: dc.Patch) -> str:
        """Return a compact description of patch dims and coords."""
        dims = ", ".join(patch.dims) or "-"
        coords = ", ".join(tuple(patch.coords.coord_map)) or "-"
        return f"dims={dims}; coords={coords}"

    def _active_summary(self) -> str:
        """Return a compact summary of the active operation parameters."""
        operation = self._coerce_operation()
        if operation == "rename_coords":
            rows = [
                f"{left}->{right}"
                for left, right in self._normalize_rows(self.rename_rows)
                if left and right
            ]
            return "Rename: " + (", ".join(rows) if rows else "no mappings")
        if operation == "drop_coords":
            selected = ", ".join(self.drop_coords_selected) or "none"
            return f"Drop: {selected}"
        if operation == "sort_coords":
            selected = ", ".join(self.sort_coords_selected) or "none"
            suffix = ", reverse" if bool(self.sort_reverse) else ""
            return f"Sort: {selected}{suffix}"
        if operation == "snap_coords":
            selected = ", ".join(self.snap_coords_selected) or "none"
            suffix = ", reverse" if bool(self.snap_reverse) else ""
            return f"Snap: {selected}{suffix}"
        if operation == "set_coords":
            if not self.set_coords_applied_dim:
                return "Set coords: no applied values"
            values = []
            if self.set_coords_applied_start.strip():
                values.append(f"start={self.set_coords_applied_start}")
            if self.set_coords_applied_stop.strip():
                values.append(f"stop={self.set_coords_applied_stop}")
            if self.set_coords_applied_step.strip():
                values.append(f"step={self.set_coords_applied_step}")
            suffix = " ".join(values) if values else "no applied values"
            return f"Set coords: {self.set_coords_applied_dim} {suffix}".strip()
        if operation == "set_dims":
            rows = [
                f"{left}->{right}"
                for left, right in self._normalize_rows(self.set_dims_rows)
                if left and right
            ]
            return "Set dims: " + (", ".join(rows) if rows else "no mappings")
        if operation == "flip":
            selected = ", ".join(self.flip_dims_selected) or "none"
            modes = []
            if bool(self.flip_data):
                modes.append("data")
            if bool(self.flip_coords):
                modes.append("coords")
            suffix = ", ".join(modes) if modes else "none"
            return f"Flip: {selected} ({suffix})"
        order = ", ".join(self.transpose_order) or "none"
        return f"Transpose: {order}"

    def get_task(self) -> Task:
        """Return the current coordinate-operation semantics as a workflow task."""
        self._sync_settings_from_controls()
        return self._task_snapshot()

    @classmethod
    def _operation_label(cls, operation: str) -> str:
        """Return the display label for a stored operation name."""
        return dict(cls._OPERATIONS).get(operation, operation)


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(Coords).run()
