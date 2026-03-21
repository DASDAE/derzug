"""
Tests for the Spool widget.
"""

from __future__ import annotations

from pathlib import Path

import dascore as dc
import numpy as np
import pandas as pd
import pytest
from AnyQt.QtCore import Qt
from AnyQt.QtWidgets import QDialog
from dascore.clients.dirspool import DirectorySpool
from dascore.clients.filespool import FileSpool
from derzug.utils.display import format_display
from derzug.utils.example_parameters import (
    ExampleParametersDialog,
    get_example_parameter_specs,
)
from derzug.utils.qt import FileOrDirDialog
from derzug.utils.testing import (
    TestWidgetDefaults,
    capture_output,
    wait_for_widget_idle,
    widget_context,
)
from derzug.widgets.spool import Spool


def _default_example_name(spool_widget: Spool) -> str | None:
    """Return the widget's expected default example name for this environment."""
    return (
        "example_event_2"
        if "example_event_2" in spool_widget._examples
        else (spool_widget._examples[0] if spool_widget._examples else None)
    )


@pytest.fixture
def spool_widget(qtbot):
    """Return a live Spool widget for one test case."""
    with widget_context(Spool) as widget:
        widget.show()
        qtbot.wait(10)
        yield widget
        # Drain any pending task before teardown to avoid leaking async work
        # into the next test (load→singleShot→emit chain may still be running).
        wait_for_widget_idle(widget, timeout=3.0)


def _patch_with_tag(tag: str) -> dc.Patch:
    """Return an example patch with a unique tag for path-safe persistence tests."""
    patch = dc.get_example_patch()
    attrs = patch.attrs.model_dump()
    attrs["tag"] = tag
    return patch.update(attrs=attrs)


def _spool_tags(spool: dc.BaseSpool) -> list[str]:
    """Return tag attributes for each patch in a spool."""
    return [patch.attrs.tag for patch in spool]


def _run_and_wait(widget, qtbot, timeout=5000) -> None:
    """Trigger widget.run() and block until the background load completes."""
    widget.run()
    wait_for_widget_idle(widget, timeout=timeout / 1000)


def _select_row(widget: Spool, index: int = 0) -> tuple:
    """Return the combo/edit/remove widgets for one select-filter row."""
    row = widget._select_rows[index]
    return row["combo"], row["edit"], row["remove"]


def _multi_select_spool() -> dc.BaseSpool:
    """Return a small spool with overlapping tags and distinct distance minima."""
    base = dc.get_example_patch()
    first = _patch_with_tag("bob")
    second = _patch_with_tag("bob").update_coords(
        distance=base.get_array("distance") + 1000
    )
    third = _patch_with_tag("alice").update_coords(
        distance=base.get_array("distance") + 1000
    )
    return dc.spool([first, second, third])


def _make_example_map():
    """Return a small deterministic example registry for parameter-dialog tests."""

    def configured_example(sample_rate: int = 150, duration: float = 1.5):
        patch = dc.get_example_patch("example_event_1").mean("distance").squeeze()
        sample_count = max(2, round(sample_rate * duration))
        time = np.arange(sample_count, dtype=np.float64) / float(sample_rate)
        data = np.linspace(0.0, 1.0, sample_count, dtype=np.float64)
        patch = patch.new(data=data, coords={"time": time}, dims=("time",))
        patch = patch.update_attrs(tag=f"duration-{duration}")
        return dc.spool([patch])

    def plain_example():
        return dc.spool([dc.get_example_patch("example_event_1")])

    return {
        "configured_example": configured_example,
        "plain_example": plain_example,
    }


