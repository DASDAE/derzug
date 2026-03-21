"""Tests for the Annotations widget."""

from __future__ import annotations

from pathlib import Path

import dascore as dc
import pytest
from AnyQt.QtCore import QPointF, Qt
from AnyQt.QtTest import QTest
from AnyQt.QtWidgets import QApplication
from derzug.models.annotations import Annotation, AnnotationSet, PointGeometry
from derzug.utils.annotations import sync_directory_state
from derzug.utils.testing import TestWidgetDefaults, capture_output, widget_context
from derzug.widgets.annotations import Annotations
from derzug.widgets.waterfall import Waterfall


def _set(ids: tuple[str, ...], dims=("time",)) -> AnnotationSet:
    return AnnotationSet(
        dims=dims,
        annotations=tuple(
            Annotation(
                id=annotation_id,
                geometry=PointGeometry(
                    dims=dims,
                    values=tuple(float(i + 1) for i in range(len(dims))),
                ),
            )
            for annotation_id in ids
        ),
    )


@pytest.fixture
def widget(qtbot):
    """Return a live Annotations widget."""
    with widget_context(Annotations) as w:
        w.show()
        qtbot.wait(10)
        yield w


class TestAnnotationsDefaults(TestWidgetDefaults):
    """Default smoke tests for the Annotations widget."""

    __test__ = True
    widget = Annotations


