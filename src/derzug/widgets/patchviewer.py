"""Interactive patch inspector widget."""

from __future__ import annotations

import warnings
from dataclasses import dataclass

import dascore as dc
import numpy as np
import pyqtgraph as pg
from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import (
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)
from Orange.widgets.utils.signals import Input, Output
from Orange.widgets.widget import Msg

from derzug.core.zugwidget import ZugWidget
from derzug.utils.display import format_display
from derzug.workflow import Task
from derzug.workflow.widget_tasks import PatchPassThroughTask


@dataclass(frozen=True)
class _NodeDescriptor:
    """Metadata for one visible patch tree node."""

    path: str
    kind: str
    label: str
    value: object
    shape: tuple[int, ...] = ()
    dtype: str = ""
    plot_title: str = ""
    x_label: str = "Sample"
    y_label: str = "Value"
    summary: str = ""


class PatchViewer(ZugWidget):
    """Inspect patch structure and preview selected arrays."""

    name = "PatchViewer"
    description = "Inspect a DAS patch and preview its arrays"
    want_control_area = False
    icon = "icons/PatchViewer.svg"
    category = "Visualize"
    keywords = ("patch", "viewer", "inspect", "coords", "attrs")
    priority = 22

    class Error(ZugWidget.Error):
        """Errors shown by the widget."""

        invalid_patch = Msg("Could not preview patch item: {}")

    class Inputs:
        """Input signal definitions."""

        patch = Input("Patch", dc.Patch)

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def __init__(self) -> None:
        super().__init__()
        self._patch: dc.Patch | None = None
        self._preview_mode = "empty"
        self._current_descriptor: _NodeDescriptor | None = None
        self._default_item: QTreeWidgetItem | None = None
        self._items_by_path: dict[str, QTreeWidgetItem] = {}
        self._expanded_paths: set[str] = {"patch", "attrs", "coords"}

        splitter = QSplitter(Qt.Horizontal, self.mainArea)
        self.mainArea.layout().addWidget(splitter)

        tree_panel = self._build_tree_panel(splitter)

        preview_panel = self._build_preview_panel(splitter)

        splitter.addWidget(tree_panel)
        splitter.addWidget(preview_panel)
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([260, 740])

        self._tree.currentItemChanged.connect(self._on_current_item_changed)
        self._tree.itemExpanded.connect(self._remember_expanded_paths)
        self._tree.itemCollapsed.connect(self._remember_expanded_paths)
        self._show_empty_preview("No patch loaded")

    def _build_tree_panel(self, parent: QWidget) -> QWidget:
        """Create the searchable left-hand tree panel."""
        panel = QWidget(parent)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        self._tree_filter = QLineEdit(panel)
        self._tree_filter.setPlaceholderText("Filter patch items")
        self._tree_filter.textChanged.connect(self._apply_tree_filter)

        tree = QTreeWidget(panel)
        tree.setHeaderLabels(("Patch Item", "Summary"))
        tree.setUniformRowHeights(True)
        tree.setAlternatingRowColors(True)
        tree.setRootIsDecorated(True)
        tree.setColumnWidth(0, 180)
        header = tree.header()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self._tree = tree

        layout.addWidget(self._tree_filter, 0)
        layout.addWidget(tree, 1)
        return panel

    def _build_preview_panel(self, parent: QWidget) -> QWidget:
        """Create the right-hand preview and details panel."""
        preview_panel = QWidget(parent)
        preview_layout = QVBoxLayout(preview_panel)
        preview_layout.setContentsMargins(0, 0, 0, 0)
        preview_layout.setSpacing(8)

        self._preview_header = QLabel("", preview_panel)
        self._preview_header.setWordWrap(True)
        self._preview_header.setTextFormat(Qt.RichText)

        self._stats_label = QLabel("", preview_panel)
        self._stats_label.setWordWrap(True)
        self._stats_label.setStyleSheet("color: palette(mid);")

        self._preview_stack = QStackedWidget(preview_panel)
        self._empty_label = QLabel("No patch loaded", self._preview_stack)
        self._empty_label.setAlignment(Qt.AlignCenter)
        self._empty_label.setWordWrap(True)

        self._summary_label = QLabel("", self._preview_stack)
        self._summary_label.setAlignment(Qt.AlignCenter)
        self._summary_label.setWordWrap(True)

        self._line_plot = pg.PlotWidget(self._preview_stack, background="w")
        self._line_plot_item = self._line_plot.getPlotItem()
        self._line_plot_item.showGrid(x=True, y=True, alpha=0.2)
        self._line_curve = pg.PlotCurveItem(
            pen=pg.mkPen(color=(20, 20, 20, 255), width=2)
        )
        self._line_plot_item.addItem(self._line_curve)

        self._image_page = QWidget(self._preview_stack)
        image_layout = QHBoxLayout(self._image_page)
        image_layout.setContentsMargins(0, 0, 0, 0)
        image_layout.setSpacing(8)

        self._image_plot = pg.PlotWidget(self._image_page)
        self._image_plot_item = self._image_plot.getPlotItem()
        self._image_plot_item.showGrid(x=True, y=True, alpha=0.2)
        self._image_item = pg.ImageItem(axisOrder="row-major")
        self._image_plot_item.addItem(self._image_item)
        self._image_lut = pg.HistogramLUTWidget(self._image_page)
        self._image_lut.setImageItem(self._image_item)

        image_layout.addWidget(self._image_plot, 1)
        image_layout.addWidget(self._image_lut, 0)

        self._preview_stack.addWidget(self._empty_label)
        self._preview_stack.addWidget(self._summary_label)
        self._preview_stack.addWidget(self._line_plot)
        self._preview_stack.addWidget(self._image_page)

        self._details = QPlainTextEdit(preview_panel)
        self._details.setReadOnly(True)
        self._details.setPlaceholderText("Select a patch item to inspect it.")

        preview_layout.addWidget(self._preview_header, 0)
        preview_layout.addWidget(self._stats_label, 0)
        preview_layout.addWidget(self._preview_stack, 1)
        preview_layout.addWidget(self._details, 0)
        return preview_panel

    @Inputs.patch
    def set_patch(self, patch: dc.Patch | None) -> None:
        """Receive a patch, rebuild the tree, and forward it unchanged."""
        self.Error.clear()
        self._patch = patch
        self._request_ui_refresh()
        if patch is None:
            self.Outputs.patch.send(None)
            return
        self.Outputs.patch.send(patch)

    def get_task(self) -> Task:
        """Return the compiled workflow representation for PatchViewer."""
        return PatchPassThroughTask()

    def _refresh_ui(self) -> None:
        """Rebuild the visible tree and preview for the current patch."""
        self._rebuild_tree()
        if self._patch is None:
            self._show_empty_preview("No patch loaded")

    def _rebuild_tree(self) -> None:
        """Rebuild the tree model from the current patch."""
        preferred_path = (
            self._current_descriptor.path
            if self._current_descriptor is not None
            else None
        )
        self._tree.blockSignals(True)
        self._tree.clear()
        self._default_item = None
        self._items_by_path.clear()

        if self._patch is None:
            self._tree.blockSignals(False)
            self._details.clear()
            return

        root = self._build_root_node()
        self._add_patch_metadata_nodes(root)
        self._add_attrs_branch(root)
        self._add_coords_branch(root)
        self._add_data_node(root)

        root.setExpanded(True)
        self._restore_tree_state()
        target_item = self._resolve_target_item(preferred_path) or root
        self._tree.setCurrentItem(target_item)
        self._tree.blockSignals(False)
        self._apply_tree_filter(self._tree_filter.text())
        self._on_current_item_changed(target_item, None)

    def _build_root_node(self) -> QTreeWidgetItem:
        """Create the root patch node."""
        assert self._patch is not None
        return self._add_node(
            None,
            _NodeDescriptor(
                path="patch",
                kind="patch",
                label="Patch",
                value=self._patch,
                shape=tuple(int(x) for x in getattr(self._patch, "shape", ())),
                plot_title="Patch",
                summary=f"dims={self._patch.dims} shape={self._patch.shape}",
            ),
        )

    def _add_patch_metadata_nodes(self, root: QTreeWidgetItem) -> None:
        """Add the fixed scalar metadata nodes under the root."""
        assert self._patch is not None
        data_dtype = str(np.asarray(self._patch.data).dtype)
        descriptors = (
            _NodeDescriptor(
                path="dims",
                kind="scalar",
                label="dims",
                value=self._patch.dims,
                summary=", ".join(map(str, self._patch.dims)),
            ),
            _NodeDescriptor(
                path="shape",
                kind="scalar",
                label="shape",
                value=tuple(self._patch.shape),
                summary=str(tuple(self._patch.shape)),
            ),
            _NodeDescriptor(
                path="dtype",
                kind="scalar",
                label="dtype",
                value=data_dtype,
                summary=data_dtype,
            ),
        )
        for descriptor in descriptors:
            self._add_node(root, descriptor)

    def _add_attrs_branch(self, root: QTreeWidgetItem) -> QTreeWidgetItem:
        """Add the attrs branch and its children."""
        assert self._patch is not None
        attrs_items = sorted(self._patch.attrs.items(), key=lambda item: str(item[0]))
        attrs_item = self._add_node(
            root,
            _NodeDescriptor(
                path="attrs",
                kind="group",
                label="attrs",
                value=self._patch.attrs,
                summary=f"{len(attrs_items)} entries",
            ),
        )
        for key, value in attrs_items:
            self._add_node(
                attrs_item,
                _NodeDescriptor(
                    path=f"attrs.{key}",
                    kind="scalar",
                    label=str(key),
                    value=value,
                    summary=self._summarize_scalar(value),
                ),
            )
        return attrs_item

    def _add_coords_branch(self, root: QTreeWidgetItem) -> QTreeWidgetItem:
        """Add the coords branch and its array children."""
        assert self._patch is not None
        coords_item = self._add_node(
            root,
            _NodeDescriptor(
                path="coords",
                kind="group",
                label="coords",
                value=self._patch.dims,
                summary=f"{len(self._patch.dims)} arrays",
            ),
        )
        for dim in self._patch.dims:
            values = np.asarray(self._patch.get_array(dim))
            self._add_node(coords_item, self._coord_descriptor(dim, values))
        return coords_item

    def _coord_descriptor(self, dim: str, values: np.ndarray) -> _NodeDescriptor:
        """Build a descriptor for one coordinate array."""
        return _NodeDescriptor(
            path=f"coords.{dim}",
            kind="array",
            label=str(dim),
            value=values,
            shape=tuple(int(x) for x in values.shape),
            dtype=str(values.dtype),
            plot_title=f"Coord: {dim}",
            y_label=str(dim),
            summary=self._format_array_summary(values),
        )

    def _add_data_node(self, root: QTreeWidgetItem) -> None:
        """Add the main patch data node and mark it as the default preview."""
        assert self._patch is not None
        data = np.asarray(self._patch.data)
        self._default_item = self._add_node(
            root,
            _NodeDescriptor(
                path="data",
                kind="array",
                label="data",
                value=data,
                shape=tuple(int(x) for x in data.shape),
                dtype=str(data.dtype),
                plot_title="Patch data",
                x_label=self._patch.dims[-1] if self._patch.dims else "Sample",
                y_label=self._patch.dims[0] if self._patch.dims else "Trace",
                summary=self._format_array_summary(data),
            ),
        )

    def _resolve_target_item(
        self, preferred_path: str | None
    ) -> QTreeWidgetItem | None:
        """Resolve the preferred selection after rebuilding the tree."""
        if preferred_path:
            preferred_item = self._items_by_path.get(preferred_path)
            if preferred_item is not None:
                return preferred_item
        return self._default_item

    def _add_node(
        self,
        parent: QTreeWidgetItem | None,
        descriptor: _NodeDescriptor,
    ) -> QTreeWidgetItem:
        """Create one tree item and attach its descriptor."""
        item = QTreeWidgetItem([descriptor.label, descriptor.summary])
        item.setData(0, Qt.ItemDataRole.UserRole, descriptor)
        item.setIcon(0, self._icon_for_descriptor(descriptor))
        self._items_by_path[descriptor.path] = item
        if parent is None:
            self._tree.addTopLevelItem(item)
        else:
            parent.addChild(item)
        return item

    def _on_current_item_changed(
        self,
        current: QTreeWidgetItem | None,
        _previous: QTreeWidgetItem | None,
    ) -> None:
        """Preview the descriptor attached to the selected tree item."""
        if current is None:
            self._show_empty_preview("Select a patch item to preview it.")
            return
        descriptor = current.data(0, Qt.ItemDataRole.UserRole)
        if not isinstance(descriptor, _NodeDescriptor):
            self._show_empty_preview("Select a patch item to preview it.")
            return
        self._current_descriptor = descriptor
        self._render_descriptor(descriptor)

    def _render_descriptor(self, descriptor: _NodeDescriptor) -> None:
        """Render one descriptor in the preview area."""
        self.Error.clear()
        self._preview_header.setText(self._format_preview_header(descriptor))
        self._stats_label.setText(self._format_stats_label(descriptor))
        self._details.setPlainText(self._format_details(descriptor))
        if descriptor.kind != "array":
            self._show_summary_preview(descriptor)
            return
        values = np.asarray(descriptor.value)
        try:
            if values.ndim == 1:
                self._show_line_preview(values, descriptor)
                return
            if values.ndim == 2:
                self._show_image_preview(values, descriptor)
                return
            self._show_summary_preview(descriptor)
        except Exception as exc:
            self._show_exception("invalid_patch", exc)
            self._show_summary_preview(descriptor)

    def _show_line_preview(
        self,
        values: np.ndarray,
        descriptor: _NodeDescriptor,
    ) -> None:
        """Render a 1D array preview."""
        y_values = self._coerce_plot_axis(values)
        x_values = np.arange(values.size, dtype=np.float64)
        self._line_curve.setData(x_values, y_values)
        self._line_plot_item.setTitle(descriptor.plot_title or descriptor.label)
        self._line_plot_item.setLabel("bottom", "Sample")
        self._line_plot_item.setLabel("left", descriptor.y_label or "Value")
        self._line_plot_item.vb.enableAutoRange(x=True, y=True)
        self._line_plot_item.vb.autoRange()
        self._preview_stack.setCurrentWidget(self._line_plot)
        self._preview_mode = "line"

    def _show_image_preview(
        self,
        values: np.ndarray,
        descriptor: _NodeDescriptor,
    ) -> None:
        """Render a 2D array preview."""
        self._image_item.setImage(values, autoLevels=True)
        self._image_plot_item.setTitle(descriptor.plot_title or descriptor.label)
        self._image_plot_item.setLabel("bottom", descriptor.x_label or "Sample")
        self._image_plot_item.setLabel("left", descriptor.y_label or "Trace")
        self._image_plot_item.vb.enableAutoRange(x=True, y=True)
        self._image_plot_item.vb.autoRange()
        self._preview_stack.setCurrentWidget(self._image_page)
        self._preview_mode = "image"

    def _show_summary_preview(self, descriptor: _NodeDescriptor) -> None:
        """Show a text-only preview for non-plot nodes."""
        self._line_curve.setData([], [])
        self._image_item.clear()
        self._summary_label.setText(self._format_summary_text(descriptor))
        self._preview_stack.setCurrentWidget(self._summary_label)
        self._preview_mode = "summary"

    def _show_empty_preview(self, message: str) -> None:
        """Show the empty-state preview and clear details."""
        self._line_curve.setData([], [])
        self._image_item.clear()
        self._summary_label.clear()
        self._preview_header.setText("PatchViewer")
        self._stats_label.clear()
        self._empty_label.setText(message)
        self._preview_stack.setCurrentWidget(self._empty_label)
        self._details.clear()
        self._preview_mode = "empty"
        self._current_descriptor = None

    def _format_array_summary(self, values: np.ndarray) -> str:
        """Return a compact one-line summary for an array."""
        parts = [f"shape={tuple(values.shape)}", f"dtype={values.dtype}"]
        stats = self._numeric_stats_text(values)
        if stats:
            parts.append(stats)
        return " ".join(parts)

    @staticmethod
    def _summarize_scalar(value: object) -> str:
        """Return a compact label for a scalar value."""
        text = str(value)
        if len(text) > 80:
            return text[:77] + "..."
        return text

    def _format_summary_text(self, descriptor: _NodeDescriptor) -> str:
        """Build the short summary shown above the details panel."""
        if descriptor.kind == "group":
            return f"{descriptor.path}\n{descriptor.summary or 'Container'}"
        if descriptor.kind == "array":
            return f"{descriptor.path}\n{descriptor.summary}"
        return f"{descriptor.path}\n{self._summarize_scalar(descriptor.value)}"

    def _format_details(self, descriptor: _NodeDescriptor) -> str:
        """Build the long-form details text for a selected node."""
        lines = [f"path: {descriptor.path}", f"kind: {descriptor.kind}"]
        if descriptor.shape:
            lines.append(f"shape: {descriptor.shape}")
        if descriptor.dtype:
            lines.append(f"dtype: {descriptor.dtype}")
        if descriptor.kind == "array":
            values = np.asarray(descriptor.value)
            stats = self._numeric_stats_text(values)
            if stats:
                lines.append(f"stats: {stats}")
            lines.append(f"value: {np.array2string(values, threshold=20)}")
        else:
            lines.append(f"value: {descriptor.value!r}")
        return "\n".join(lines)

    @staticmethod
    def _numeric_stats_text(values: np.ndarray) -> str:
        """Return compact numeric stats when the array supports them."""
        if values.size == 0 or not np.issubdtype(values.dtype, np.number):
            return ""
        min_value = float(np.nanmin(values))
        max_value = float(np.nanmax(values))
        return f"min={format_display(min_value)} max={format_display(max_value)}"

    @staticmethod
    def _format_preview_header(descriptor: _NodeDescriptor) -> str:
        """Build the title line shown above the preview panel."""
        kind = descriptor.kind.upper()
        return (
            f"<b>{descriptor.path}</b> " f"<span style='color: gray;'>[{kind}]</span>"
        )

    @staticmethod
    def _format_stats_label(descriptor: _NodeDescriptor) -> str:
        """Build the secondary stats line shown below the preview header."""
        return descriptor.summary

    def _restore_tree_state(self) -> None:
        """Restore expanded branches after a tree rebuild."""
        for path, item in self._items_by_path.items():
            if path in self._expanded_paths:
                item.setExpanded(True)

    def _remember_expanded_paths(self) -> None:
        """Capture the current set of expanded item paths."""
        expanded: set[str] = set()
        for path, item in self._items_by_path.items():
            if item.isExpanded():
                expanded.add(path)
        self._expanded_paths = expanded

    def _apply_tree_filter(self, text: str) -> None:
        """Filter tree rows by label, path, or summary text."""
        needle = text.strip().casefold()
        for index in range(self._tree.topLevelItemCount()):
            item = self._tree.topLevelItem(index)
            self._filter_item_recursive(item, needle)

    def _filter_item_recursive(self, item: QTreeWidgetItem, needle: str) -> bool:
        """Hide tree rows that do not match the current filter."""
        descriptor = item.data(0, Qt.ItemDataRole.UserRole)
        own_match = True
        if isinstance(descriptor, _NodeDescriptor) and needle:
            haystack = " ".join(
                (descriptor.label, descriptor.path, descriptor.summary)
            ).casefold()
            own_match = needle in haystack

        child_match = False
        for index in range(item.childCount()):
            child = item.child(index)
            child_match = self._filter_item_recursive(child, needle) or child_match

        visible = own_match or child_match or not needle
        item.setHidden(not visible)
        if needle and child_match:
            item.setExpanded(True)
        return visible

    def _icon_for_descriptor(self, descriptor: _NodeDescriptor):
        """Return a lightweight icon conveying the node type."""
        style = self.style()
        if descriptor.kind == "group":
            return style.standardIcon(QStyle.StandardPixmap.SP_DirIcon)
        if descriptor.kind in {"patch", "array"} and len(descriptor.shape) == 2:
            return style.standardIcon(QStyle.StandardPixmap.SP_FileDialogDetailedView)
        if descriptor.kind == "array" and len(descriptor.shape) == 1:
            return style.standardIcon(QStyle.StandardPixmap.SP_FileDialogListView)
        if descriptor.kind == "scalar":
            return style.standardIcon(QStyle.StandardPixmap.SP_FileIcon)
        return style.standardIcon(QStyle.StandardPixmap.SP_ComputerIcon)

    @staticmethod
    def _coerce_plot_axis(values: np.ndarray) -> np.ndarray:
        """Convert array values into numbers pyqtgraph can display."""
        arr = np.asarray(values)
        if np.issubdtype(arr.dtype, np.datetime64):
            base = arr.astype("datetime64[ns]").astype(np.int64)
            return (base - base[0]).astype(np.float64) / 1e9
        if np.issubdtype(arr.dtype, np.timedelta64):
            return arr.astype("timedelta64[ns]").astype(np.float64) / 1e9
        if np.issubdtype(arr.dtype, np.number):
            return arr.astype(np.float64)
        warnings.warn(
            "Non-numeric array detected; using sample index for preview values.",
            RuntimeWarning,
            stacklevel=2,
        )
        return np.arange(arr.size, dtype=np.float64)


if __name__ == "__main__":  # pragma: no cover
    from Orange.widgets.utils.widgetpreview import WidgetPreview

    WidgetPreview(PatchViewer).run()