class TestSpool:
    """Tests for the pure Orange Spool widget."""

    def test_widget_instantiates(self, spool_widget):
        """Widget creates without error and has the expected class name."""
        assert isinstance(spool_widget, Spool)
        assert spool_widget.is_source is True
        assert spool_widget.name == "Spool"
        assert spool_widget.unpack_single_patch is True
        assert len(spool_widget._examples) > 0
        assert hasattr(spool_widget, "example_combo")
        assert hasattr(spool_widget, "file_path_edit")
        assert hasattr(spool_widget, "open_button")
        assert hasattr(spool_widget, "update_button")
        assert hasattr(spool_widget, "raw_edit")
        assert hasattr(spool_widget, "chunk_dim_combo")
        assert hasattr(spool_widget, "chunk_value_edit")
        assert hasattr(spool_widget, "chunk_overlap_edit")
        assert hasattr(spool_widget, "select_add_button")
        assert not hasattr(spool_widget, "load_button")
        assert (
            spool_widget.spool_input in spool_widget._examples
            or spool_widget.spool_input is None
        )
        assert spool_widget._table is not None
        assert spool_widget.update_button.text() == "Update"
        assert spool_widget.unpack_checkbox.text() == "Unpack len1 spool"
        assert len(spool_widget._select_rows) == 1

    def test_default_selection_populates_table_on_init(self, spool_widget):
        """Default/persisted source is loaded immediately on widget construction."""
        if spool_widget.file_input or spool_widget.raw_input:
            pytest.skip("This check targets default example initialization path.")
        model = spool_widget._table.model()
        assert spool_widget.spool_input == _default_example_name(spool_widget)
        assert spool_widget.example_combo.currentText() == spool_widget.spool_input
        assert model is not None
        assert model.rowCount() > 0

    def test_table_uses_polished_view_defaults(self, spool_widget):
        """The spool table should use the intended lightweight presentation tweaks."""
        assert spool_widget._table.alternatingRowColors() is True
        assert spool_widget._table.showGrid() is False
        assert (
            spool_widget._table.selectionBehavior()
            == spool_widget._table.SelectionBehavior.SelectRows
        )
        assert (
            spool_widget._table.selectionMode()
            == spool_widget._table.SelectionMode.SingleSelection
        )
        assert spool_widget._table.verticalHeader().isVisible() is False

    def test_table_formats_float_display_but_keeps_raw_sort_value(
        self, spool_widget, qtbot
    ):
        """Float-like values should share display formatting and keep raw sort data."""
        spool_widget.spool_input = "example_event_2"
        _run_and_wait(spool_widget, qtbot)
        contents = spool_widget._current_spool.get_contents()
        numeric_col = next(
            column
            for column in ("time_step", "distance_step")
            if column in contents.columns
        )
        expected_value = contents.iloc[0][numeric_col]
        model = spool_widget._build_table_model(contents)
        # Derive column index from the model directly so computed columns
        # (e.g. duration) do not offset the position.
        header_name = numeric_col.replace("_", " ").title()
        column = next(
            i
            for i in range(model.columnCount())
            if model.headerData(i, Qt.Horizontal) == header_name
        )
        index = model.index(0, column)

        assert model.data(index, Qt.ItemDataRole.DisplayRole) == format_display(
            expected_value
        )
        assert model.data(index, Qt.ItemDataRole.UserRole) == pytest.approx(
            float(expected_value)
        )

    def test_duration_column_appears_in_table(self, spool_widget, qtbot):
        """Duration column is present and shows a human-readable string."""
        spool_widget.spool_input = "example_event_2"
        _run_and_wait(spool_widget, qtbot)
        model = spool_widget._table.model()
        headers = [
            model.headerData(i, Qt.Horizontal) for i in range(model.columnCount())
        ]
        assert "Duration" in headers

    def test_duration_display_is_human_readable(self, spool_widget, qtbot):
        """Duration cell contains a human-readable unit string, not raw nanoseconds."""
        spool_widget.spool_input = "example_event_2"
        _run_and_wait(spool_widget, qtbot)
        model = spool_widget._table.model()
        col = next(
            i
            for i in range(model.columnCount())
            if model.headerData(i, Qt.Horizontal) == "Duration"
        )
        display = model.data(model.index(0, col), Qt.ItemDataRole.DisplayRole)
        # Should contain a unit abbreviation, not a raw integer
        assert any(unit in display for unit in ("ns", "µs", "ms", " s", " m", " h"))
        assert "nanoseconds" not in display

    def test_duration_sort_value_is_numeric(self, spool_widget, qtbot):
        """Duration UserRole is an integer nanosecond value for table sorting."""
        spool_widget.spool_input = "example_event_2"
        _run_and_wait(spool_widget, qtbot)
        model = spool_widget._table.model()
        col = next(
            i
            for i in range(model.columnCount())
            if model.headerData(i, Qt.Horizontal) == "Duration"
        )
        sort_val = model.data(model.index(0, col), Qt.ItemDataRole.UserRole)
        assert isinstance(sort_val, int)
        assert sort_val > 0

    def test_duration_column_position_is_after_time_max(self, spool_widget, qtbot):
        """Duration column immediately follows Time Max in the table."""
        spool_widget.spool_input = "example_event_2"
        _run_and_wait(spool_widget, qtbot)
        model = spool_widget._table.model()
        headers = [
            model.headerData(i, Qt.Horizontal) for i in range(model.columnCount())
        ]
        assert "Time Max" in headers
        assert headers.index("Duration") == headers.index("Time Max") + 1

    def test_sorted_selection_uses_sorted_table_row_mapping(
        self, spool_widget, monkeypatch, qtbot
    ):
        """Selecting a sorted row should emit the corresponding sorted spool entry."""
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)
        spool_widget._set_source_spool(_multi_select_spool())
        spool_widget._emit_current_output()

        model = spool_widget._table.model()
        assert model is not None
        distance_col = next(
            idx
            for idx in range(model.columnCount())
            if model.headerData(idx, Qt.Horizontal) == "Distance Min"
        )

        model.sort(distance_col, Qt.SortOrder.DescendingOrder)
        spool_widget._table.selectRow(0)
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert received
        output = received[-1]
        assert output is not None
        patch = next(iter(output))
        assert patch.attrs.tag == "bob"
        assert float(np.min(patch.get_array("distance"))) == pytest.approx(1000.0)

    def test_run_emits_spool(self, spool_widget, monkeypatch, qtbot):
        """Calling run() with a valid selection emits a spool on the output."""
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        spool_widget.spool_input = spool_widget._examples[0]
        _run_and_wait(spool_widget, qtbot)

        assert len(received) == 1
        assert received[0] is not None

    def test_load_from_example_uses_saved_parameter_overrides(self, monkeypatch):
        """Example-specific overrides should be passed into the selected callable."""
        examples = _make_example_map()
        monkeypatch.setattr(
            "derzug.widgets.spool._all_examples", lambda ignore=(): examples
        )

        with widget_context(Spool) as widget:
            widget.spool_input = "configured_example"
            widget.example_parameters = {
                "configured_example": {"sample_rate": 220, "duration": 2.0}
            }

            spool = widget._load_from_example()

        patch = next(iter(spool))
        time = patch.get_array("time")
        assert len(time) == 440
        assert time[1] - time[0] == pytest.approx(1 / 220)

    def test_right_click_example_combo_opens_parameter_dialog(self, monkeypatch, qtbot):
        """Right-clicking the example selector should open the parameter dialog."""
        examples = _make_example_map()
        monkeypatch.setattr(
            "derzug.widgets.spool._all_examples", lambda ignore=(): examples
        )
        dialogs: list[ExampleParametersDialog] = []

        def _fake_exec(dialog):
            dialogs.append(dialog)
            return 0

        monkeypatch.setattr(ExampleParametersDialog, "exec", _fake_exec)
        with widget_context(Spool) as widget:
            widget.show()
            widget.spool_input = "configured_example"
            widget.example_combo.setCurrentText("configured_example")
            qtbot.wait(10)

            qtbot.mouseClick(widget.example_combo, Qt.RightButton)

        assert dialogs
        assert dialogs[0].windowTitle() == "Example Parameters: configured_example"

    def test_parameter_dialog_empty_state_for_examples_without_supported_params(
        self, monkeypatch
    ):
        """Examples without supported parameters should still open a dialog cleanly."""
        examples = {"plain_example": _make_example_map()["plain_example"]}
        monkeypatch.setattr(
            "derzug.widgets.spool._all_examples", lambda ignore=(): examples
        )
        dialogs: list[ExampleParametersDialog] = []

        def _fake_exec(dialog):
            dialogs.append(dialog)
            return 0

        monkeypatch.setattr(ExampleParametersDialog, "exec", _fake_exec)
        with widget_context(Spool) as widget:
            widget.spool_input = "plain_example"
            widget._open_example_parameters_dialog()

        assert dialogs
        assert dialogs[0]._apply_button.text() == "Close"

    def test_example_parameter_overrides_persist_across_settings_restore(
        self, monkeypatch
    ):
        """Saved per-example overrides should survive Orange settings packing."""
        examples = _make_example_map()
        monkeypatch.setattr(
            "derzug.widgets.spool._all_examples", lambda ignore=(): examples
        )

        with widget_context(Spool) as first:
            first.example_parameters = {
                "configured_example": {"sample_rate": 300, "duration": 2.5}
            }
            saved = first.settingsHandler.pack_data(first)

        with widget_context(Spool, stored_settings=saved) as second:
            assert second.example_parameters == {
                "configured_example": {"sample_rate": 300, "duration": 2.5}
            }

    def test_save_example_parameter_overrides_drops_defaults(self, monkeypatch):
        """Only non-default example values should be persisted."""
        examples = _make_example_map()
        monkeypatch.setattr(
            "derzug.widgets.spool._all_examples", lambda ignore=(): examples
        )

        with widget_context(Spool) as widget:
            specs = get_example_parameter_specs(examples["configured_example"])
            widget._save_example_parameter_overrides(
                "configured_example",
                specs,
                {"sample_rate": 150, "duration": 2.0},
            )

            assert widget.example_parameters == {
                "configured_example": {"duration": 2.0}
            }

    def test_single_patch_source_emits_patch_by_default(
        self, spool_widget, monkeypatch, qtbot
    ):
        """Single-patch sources emit on the Patch output when unpack is default-on."""
        received = capture_output(spool_widget.Outputs.patch, monkeypatch)

        spool_widget.spool_input = "example_event_2"
        _run_and_wait(spool_widget, qtbot)

        assert received
        assert received[-1] is not None

    def test_file_input_clears_other_inputs(self, spool_widget):
        """Typing file input clears example and raw inputs."""
        spool_widget.spool_input = spool_widget._examples[0]
        spool_widget.raw_input = "abc"
        spool_widget.raw_edit.setText("abc")

        spool_widget._set_file_input("/tmp/some-path", trigger_run=False)

        assert spool_widget.file_input == "/tmp/some-path"
        assert spool_widget.file_path_edit.text() == "/tmp/some-path"
        assert spool_widget.spool_input is None
        assert spool_widget.raw_input == ""
        assert spool_widget.raw_edit.text() == ""

    def test_raw_input_clears_other_inputs(self, spool_widget):
        """Typing raw input clears example and file inputs."""
        spool_widget.spool_input = spool_widget._examples[0]
        spool_widget.file_input = "/tmp/a"
        spool_widget.file_path_edit.setText("/tmp/a")

        spool_widget._on_raw_text_edited("raw://source")

        assert spool_widget.raw_input == "raw://source"
        assert spool_widget.spool_input is None
        assert spool_widget.file_input == ""
        assert spool_widget.file_path_edit.text() == ""

    def test_raw_typing_does_not_run_until_edit_finished(
        self, spool_widget, monkeypatch
    ):
        """Raw input typing clears fields but does not run immediately."""
        called = []
        monkeypatch.setattr(spool_widget, "run", lambda: called.append(True))

        spool_widget._on_raw_text_edited("raw://source")

        assert spool_widget.raw_input == "raw://source"
        assert called == []

    def test_raw_edit_finished_runs(self, spool_widget, monkeypatch):
        """Raw input executes when editing is finished (focus change/enter)."""
        called = []
        monkeypatch.setattr(spool_widget, "run", lambda: called.append(True))

        spool_widget.raw_edit.setText("raw://source")
        spool_widget._on_raw_edit_finished()

        assert spool_widget.raw_input == "raw://source"
        assert called == [True]

    def test_example_selection_clears_text_inputs(self, spool_widget):
        """Selecting an example clears file and raw text inputs."""
        spool_widget.file_input = "/tmp/a"
        spool_widget.raw_input = "raw://source"
        spool_widget.file_path_edit.setText("/tmp/a")
        spool_widget.raw_edit.setText("raw://source")

        spool_widget._on_combo_changed(0)

        assert spool_widget.spool_input == spool_widget._examples[0]
        assert spool_widget.file_input == ""
        assert spool_widget.raw_input == ""
        assert spool_widget.file_path_edit.text() == ""
        assert spool_widget.raw_edit.text() == ""

    def test_select_path_input_uses_dialog_selected_file(
        self, spool_widget, monkeypatch
    ):
        """Open selector stores chosen file path and clears other inputs."""
        monkeypatch.setattr(
            spool_widget,
            "_open_path_dialog",
            lambda: "/tmp/selected.h5",
        )
        called = []
        monkeypatch.setattr(spool_widget, "run", lambda: called.append(True))

        spool_widget.raw_input = "raw://source"
        spool_widget.raw_edit.setText("raw://source")
        spool_widget.spool_input = spool_widget._examples[0]
        spool_widget._select_path_input()

        assert spool_widget.file_input == "/tmp/selected.h5"
        assert spool_widget.file_path_edit.text() == "/tmp/selected.h5"
        assert spool_widget.raw_input == ""
        assert spool_widget.spool_input is None
        assert called == [True]

    def test_select_path_input_uses_dialog_selected_directory(
        self, spool_widget, monkeypatch
    ):
        """Open selector stores chosen folder path and clears other inputs."""
        monkeypatch.setattr(
            spool_widget,
            "_open_path_dialog",
            lambda: "/tmp/data-dir",
        )
        called = []
        monkeypatch.setattr(spool_widget, "run", lambda: called.append(True))

        spool_widget.raw_input = "raw://source"
        spool_widget.raw_edit.setText("raw://source")
        spool_widget.spool_input = spool_widget._examples[0]
        spool_widget._select_path_input()

        assert spool_widget.file_input == "/tmp/data-dir"
        assert spool_widget.file_path_edit.text() == "/tmp/data-dir"
        assert spool_widget.raw_input == ""
        assert spool_widget.spool_input is None
        assert called == [True]

    def test_select_path_input_does_nothing_on_cancel(self, spool_widget, monkeypatch):
        """Canceling the picker leaves inputs unchanged and does not run."""
        monkeypatch.setattr(spool_widget, "_open_path_dialog", lambda: "")
        called = []
        monkeypatch.setattr(spool_widget, "run", lambda: called.append(True))

        spool_widget.file_input = ""
        spool_widget._select_path_input()

        assert spool_widget.file_input == ""
        assert called == []

    def test_file_or_dir_dialog_accepts_directory_on_open(self, tmp_path):
        """Pressing Open with a selected directory accepts that directory path."""
        directory = tmp_path / "chosen_dir"
        directory.mkdir()

        dialog = FileOrDirDialog()
        dialog.setFileMode(dialog.FileMode.AnyFile)
        dialog.selectFile(str(directory))
        dialog.accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        # Necessary to convert to a Path object for OS-independent equivalence
        assert Path(dialog.chosen_path()) == directory

    def test_file_or_dir_dialog_accepts_file(self, tmp_path):
        """Pressing Open with a selected file accepts that file path."""
        file_path = tmp_path / "chosen.h5"
        file_path.write_text("x", encoding="utf-8")

        dialog = FileOrDirDialog()
        dialog.setFileMode(dialog.FileMode.AnyFile)
        dialog.selectFile(str(file_path))
        dialog.accept()

        assert dialog.result() == QDialog.DialogCode.Accepted
        # Necessary to convert to a Path object for OS-independent equivalence
        assert Path(dialog.chosen_path()) == file_path

    def test_run_uses_file_loader_when_file_input_set(self, spool_widget):
        """_snapshot_loader() routes to the file path when file_input is set."""
        spool_widget.file_input = "/tmp/fake"
        spool_widget.raw_input = ""
        spool_widget.spool_input = None
        source_name, loader_fn = spool_widget._snapshot_loader()
        assert source_name == "/tmp/fake"
        assert callable(loader_fn)

    def test_run_uses_raw_loader_when_raw_input_set(self, spool_widget):
        """_snapshot_loader() routes to the raw path when raw_input is set."""
        spool_widget.raw_input = "raw://fake"
        spool_widget.file_input = ""
        spool_widget.spool_input = None
        source_name, loader_fn = spool_widget._snapshot_loader()
        assert source_name == "raw://fake"
        assert callable(loader_fn)

    def test_run_with_no_selection_emits_none(self, spool_widget, monkeypatch):
        """run() with no selected example sends None downstream."""
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        spool_widget.spool_input = None
        spool_widget.file_input = ""
        spool_widget.raw_input = ""
        spool_widget.run()

        assert received == [None]

    def test_run_loads_spool_from_file_path(
        self, spool_widget, monkeypatch, tmp_path, qtbot
    ):
        """run() loads and emits a spool when file_input points to one file."""
        spool = dc.get_example_spool("random_das")
        file_path = dc.write(spool, tmp_path / "single.h5", file_format="DASDAE")

        received = capture_output(spool_widget.Outputs.spool, monkeypatch)
        spool_widget.file_input = str(file_path)
        spool_widget.raw_input = ""
        spool_widget.spool_input = None
        _run_and_wait(spool_widget, qtbot)

        assert len(received) == 1
        assert received[0] is not None
        assert len(list(received[0])) > 0

    def test_run_loads_spool_from_directory_path(
        self, spool_widget, monkeypatch, tmp_path, qtbot
    ):
        """run() loads and emits a spool when file_input points to a directory."""
        spool = dc.get_example_spool("random_das")
        directory = tmp_path / "spool_dir"
        directory.mkdir()
        dc.write(spool, directory / "a.h5", file_format="DASDAE")

        received = capture_output(spool_widget.Outputs.spool, monkeypatch)
        spool_widget.file_input = str(directory)
        spool_widget.raw_input = ""
        spool_widget.spool_input = None
        _run_and_wait(spool_widget, qtbot)

        assert len(received) == 1
        assert received[0] is not None
        assert len(list(received[0])) > 0

    def test_update_button_reruns_loader_for_source_backed_spools(
        self, spool_widget, monkeypatch
    ):
        """Update should reuse the normal load path when source controls are active."""
        calls: list[str] = []
        monkeypatch.setattr(spool_widget, "run", lambda: calls.append("run"))

        spool_widget.update_button.click()

        assert calls == ["run"]

    def test_update_button_updates_in_memory_underlying_spool(
        self, spool_widget, monkeypatch, qtbot
    ):
        """Update should refresh the in-memory source spool when no loader applies."""
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)
        original = dc.spool([_patch_with_tag("before")])
        refreshed = dc.spool([_patch_with_tag("after")])

        class _UpdateProxy:
            def update(self):
                return refreshed

            def get_contents(self):
                return original.get_contents()

        spool_widget.set_canvas_source(original)
        received.clear()
        spool_widget._source_spool = _UpdateProxy()

        spool_widget.update_button.click()
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert received[-1] is refreshed
        assert spool_widget._source_spool is refreshed

    def test_combo_change_triggers_load_and_table_update(
        self, spool_widget, monkeypatch, qtbot
    ):
        """Changing combo selection loads data and populates the table view."""
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        start_index = spool_widget.example_combo.currentIndex()
        target_index = 1 if len(spool_widget._examples) > 1 else 0
        spool_widget.example_combo.setCurrentIndex(target_index)

        # If there is only one entry, setCurrentIndex(0) may not emit.
        if target_index == start_index:
            spool_widget._on_combo_changed(target_index)

        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert received
        assert received[-1] is not None
        model = spool_widget._table.model()
        assert model is not None
        assert model.rowCount() > 0

    def test_combo_change_updates_selected_setting(self, spool_widget):
        """The persisted spool_input Setting follows combo selection changes."""
        target_index = 1 if len(spool_widget._examples) > 1 else 0
        spool_widget.example_combo.setCurrentIndex(target_index)
        if len(spool_widget._examples) == 1:
            spool_widget._on_combo_changed(target_index)
        assert spool_widget.spool_input == spool_widget._examples[target_index]

    def test_table_populated_after_run(self, spool_widget, qtbot):
        """After a successful run(), the table view has at least one row."""
        spool_widget.spool_input = spool_widget._examples[0]
        _run_and_wait(spool_widget, qtbot)

        model = spool_widget._table.model()
        assert model is not None
        assert model.rowCount() > 0
        assert spool_widget.chunk_dim_combo.isEnabled()
        assert spool_widget.chunk_value_edit.isEnabled()
        assert spool_widget.chunk_dim_combo.count() > 0

    def test_chunk_dims_populated_from_contents_dims_column(self, spool_widget, qtbot):
        """Chunk dropdown options are derived from the contents dims values."""
        spool_widget.spool_input = spool_widget._examples[0]
        _run_and_wait(spool_widget, qtbot)
        options = [
            spool_widget.chunk_dim_combo.itemText(i)
            for i in range(spool_widget.chunk_dim_combo.count())
        ]
        assert options
        assert any(x in options for x in ("time", "distance"))

    def test_chunk_and_select_dropdown_options_are_sorted(self, spool_widget):
        """Dynamic Spool dropdown choices should be alphabetically sorted."""
        df = pd.DataFrame(
            {
                "tag": ["alpha"],
                "network": ["net"],
                "dims": [("z", "time", "distance")],
            }
        )

        spool_widget._set_chunk_dims_from_contents(df)
        spool_widget._set_select_cols_from_contents(df)

        chunk_options = [
            spool_widget.chunk_dim_combo.itemText(i)
            for i in range(spool_widget.chunk_dim_combo.count())
        ]

        assert chunk_options == sorted(chunk_options, key=str.casefold)
        assert list(spool_widget._select_options) == sorted(
            spool_widget._select_options, key=str.casefold
        )

    def test_chunk_selection_calls_spool_chunk(self, spool_widget, monkeypatch, qtbot):
        """Chunk controls call BaseSpool.chunk with dim/value and extra kwargs."""
        spool_widget.spool_input = spool_widget._examples[0]
        _run_and_wait(spool_widget, qtbot)
        if spool_widget.chunk_dim_combo.count() == 0:
            pytest.skip("No chunk dimensions available in loaded spool.")

        called: list[dict] = []
        first_dim = spool_widget.chunk_dim_combo.itemText(0)
        expected = spool_widget._current_spool

        class _ChunkProxy:
            def chunk(self, **kwargs):
                called.append(kwargs)
                return expected

            def get_contents(self):
                return expected.get_contents()

            def __iter__(self):
                return iter(expected)

        spool_widget._current_spool = _ChunkProxy()
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)
        spool_widget.chunk_value_edit.setText("10")
        spool_widget.chunk_overlap_edit.setText("1")
        spool_widget.chunk_keep_partial = True
        spool_widget.chunk_snap_coords = False
        spool_widget.chunk_tolerance = 2.0
        spool_widget.chunk_conflict = "drop"
        spool_widget.chunk_dim_combo.setCurrentIndex(0)
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert called
        kwargs = called[-1]
        assert kwargs[first_dim] == 10
        assert kwargs["overlap"] == 1
        assert kwargs["keep_partial"] is True
        assert kwargs["snap_coords"] is False
        assert kwargs["tolerance"] == 2.0
        assert kwargs["conflict"] == "drop"
        assert received
        assert received[-1] is not None

    def test_chunk_not_called_when_value_blank(self, spool_widget, monkeypatch):
        """Selecting a chunk dim with blank value does not call chunk."""
        spool_widget.spool_input = spool_widget._examples[0]
        spool_widget.run()
        if spool_widget.chunk_dim_combo.count() == 0:
            pytest.skip("No chunk dimensions available in loaded spool.")

        called: list[dict] = []
        expected = spool_widget._current_spool

        class _ChunkProxy:
            def chunk(self, **kwargs):
                called.append(kwargs)
                return expected

            def get_contents(self):
                return expected.get_contents()

            def __iter__(self):
                return iter(expected)

        spool_widget._current_spool = _ChunkProxy()
        spool_widget.chunk_value_edit.setText("")
        spool_widget.chunk_dim_combo.setCurrentIndex(0)
        assert called == []

    def test_add_select_row_creates_second_row(self, spool_widget):
        """The + button should append another select-filter row."""
        spool_widget.select_add_button.click()

        assert len(spool_widget._select_rows) == 2

    def test_select_rows_call_spool_select_with_all_kwargs(
        self, spool_widget, monkeypatch
    ):
        """Multiple select rows should be passed together into spool.select."""
        called: list[dict] = []
        expected = dc.get_example_spool()

        class _SelectProxy:
            def select(self, **kwargs):
                called.append(kwargs)
                return expected

            def get_contents(self):
                return expected.get_contents()

            def __iter__(self):
                return iter(expected)

        spool_widget._source_spool = _SelectProxy()
        spool_widget._display_spool = expected
        spool_widget._select_options = ("time", "distance", "tag")
        spool_widget.select_filters = [
            {"key": "time", "raw": "(0, 1)"},
            {"key": "tag", "raw": "'?bob'"},
        ]
        spool_widget._refresh_select_rows()
        spool_widget.select_add_button.click()
        third_combo, third_edit, _remove = _select_row(spool_widget, 2)
        third_combo.setCurrentText("distance")
        third_edit.setText("(10, 20)")
        third_edit.editingFinished.emit()

        assert called
        assert called[-1] == {
            "time": (0, 1),
            "tag": "?bob",
            "distance": (10, 20),
        }

    def test_remove_select_row_updates_persisted_filters(self, spool_widget):
        """Removing one row should drop it from the persisted filter list."""
        spool_widget._select_options = ("tag", "time")
        spool_widget.select_filters = [
            {"key": "tag", "raw": "'a'"},
            {"key": "time", "raw": "(0, 1)"},
        ]
        spool_widget._refresh_select_rows()

        _combo, _edit, remove = _select_row(spool_widget, 0)
        remove.click()

        assert len(spool_widget._select_rows) == 1
        assert spool_widget.select_filters == [{"key": "time", "raw": "(0, 1)"}]

    def test_legacy_single_filter_settings_migrate_to_select_filters(
        self, spool_widget
    ):
        """Legacy single-filter settings should restore into the first row."""
        spool_widget.select_filters = []
        spool_widget.select_col = "time_min"
        spool_widget.select_val = "1"
        spool_widget._migrate_select_filters()
        spool_widget._refresh_select_rows()

        combo, edit, _remove = _select_row(spool_widget)

        assert spool_widget.select_filters == [{"key": "time_min", "raw": "1"}]
        assert combo.currentText() == "time_min"
        assert edit.text() == "1"

    def test_multiple_select_rows_filter_real_spool_to_one_patch(
        self, spool_widget, monkeypatch, qtbot
    ):
        """Multiple select rows should combine into one real spool.select filter."""
        spool = _multi_select_spool()
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        spool_widget._set_source_spool(spool)
        first_combo, first_edit, _remove = _select_row(spool_widget, 0)
        first_combo.setCurrentText("tag")
        first_edit.setText("'bob'")
        first_edit.editingFinished.emit()

        spool_widget.select_add_button.click()
        second_combo, second_edit, _remove = _select_row(spool_widget, 1)
        second_combo.setCurrentText("distance_min")
        second_edit.setText("1000")
        second_edit.editingFinished.emit()
        wait_for_widget_idle(spool_widget, timeout=5.0)

        expected = spool.select(tag="bob", distance_min=1000)

        assert received
        assert _spool_tags(received[-1]) == _spool_tags(expected)
        assert len(list(received[-1])) == 1

    def test_multiple_select_rows_match_direct_spool_select(
        self, spool_widget, monkeypatch, qtbot
    ):
        """The widget multi-select path should match direct DASCore selection."""
        spool = _multi_select_spool()
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        spool_widget._set_source_spool(spool)
        first_combo, first_edit, _remove = _select_row(spool_widget, 0)
        first_combo.setCurrentText("distance_min")
        first_edit.setText("1000")
        first_edit.editingFinished.emit()

        spool_widget.select_add_button.click()
        second_combo, second_edit, _remove = _select_row(spool_widget, 1)
        second_combo.setCurrentText("tag")
        second_edit.setText("'alice'")
        second_edit.editingFinished.emit()
        wait_for_widget_idle(spool_widget, timeout=5.0)

        expected = spool.select(distance_min=1000, tag="alice")

        assert received
        assert _spool_tags(received[-1]) == _spool_tags(expected)
        assert len(list(received[-1])) == len(list(expected))

    def test_row_selection_filters_output_spool(self, spool_widget, monkeypatch, qtbot):
        """Selecting a row re-emits a spool containing only that patch."""
        multi_patch = next(
            (e for e in spool_widget._examples if "spool" in e.lower()),
            spool_widget._examples[0],
        )
        spool_widget.spool_input = multi_patch
        _run_and_wait(spool_widget, qtbot)

        received = capture_output(spool_widget.Outputs.spool, monkeypatch)
        spool_widget._table.selectRow(0)
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert len(received) == 1
        sent_spool = received[0]
        assert sent_spool is not None
        assert len(list(sent_spool)) == 1

    def test_selected_rows_use_direct_spool_indexing(self):
        """Selected-row extraction should use slicing rather than full iteration."""

        class _FakeSpool:
            def __init__(self, patches):
                self._patches = list(patches)
                self.slice_requests = []

            def __iter__(self):
                raise AssertionError("full spool iteration should not be used")

            def __getitem__(self, item):
                self.slice_requests.append(item)
                if isinstance(item, slice):
                    return self._patches[item]
                return self._patches[item]

        patches = [_patch_with_tag("first"), _patch_with_tag("second")]
        fake = _FakeSpool(patches)

        out = Spool._spool_rows_to_output(fake, {1})

        assert fake.slice_requests == [slice(1, 2, None)]
        assert len(list(out)) == 1
        assert next(iter(out)).attrs.tag == "second"

    def test_row_selection_emits_once_after_multiple_runs(
        self, spool_widget, monkeypatch, qtbot
    ):
        """Repeated runs should not duplicate selectionChanged signal connections."""
        multi_patch = next(
            (e for e in spool_widget._examples if "spool" in e.lower()),
            spool_widget._examples[0],
        )
        spool_widget.spool_input = multi_patch
        _run_and_wait(spool_widget, qtbot)
        _run_and_wait(spool_widget, qtbot)
        spool_widget._table.clearSelection()
        wait_for_widget_idle(spool_widget, timeout=5.0)

        received = capture_output(spool_widget.Outputs.spool, monkeypatch)
        spool_widget._table.selectRow(0)
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert len(received) == 1

    def test_selected_row_restore_scrolls_into_view_and_emits_patch(
        self, monkeypatch, qtbot
    ):
        """Restored row selection should be visible and re-emit its patch."""
        with widget_context(Spool) as first:
            first.show()
            qtbot.wait(10)
            first.spool_input = next(
                (e for e in first._examples if "spool" in e.lower()),
                first._examples[0],
            )
            _run_and_wait(first, qtbot)
            model = first._table.model()
            if model is None or model.rowCount() < 2:
                pytest.skip("Need at least two rows for selection restore test.")

            first._table.selectRow(1)
            wait_for_widget_idle(first, timeout=5.0)
            saved = first.settingsHandler.pack_data(first)

        with widget_context(Spool, stored_settings=saved) as second:
            scrolled_to: list[int] = []
            patch_received = capture_output(second.Outputs.patch, monkeypatch)
            original_scroll_to = second._table.scrollTo

            def _capture_scroll(index, hint=second._table.ScrollHint.EnsureVisible):
                scrolled_to.append(index.row())
                return original_scroll_to(index, hint)

            monkeypatch.setattr(second._table, "scrollTo", _capture_scroll)
            second.show()
            qtbot.wait(10)
            wait_for_widget_idle(second, timeout=5.0)

            selected = second._table.selectionModel().selectedRows()
            assert selected
            assert selected[0].row() == 1
            assert second.selected_source_row == 1
            assert scrolled_to and scrolled_to[-1] == 1
            assert patch_received
            assert patch_received[-1] is not None

    def test_select_dropdown_values_persist_across_settings_restore(self, qtbot):
        """Saved workflow settings should restore select-row dropdown choices."""
        with widget_context(Spool) as first:
            first.show()
            qtbot.wait(10)
            first.spool_input = next(
                (e for e in first._examples if "spool" in e.lower()),
                first._examples[0],
            )
            _run_and_wait(first, qtbot)

            first_combo, first_edit, _remove = _select_row(first, 0)
            first_key = next(
                key
                for key in ("tag", "distance_min", "time_min")
                if key in first._select_options
            )
            first_combo.setCurrentText(first_key)
            first_edit.setText("'bob'" if first_key == "tag" else "0")
            first_edit.editingFinished.emit()

            first.select_add_button.click()
            second_combo, second_edit, _remove = _select_row(first, 1)
            second_key = next(
                key
                for key in ("distance_min", "time_min", "tag")
                if key in first._select_options and key != first_key
            )
            second_combo.setCurrentText(second_key)
            second_edit.setText("1000" if second_key != "tag" else "'bob'")
            second_edit.editingFinished.emit()
            wait_for_widget_idle(first, timeout=5.0)
            saved = first.settingsHandler.pack_data(first)

        with widget_context(Spool, stored_settings=saved) as second:
            second.show()
            qtbot.wait(10)
            wait_for_widget_idle(second, timeout=5.0)

            assert len(second._select_rows) == 2
            first_combo, first_edit, _remove = _select_row(second, 0)
            second_combo, second_edit, _remove = _select_row(second, 1)
            assert first_combo.currentText() == first_key
            assert first_edit.text() == ("'bob'" if first_key == "tag" else "0")
            assert second_combo.currentText() == second_key
            assert second_edit.text() == ("1000" if second_key != "tag" else "'bob'")

    def test_unpack_checkbox_off_emits_no_patch(self, spool_widget, monkeypatch):
        """The patch output stays None when unpack is disabled."""
        spool_widget.spool_input = spool_widget._examples[0]
        spool_widget.run()
        spool_widget.unpack_single_patch = False
        patch_received = capture_output(spool_widget.Outputs.patch, monkeypatch)

        spool_widget._emit_current_output()

        assert patch_received == [None]

    def test_unpack_checkbox_on_emits_patch_for_single_patch_spool(
        self, spool_widget, monkeypatch
    ):
        """Enabling unpack emits a patch when the current spool has length one."""
        patch = _patch_with_tag("single")
        spool_widget._current_spool = dc.spool([patch])
        spool_widget.unpack_single_patch = True
        patch_received = capture_output(spool_widget.Outputs.patch, monkeypatch)

        spool_widget._emit_current_output()

        assert len(patch_received) == 1
        assert patch_received[0] is not None
        assert patch_received[0].attrs.tag == "single"

    def test_caption_shows_patch_emoji_for_active_patch_output(self, spool_widget):
        """The caption is decorated when Patch output is currently active."""
        patch = _patch_with_tag("single")
        spool_widget._current_spool = dc.spool([patch])
        spool_widget.unpack_single_patch = True

        spool_widget._emit_current_output()

        assert spool_widget.captionTitle == "Spool ⚡"

    def test_caption_clears_patch_emoji_for_multi_patch_output(self, spool_widget):
        """The caption returns to plain Spool when Patch output is inactive."""
        spool_widget._current_spool = dc.spool(
            [_patch_with_tag("first"), _patch_with_tag("second")]
        )
        spool_widget.unpack_single_patch = True

        spool_widget._emit_current_output()

        assert spool_widget.captionTitle == "Spool"

    def test_unpack_checkbox_on_emits_none_for_multi_patch_spool(
        self, spool_widget, monkeypatch
    ):
        """Enabling unpack does not emit a patch for multi-patch spools."""
        spool_widget._current_spool = dc.spool(
            [_patch_with_tag("first"), _patch_with_tag("second")]
        )
        spool_widget.unpack_single_patch = True
        patch_received = capture_output(spool_widget.Outputs.patch, monkeypatch)

        spool_widget._emit_current_output()

        assert patch_received == [None]

    def test_multi_patch_output_skips_single_patch_probe(
        self, spool_widget, monkeypatch
    ):
        """Multi-row outputs should not probe spool contents for a single patch."""
        spool_widget._current_spool = dc.spool(
            [_patch_with_tag("first"), _patch_with_tag("second")]
        )
        spool_widget._render_spool(spool_widget._current_spool)
        spool_widget.unpack_single_patch = True
        patch_received = capture_output(spool_widget.Outputs.patch, monkeypatch)

        monkeypatch.setattr(
            "derzug.widgets.spool.extract_single_patch",
            lambda _spool: (_ for _ in ()).throw(
                AssertionError("single-patch probe should be skipped")
            ),
        )

        spool_widget._emit_current_output()

        assert patch_received == [None]

    def test_unpack_checkbox_on_row_selection_emits_selected_patch(
        self, spool_widget, monkeypatch, qtbot
    ):
        """Selecting one row emits that patch on the Patch output when unpacking."""
        spool_widget._current_spool = dc.spool(
            [_patch_with_tag("first"), _patch_with_tag("second")]
        )
        spool_widget._render_spool(spool_widget._current_spool)
        spool_widget.unpack_single_patch = True
        patch_received = capture_output(spool_widget.Outputs.patch, monkeypatch)

        spool_widget._table.selectRow(0)
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert len(patch_received) == 1
        assert patch_received[0] is not None

    def test_unpack_checkbox_on_clearing_row_selection_emits_none(
        self, spool_widget, monkeypatch, qtbot
    ):
        """Clearing a single-row selection returns the Patch output to None."""
        spool_widget._current_spool = dc.spool(
            [_patch_with_tag("first"), _patch_with_tag("second")]
        )
        spool_widget._render_spool(spool_widget._current_spool)
        spool_widget.unpack_single_patch = True
        spool_widget._table.selectRow(0)
        wait_for_widget_idle(spool_widget, timeout=5.0)
        patch_received = capture_output(spool_widget.Outputs.patch, monkeypatch)

        spool_widget._table.clearSelection()
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert patch_received == [None]

    def test_caption_tracks_row_selection_patch_state(self, spool_widget, qtbot):
        """Selecting one row toggles the caption decoration on, then back off."""
        spool_widget._current_spool = dc.spool(
            [_patch_with_tag("first"), _patch_with_tag("second")]
        )
        spool_widget._render_spool(spool_widget._current_spool)
        spool_widget.unpack_single_patch = True

        spool_widget._table.selectRow(0)
        wait_for_widget_idle(spool_widget, timeout=5.0)
        assert spool_widget.captionTitle == "Spool ⚡"

        spool_widget._table.clearSelection()
        wait_for_widget_idle(spool_widget, timeout=5.0)
        assert spool_widget.captionTitle == "Spool"

    def test_clearing_row_selection_emits_full_spool(
        self, spool_widget, monkeypatch, qtbot
    ):
        """Clearing selection re-emits the full (unfiltered) spool."""
        spool_widget.spool_input = spool_widget._examples[0]
        _run_and_wait(spool_widget, qtbot)

        full_patch_count = len(list(spool_widget._current_spool))
        spool_widget._table.selectRow(0)
        wait_for_widget_idle(spool_widget, timeout=5.0)

        received = capture_output(spool_widget.Outputs.spool, monkeypatch)
        spool_widget._table.clearSelection()
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert len(received) == 1
        assert len(list(received[0])) == full_patch_count

    def test_table_cleared_on_no_selection(self, spool_widget):
        """run() with no selection clears the table view."""
        spool_widget.spool_input = spool_widget._examples[0]
        spool_widget.run()
        spool_widget.spool_input = None
        spool_widget.run()

        model = spool_widget._table.model()
        assert model is None or model.rowCount() == 0

    def test_step_next_item_selects_next_row(self, spool_widget):
        """step_next_item selects the next table row and wraps at the end."""
        spool_widget.spool_input = spool_widget._examples[0]
        spool_widget.run()
        model = spool_widget._table.model()
        if model is None or model.rowCount() < 2:
            pytest.skip("Need at least two rows for stepping test.")

        spool_widget._table.selectRow(0)
        assert spool_widget.step_next_item() is True
        selected = spool_widget._table.selectionModel().selectedRows()
        assert selected and selected[0].row() == 1

        spool_widget._table.selectRow(model.rowCount() - 1)
        assert spool_widget.step_next_item() is True
        selected = spool_widget._table.selectionModel().selectedRows()
        assert selected and selected[0].row() == 0

    def test_step_previous_item_selects_previous_row(self, spool_widget):
        """step_previous_item selects the previous table row and wraps at the start."""
        spool_widget.spool_input = spool_widget._examples[0]
        spool_widget.run()
        model = spool_widget._table.model()
        if model is None or model.rowCount() < 2:
            pytest.skip("Need at least two rows for stepping test.")

        spool_widget._table.selectRow(1)
        assert spool_widget.step_previous_item() is True
        selected = spool_widget._table.selectionModel().selectedRows()
        assert selected and selected[0].row() == 0

        spool_widget._table.selectRow(0)
        assert spool_widget.step_previous_item() is True
        selected = spool_widget._table.selectionModel().selectedRows()
        assert selected and selected[0].row() == model.rowCount() - 1

    def test_set_patch_appends_in_memory_spool(self, spool_widget, monkeypatch, qtbot):
        """Patch input appends to an in-memory spool and emits the updated spool."""
        first = _patch_with_tag("first")
        second = _patch_with_tag("second")
        spool_widget._current_spool = dc.spool([first])
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        spool_widget.set_patch(second)
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert received
        updated = received[-1]
        assert len(list(updated)) == 2
        assert len(list(spool_widget._current_spool)) == 2

    def test_set_spool_appends_in_memory_spool(self, spool_widget, monkeypatch, qtbot):
        """Spool input appends all incoming patches to an in-memory spool."""
        first = _patch_with_tag("first")
        second = _patch_with_tag("second")
        third = _patch_with_tag("third")
        spool_widget._current_spool = dc.spool([first])
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        spool_widget.set_spool(dc.spool([second, third]))
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert received
        updated = received[-1]
        assert len(list(updated)) == 3
        assert len(list(spool_widget._current_spool)) == 3

    def test_none_input_is_noop(self, spool_widget, monkeypatch):
        """None on the new inputs leaves the current spool unchanged."""
        first = _patch_with_tag("first")
        current = dc.spool([first])
        spool_widget._current_spool = current
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        spool_widget.set_patch(None)
        spool_widget.set_spool(None)

        assert received == []
        assert spool_widget._current_spool is current

    def test_input_uses_put_when_available(self, spool_widget, monkeypatch, qtbot):
        """Input ingestion prefers a spool's put method when it exists."""
        called: list[object] = []
        updated = dc.spool([_patch_with_tag("put-result")])

        class _PutSpool:
            def put(self, value):
                called.append(value)
                return updated

        spool_widget._current_spool = _PutSpool()
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        incoming = dc.spool([_patch_with_tag("incoming")])
        spool_widget.set_spool(incoming)
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert called == [incoming]
        assert received[-1] is updated
        assert spool_widget._current_spool is updated

    def test_set_patch_appends_directory_spool(
        self, spool_widget, monkeypatch, tmp_path, qtbot
    ):
        """Patch input persists into a directory-backed spool and reloads it."""
        first = _patch_with_tag("dir-first")
        second = _patch_with_tag("dir-second")
        directory = tmp_path / "spool_dir"
        directory.mkdir()
        dc.examples.spool_to_directory(dc.spool([first]), directory)
        spool_widget._current_spool = dc.spool(directory)
        assert isinstance(spool_widget._current_spool, DirectorySpool)
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        spool_widget.set_patch(second)
        wait_for_widget_idle(spool_widget, timeout=5.0)

        assert received
        updated = received[-1]
        assert isinstance(updated, DirectorySpool)
        assert Path(updated.spool_path) == directory
        assert len(list(updated)) == 2
        assert len(list(spool_widget._current_spool)) == 2

    def test_set_patch_rejects_file_backed_spool(
        self, spool_widget, monkeypatch, tmp_path
    ):
        """Patch input fails for file-backed spools and leaves state unchanged."""
        first = _patch_with_tag("file-first")
        second = _patch_with_tag("file-second")
        file_path = tmp_path / "single.h5"
        dc.write(dc.spool([first]), file_path, file_format="DASDAE")
        current = dc.spool(file_path)
        assert isinstance(current, FileSpool)
        spool_widget._current_spool = current
        received = capture_output(spool_widget.Outputs.spool, monkeypatch)

        spool_widget.set_patch(second)

        assert received == []
        assert spool_widget._current_spool is current
        assert spool_widget.Error.general.is_shown()

    def test_append_uses_source_spool_not_chunked_display(
        self, spool_widget, monkeypatch
    ):
        """Incoming data appends to the base source spool."""
        first = _patch_with_tag("first")
        second = _patch_with_tag("second")
        derived = dc.spool([_patch_with_tag("derived-only")])
        spool_widget._current_spool = dc.spool([first])
        monkeypatch.setattr(
            spool_widget, "_apply_chunk_transform", lambda spool: derived
        )
        monkeypatch.setattr(spool_widget, "_render_spool", lambda spool: None)

        spool_widget._recompute_display_spool()
        assert _spool_tags(spool_widget._display_spool) == ["derived-only"]

        spool_widget.set_patch(second)

        assert _spool_tags(spool_widget._current_spool) == ["first", "second"]
        assert _spool_tags(spool_widget._display_spool) == ["derived-only"]


class TestSpoolDefaults(TestWidgetDefaults):
    """Shared default/smoke tests for Spool."""

    __test__ = True
    widget = Spool