class TestAnnotationsWidget:
    """Tests for the Annotations widget UI and business logic."""

    @staticmethod
    def _double_click_waterfall_point(
        waterfall: Waterfall, *, x_index: int, y_index: int
    ) -> None:
        """Create one point via a real viewport double-click."""
        axes = waterfall._axes
        assert axes is not None
        waterfall._annotation_tool = "point"
        scene_pos = waterfall._plot_item.vb.mapViewToScene(
            QPointF(float(axes.x_plot[x_index]), float(axes.y_plot[y_index]))
        )
        viewport_pos = waterfall._plot_widget.mapFromScene(scene_pos)
        QTest.mouseDClick(
            waterfall._plot_widget.viewport(),
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
            viewport_pos,
        )

    def test_widget_instantiates(self, widget):
        """Widget initializes with an in-memory store and empty table."""
        assert isinstance(widget, Annotations)
        assert widget.is_source is True
        assert widget._table is not None
        assert widget._in_memory_checkbox.isChecked() is True
        assert widget._in_memory_checkbox.isEnabled() is False

    def test_input_creates_new_selected_row(self, widget, monkeypatch):
        """Sending an annotation set creates a new entry and selects it."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        assert len(widget._entries) == 1
        assert received[-1] == widget._entries[0].annotation_set

    def test_empty_input_annotation_set_does_not_create_row(self, widget, monkeypatch):
        """An empty annotation set should not create a store entry."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(AnnotationSet(dims=("time",), annotations=()))

        assert len(widget._entries) == 0
        assert received == [None]

    def test_in_memory_checkbox_stays_checked_without_directory(self, widget):
        """Clicking the in-memory checkbox without a directory is a no-op."""
        widget._in_memory_checkbox.click()

        assert widget.store_directory == ""
        assert widget._in_memory_checkbox.isChecked() is True
        assert widget._in_memory_checkbox.isEnabled() is False

    def test_matching_dims_append_to_selected_row(self, widget, monkeypatch):
        """A second input with matching dims appends to the selected row."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        widget.set_annotation_set(_set(("b",)))
        assert len(widget._entries) == 1
        assert [item.id for item in widget._entries[0].annotation_set.annotations] == [
            "a",
            "b",
        ]
        assert [item.id for item in received[-1].annotations] == ["a", "b"]

    def test_mismatched_dims_create_new_row(self, widget, monkeypatch):
        """An input with mismatched dims creates a second entry."""
        capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",), dims=("time",)))
        widget.set_annotation_set(_set(("b",), dims=("distance",)))
        assert len(widget._entries) == 2
        assert widget.selected_entry_id == widget._entries[-1].id

    def test_colliding_ids_replace_existing_annotations(self, widget, monkeypatch):
        """Sending an annotation with a colliding ID replaces the existing one."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        replacement = AnnotationSet(
            dims=("time",),
            annotations=(
                Annotation(
                    id="a",
                    geometry=PointGeometry(dims=("time",), values=(9.0,)),
                ),
            ),
        )
        widget.set_annotation_set(replacement)
        assert widget._entries[0].annotation_set.annotations[0].geometry.values == (
            9.0,
        )
        assert received[-1].annotations[0].geometry.values == (9.0,)

    def test_selection_drives_output(self, widget, monkeypatch):
        """Changing the table selection re-emits the newly selected annotation set."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        widget.set_annotation_set(_set(("b",), dims=("distance",)))
        widget._table.selectRow(0)
        widget._on_selection_changed()
        assert received[-1] == widget._entries[0].annotation_set

    def test_rename_updates_entry_name(self, widget, monkeypatch):
        """Renaming a row through the model updates the entry name."""
        capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        assert widget._set_name_for_row(0, "Reviewed Picks")
        assert widget._entries[0].name == "Reviewed Picks"

    def test_delete_selected_updates_output(self, widget, monkeypatch):
        """Deleting the selected row removes it and re-emits the new selection."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        widget.set_annotation_set(_set(("b",), dims=("distance",)))
        widget._table.selectRow(0)
        widget._on_selection_changed()
        widget._delete_selected()
        assert len(widget._entries) == 1
        assert received[-1] == widget._entries[0].annotation_set

    def test_delete_key_removes_highlighted_row(self, widget, monkeypatch, qtbot):
        """Pressing Delete with a row selected removes it from the store."""
        received = capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        widget.set_annotation_set(_set(("b",), dims=("distance",)))
        widget._table.selectRow(0)
        widget._on_selection_changed()
        widget._table.setFocus()
        qtbot.wait(10)

        QTest.keyClick(widget._table, Qt.Key_Delete)

        assert len(widget._entries) == 1
        assert received[-1] == widget._entries[0].annotation_set

    def test_directory_persistence_writes_json(self, widget, monkeypatch, tmp_path):
        """Switching to a directory store writes JSON files to disk."""
        capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        widget.store_directory = str(tmp_path)
        widget._entries = sync_directory_state(widget._entries, widget.store_directory)
        widget._request_ui_refresh()
        widget._persist_settings()
        assert widget._in_memory_checkbox.isChecked() is False
        assert widget._in_memory_checkbox.isEnabled() is True
        assert list(Path(tmp_path).glob("*.json"))

    def test_choose_directory_unchecks_in_memory(self, widget, monkeypatch, tmp_path):
        """Choosing a directory disables the in-memory checkbox and writes JSON."""
        capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        monkeypatch.setattr(
            "derzug.widgets.annotations.QFileDialog.getExistingDirectory",
            lambda *_args, **_kwargs: str(tmp_path),
        )

        widget._choose_directory()

        assert widget.store_directory == str(tmp_path)
        assert widget._in_memory_checkbox.isChecked() is False
        assert widget._in_memory_checkbox.isEnabled() is True
        assert list(Path(tmp_path).glob("*.json"))

    def test_checking_in_memory_clears_directory_and_keeps_entries(
        self, widget, monkeypatch, tmp_path
    ):
        """Toggling back to in-memory clears the directory but retains entries."""
        capture_output(widget.Outputs.annotation_set, monkeypatch)
        widget.set_annotation_set(_set(("a",)))
        widget.store_directory = str(tmp_path)
        widget._entries = sync_directory_state(widget._entries, widget.store_directory)
        widget._request_ui_refresh()

        widget._in_memory_checkbox.setChecked(True)

        assert widget.store_directory == ""
        assert len(widget._entries) == 1
        assert widget._entries[0].file_path is None
        assert widget._in_memory_checkbox.isChecked() is True
        assert widget._in_memory_checkbox.isEnabled() is False

    def test_restore_directory_backed_state_updates_checkbox(self, widget, tmp_path):
        """Restoring a directory-backed state unchecks the in-memory checkbox."""
        widget.store_directory = str(tmp_path)
        widget._request_ui_refresh()

        assert widget._in_memory_checkbox.isChecked() is False
        assert widget._in_memory_checkbox.isEnabled() is True

    def test_table_hides_aggregate_count_column(self, widget):
        """The table should not show the old aggregate Count column."""
        model = widget._table_model
        headers = [
            model.headerData(column, Qt.Horizontal)
            for column in range(model.columnCount())
        ]

        assert "Count" not in headers
        assert headers == [
            "Name",
            "Dims",
            "Points",
            "Spans",
            "Boxes",
            "Paths",
            "Polygons",
            "Size",
        ]

    def test_waterfall_resends_update_selected_annotations_row(self, qtbot):
        """A second Waterfall send should refresh the selected Annotations row."""
        with (
            widget_context(Waterfall) as waterfall,
            widget_context(Annotations) as store,
        ):
            waterfall.show()
            store.show()
            qtbot.wait(10)

            waterfall.Outputs.annotation_set.send = store.set_annotation_set
            patch = dc.get_example_patch("example_event_2")
            waterfall.set_patch(patch)
            axes = waterfall._axes

            waterfall._create_point_annotation(
                float(axes.x_plot[120]),
                float(axes.y_plot[120]),
            )
            waterfall.setFocus()
            qtbot.wait(10)
            QTest.keyClick(waterfall, Qt.Key_S)
            qtbot.wait(10)

            assert len(store._entries) == 1
            first_entry = store._entries[0]
            assert len(first_entry.annotation_set.annotations) == 1
            assert store._table_model.rowCount() == 1
            assert store._table_model.data(store._table_model.index(0, 2)) == 1

            original = first_entry.annotation_set.annotations[0]
            updated = original.model_copy(
                update={
                    "geometry": PointGeometry(
                        dims=original.geometry.dims,
                        values=tuple(
                            2.0 if index == 0 else value
                            for index, value in enumerate(original.geometry.values)
                        ),
                    )
                }
            )
            waterfall._annotation_controller.store_annotation(updated)
            waterfall._mark_output_dirty("annotation_set")
            QTest.keyClick(waterfall, Qt.Key_S)
            qtbot.wait(10)

            assert len(store._entries) == 1
            assert store._entries[0].id == first_entry.id
            assert len(store._entries[0].annotation_set.annotations) == 1
            assert (
                store._entries[0].annotation_set.annotations[0].geometry.values[0]
                == 2.0
            )
            assert store._table_model.rowCount() == 1
            assert store._table_model.data(store._table_model.index(0, 2)) == 1

    def test_waterfall_local_annotations_do_not_import_until_s(self, qtbot):
        """Waterfall annotations should stay local until the user presses s."""
        with (
            widget_context(Waterfall) as waterfall,
            widget_context(Annotations) as store,
        ):
            waterfall.show()
            store.show()
            qtbot.wait(10)

            waterfall.Outputs.annotation_set.send = store.set_annotation_set
            patch = dc.get_example_patch("example_event_2")
            waterfall.set_patch(patch)

            assert len(store._entries) == 0

            self._double_click_waterfall_point(waterfall, x_index=120, y_index=120)
            qtbot.wait(10)

            assert waterfall._annotation_set is not None
            assert len(waterfall._annotation_set.annotations) == 1
            assert len(store._entries) == 0

            qtbot.waitUntil(
                lambda: QApplication.focusWidget() is waterfall, timeout=1000
            )
            QTest.keyClick(waterfall.window(), Qt.Key_S)
            qtbot.wait(10)

            assert len(store._entries) == 1
            assert len(store._entries[0].annotation_set.annotations) == 1
