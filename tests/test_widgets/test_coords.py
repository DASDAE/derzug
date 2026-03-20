"""Tests for the Coords widget."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.utils.testing import (
    TestWidgetDefaults,
    capture_output,
    wait_for_output,
    widget_context,
)
from derzug.widgets.coords import Coords


@pytest.fixture
def coords_widget(qtbot):
    """Return a live Coords widget."""
    with widget_context(Coords) as widget:
        widget.show()
        qtbot.wait(10)
        yield widget


def _patch_with_non_dim_coord() -> dc.Patch:
    """Return an example patch with an extra coordinate along distance."""
    patch = dc.get_example_patch("example_event_2")
    channels = np.arange(patch.shape[0])
    return patch.update_coords(channel=("distance", channels))


def _patch_with_datetime_time() -> dc.Patch:
    """Return the example patch with an absolute datetime time dimension."""
    patch = dc.get_example_patch("example_event_2")
    count = patch.shape[patch.dims.index("time")]
    time = np.datetime64("2024-01-02T03:04:05") + np.arange(count).astype(
        "timedelta64[ms]"
    )
    return patch.update_coords(time=time)


def _stored_set_coords_settings() -> dict[str, object]:
    """Return stored settings matching the checked-in basic DSS workflow."""
    return {
        "operation": "set_coords",
        "set_coords_applied_dim": "distance",
        "set_coords_applied_start": "0",
        "set_coords_applied_step": "",
        "set_coords_applied_stop": "",
        "set_coords_dim": "distance",
        "set_coords_start": "0",
        "set_coords_step": "",
        "set_coords_stop": "",
        "transpose_order": ["distance", "time"],
    }


class TestCoords:
    """Behavioral tests for the Coords widget."""

    def test_widget_instantiates(self, coords_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(coords_widget, Coords)
        assert coords_widget.operation == "rename_coords"
        assert coords_widget.rename_rows == [["", ""]]
        assert coords_widget.transpose_order == []

    def test_build_preview_state_for_input_patch(self, coords_widget):
        """Preview text should be derived by the pure summary builder."""
        patch = dc.get_example_patch("example_event_2")
        coords_widget.set_patch(patch)

        preview = coords_widget._build_preview_state(patch)

        assert preview.input_text == coords_widget._patch_summary(patch)
        assert preview.active_text == "Rename: no mappings"
        assert preview.output_text == coords_widget._patch_summary(patch)

    def test_set_patch_refreshes_once_after_run(self, coords_widget, monkeypatch):
        """Visible patch updates should not refresh once with a stale prior result."""
        patch = dc.get_example_patch("example_event_2")
        coords_widget.operation = "drop_coords"
        refresh_results: list[object] = []
        original = coords_widget._refresh_ui

        def _wrapped():
            refresh_results.append(coords_widget._last_result)
            return original()

        monkeypatch.setattr(coords_widget, "_refresh_ui", _wrapped)

        coords_widget.set_patch(patch)

        assert len(refresh_results) == 1
        assert refresh_results[0] is not None

    def test_patch_none_emits_none(self, coords_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)

        coords_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_valid_rename_emits_patch(self, coords_widget, monkeypatch, qtbot):
        """Rename mappings are passed through to patch.rename_coords."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_rename_coords(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "rename_coords", _fake_rename_coords)
        coords_widget.operation = "rename_coords"
        coords_widget.rename_rows = [["distance", "channel"]]
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured == {"distance": "channel"}

    def test_invalid_rename_reference_shows_error(
        self, coords_widget, monkeypatch, qtbot
    ):
        """Missing rename sources show an error and emit None."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        coords_widget.operation = "rename_coords"
        coords_widget.rename_rows = [["missing", "channel"]]

        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert coords_widget.Error.invalid_mapping.is_shown()

    def test_drop_coords_uses_only_non_dimensional_options(
        self, coords_widget, monkeypatch, qtbot
    ):
        """Drop coords applies to non-dimensional coordinates."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = _patch_with_non_dim_coord()
        captured: dict[str, object] = {}

        def _fake_drop_coords(*coords):
            captured["coords"] = coords
            return patch

        monkeypatch.setattr(patch, "drop_coords", _fake_drop_coords)
        coords_widget.operation = "drop_coords"
        coords_widget.drop_coords_selected = ["channel"]
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["coords"] == ("channel",)
        items = [
            coords_widget._drop_list.item(i).text()
            for i in range(coords_widget._drop_list.count())
        ]
        assert items == ["channel"]

    def test_sort_reverse_reaches_patch(self, coords_widget, monkeypatch, qtbot):
        """Sort selections and reverse flag are passed through."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = _patch_with_non_dim_coord()
        captured: dict[str, object] = {}

        def _fake_sort_coords(*coords, reverse=False):
            captured["coords"] = coords
            captured["reverse"] = reverse
            return patch

        monkeypatch.setattr(patch, "sort_coords", _fake_sort_coords)
        coords_widget.operation = "sort_coords"
        coords_widget.sort_coords_selected = ["channel", "time"]
        coords_widget.sort_reverse = True
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["coords"] == ("channel", "time")
        assert captured["reverse"] is True

    def test_set_dims_mapping_reaches_patch(self, coords_widget, monkeypatch, qtbot):
        """Set dims mappings are passed through as dimension-to-coordinate kwargs."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = _patch_with_non_dim_coord()
        captured: dict[str, object] = {}

        def _fake_set_dims(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "set_dims", _fake_set_dims)
        coords_widget.operation = "set_dims"
        coords_widget.set_dims_rows = [["distance", "channel"]]
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured == {"distance": "channel"}

    def test_set_coords_start_only_translates_coord(
        self, coords_widget, monkeypatch, qtbot
    ):
        """A start-only set_coords keeps the current step and translates the coord."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_update_coords(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "update_coords", _fake_update_coords)
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        coords_widget.operation = "set_coords"
        coords_widget._refresh_ui()
        coords_widget._set_coords_dim_combo.setCurrentText("distance")
        coords_widget._set_coords_start_edit.setText("0")
        coords_widget._on_set_coords_text_changed("start", "0")
        coords_widget._set_coords_start_edit.editingFinished.emit()

        wait_for_output(qtbot, received, 2)

        coord = captured["distance"]
        assert coord.start == 0
        assert coord.step == patch.coords.get_coord("distance").step
        assert coords_widget.set_coords_stop == ""
        assert coords_widget.set_coords_step == ""
        assert coords_widget.set_coords_applied_start == "0"
        assert coords_widget.set_coords_applied_stop == ""
        assert coords_widget.set_coords_applied_step == ""

    def test_set_coords_start_and_stop_infer_step(
        self, coords_widget, monkeypatch, qtbot
    ):
        """Set coords infers step from start/stop and dimension length."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_update_coords(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "update_coords", _fake_update_coords)
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        coords_widget.operation = "set_coords"
        coords_widget._refresh_ui()
        coords_widget._set_coords_dim_combo.setCurrentText("distance")
        coords_widget._set_coords_start_edit.setText("5")
        coords_widget._on_set_coords_text_changed("start", "5")
        coords_widget._set_coords_stop_edit.setText("1207")
        coords_widget._on_set_coords_text_changed("stop", "1207")
        coords_widget._set_coords_stop_edit.editingFinished.emit()

        wait_for_output(qtbot, received, 2)

        coord = captured["distance"]
        assert coord.start == 5
        assert coord.stop == 1207
        assert coord.step == 2
        assert coords_widget.set_coords_step == ""
        assert coords_widget.set_coords_applied_step == ""

    def test_set_coords_stop_only_translates_coord(
        self, coords_widget, monkeypatch, qtbot
    ):
        """A stop-only set_coords keeps the current step and translates the coord."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_update_coords(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "update_coords", _fake_update_coords)
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        coords_widget.operation = "set_coords"
        coords_widget._refresh_ui()
        coords_widget._set_coords_dim_combo.setCurrentText("distance")
        coords_widget._set_coords_stop_edit.setText("1202")
        coords_widget._on_set_coords_text_changed("stop", "1202")
        coords_widget._set_coords_stop_edit.editingFinished.emit()

        wait_for_output(qtbot, received, 2)

        coord = captured["distance"]
        assert coord.start == 601
        assert coord.stop == 1202
        assert coord.step == patch.coords.get_coord("distance").step
        assert coords_widget.set_coords_start == ""
        assert coords_widget.set_coords_step == ""
        assert coords_widget.set_coords_applied_start == ""
        assert coords_widget.set_coords_applied_step == ""

    def test_set_coords_step_only_keeps_current_start(
        self, coords_widget, monkeypatch, qtbot
    ):
        """A step-only set_coords keeps the current start and recomputes stop."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_update_coords(**kwargs):
            captured.update(kwargs)
            return patch

        monkeypatch.setattr(patch, "update_coords", _fake_update_coords)
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        coords_widget.operation = "set_coords"
        coords_widget._refresh_ui()
        coords_widget._set_coords_dim_combo.setCurrentText("distance")
        coords_widget._set_coords_step_edit.setText("2")
        coords_widget._on_set_coords_text_changed("step", "2")
        coords_widget._set_coords_step_edit.editingFinished.emit()

        wait_for_output(qtbot, received, 2)

        coord = captured["distance"]
        expected = patch.coords.get_coord("distance")
        assert coord.start == expected.start
        assert coord.step == 2
        assert coords_widget.set_coords_start == ""
        assert coords_widget.set_coords_stop == ""
        assert coords_widget.set_coords_applied_start == ""
        assert coords_widget.set_coords_applied_stop == ""

    def test_set_coords_draft_edits_do_not_emit_until_apply(
        self, coords_widget, monkeypatch, qtbot
    ):
        """Draft set-coords changes stay local until the edit is committed."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        coords_widget._on_operation_changed("Set Coords")
        wait_for_output(qtbot, received, 2)
        coords_widget._set_coords_start_edit.setText("0")
        coords_widget._on_set_coords_text_changed("start", "0")
        coords_widget._set_coords_step_edit.setText("1")
        coords_widget._on_set_coords_text_changed("step", "1")
        qtbot.wait(50)

        assert len(received) == 2
        coords_widget._set_coords_step_edit.editingFinished.emit()
        wait_for_output(qtbot, received, 3)

    def test_set_coords_reapplies_on_replacement_patch(
        self, coords_widget, monkeypatch, qtbot
    ):
        """A replacement patch with the same dimension reapplies sparse set_coords."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        first = dc.get_example_patch("example_event_2")
        second = dc.get_example_patch("example_event_1")
        first_calls: dict[str, object] = {}
        second_calls: dict[str, object] = {}

        def _first_update_coords(**kwargs):
            first_calls["coord"] = kwargs["distance"]
            return first

        monkeypatch.setattr(first, "update_coords", _first_update_coords)

        def _second_update_coords(**kwargs):
            second_calls["coord"] = kwargs["distance"]
            return second

        monkeypatch.setattr(second, "update_coords", _second_update_coords)
        coords_widget.set_patch(first)
        wait_for_output(qtbot, received)
        coords_widget._on_operation_changed("Set Coords")
        wait_for_output(qtbot, received, 2)
        coords_widget._set_coords_dim_combo.setCurrentText("distance")
        coords_widget._set_coords_start_edit.setText("0")
        coords_widget._on_set_coords_text_changed("start", "0")
        coords_widget._set_coords_start_edit.editingFinished.emit()

        wait_for_output(qtbot, received, 3)
        coords_widget.set_patch(second)
        wait_for_output(qtbot, received, 4)

        assert first_calls["coord"].start == 0
        assert second_calls["coord"].start == 0
        assert first_calls["coord"].shape == (first.shape[0],)
        assert second_calls["coord"].shape == (second.shape[0],)

    @pytest.mark.parametrize(
        "example_name",
        ("febus_dss_mine_tight", "febus_dss_mine_loose"),
    )
    def test_set_coords_restored_settings_emit_zero_based_febus_distance(
        self, example_name, monkeypatch, qtbot
    ):
        """Stored workflow settings should rebuild zero-based distance coords."""
        patch = dc.examples.EXAMPLE_PATCHES[example_name]()

        with widget_context(
            Coords,
            stored_settings=_stored_set_coords_settings(),
        ) as widget:
            widget.show()
            qtbot.wait(10)
            received = capture_output(widget.Outputs.patch, monkeypatch)

            widget.set_patch(patch)
            wait_for_output(qtbot, received)

            out = received[-1]
            coord = out.coords.get_coord("distance")
            assert coord.start == 0.0
            assert out.get_array("distance")[0] == 0.0
            assert widget.set_coords_applied_dim == "distance"
            assert widget.set_coords_applied_start == "0"

    def test_set_coords_datetime_values_parse_and_apply(
        self, coords_widget, monkeypatch, qtbot
    ):
        """Set coords should parse datetime start/step values for time dims."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = _patch_with_datetime_time()
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        coords_widget._on_operation_changed("Set Coords")
        wait_for_output(qtbot, received, 2)
        coords_widget._set_coords_dim_combo.setCurrentText("time")
        coords_widget._set_coords_start_edit.setText("2024-01-03T00:00:00")
        coords_widget._on_set_coords_text_changed("start", "2024-01-03T00:00:00")
        coords_widget._set_coords_step_edit.setText("2")
        coords_widget._on_set_coords_text_changed("step", "2")
        coords_widget._set_coords_step_edit.editingFinished.emit()

        wait_for_output(qtbot, received, 3)

        out = received[-1]
        coord = out.coords.get_coord("time")
        assert np.issubdtype(coord.dtype, np.datetime64)
        assert coord.start == np.datetime64("2024-01-03T00:00:00")
        assert coord.step == np.timedelta64(2, "ms")
        assert coords_widget.set_coords_stop == ""

    def test_set_coords_invalid_input_shows_error(
        self, coords_widget, monkeypatch, qtbot
    ):
        """Set coords rejects unparsable committed values."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        coords_widget._on_operation_changed("Set Coords")
        wait_for_output(qtbot, received, 2)
        coords_widget._set_coords_dim_combo.setCurrentText("distance")
        coords_widget._set_coords_start_edit.setText("oops")
        coords_widget._on_set_coords_text_changed("start", "oops")

        coords_widget._set_coords_start_edit.editingFinished.emit()
        qtbot.wait(50)

        assert len(received) == 2
        assert coords_widget.Error.invalid_set_coords.is_shown()
        assert coords_widget.set_coords_applied_dim == ""

    def test_transpose_reorders_dims(self, coords_widget, monkeypatch, qtbot):
        """Transpose uses the configured dimension order."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_transpose(*dims):
            captured["dims"] = dims
            return patch

        monkeypatch.setattr(patch, "transpose", _fake_transpose)
        coords_widget.operation = "transpose"
        coords_widget.transpose_order = ["time", "distance"]
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["dims"] == ("time", "distance")

    def test_flip_selected_dims_reach_patch(self, coords_widget, monkeypatch, qtbot):
        """Flip forwards data-only dim flips through patch.flip."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        captured: dict[str, object] = {}

        def _fake_flip(*dims, flip_coords=True):
            captured["dims"] = dims
            captured["flip_coords"] = flip_coords
            return patch

        monkeypatch.setattr(patch, "flip", _fake_flip)
        coords_widget.operation = "flip"
        coords_widget.flip_dims_selected = ["time"]
        coords_widget.flip_data = True
        coords_widget.flip_coords = False
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is patch
        assert captured["dims"] == ("time",)
        assert captured["flip_coords"] is False

    def test_flip_coord_only_updates_coords_without_flipping_data(
        self, coords_widget, monkeypatch, qtbot
    ):
        """Coord-only flip should update coords without calling patch.flip."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = _patch_with_non_dim_coord()
        flipped_patch = patch.update(coords=patch.coords.flip("channel"))
        flip_calls: list[tuple[tuple[str, ...], bool]] = []

        def _fake_flip(*dims, flip_coords=True):
            flip_calls.append((dims, flip_coords))
            return patch

        monkeypatch.setattr(patch, "flip", _fake_flip)
        coords_widget.operation = "flip"
        coords_widget.flip_dims_selected = ["channel"]
        coords_widget.flip_data = False
        coords_widget.flip_coords = True
        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert flip_calls == []
        assert received[-1] is not None
        assert np.array_equal(received[-1].data, patch.data)
        assert np.array_equal(
            received[-1].get_array("channel"), flipped_patch.get_array("channel")
        )

    def test_flip_data_rejects_non_dim_coords(self, coords_widget, monkeypatch, qtbot):
        """Data flip should fail clearly when non-dimensional coords are selected."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = _patch_with_non_dim_coord()
        coords_widget.operation = "flip"
        coords_widget.flip_dims_selected = ["channel"]
        coords_widget.flip_data = True
        coords_widget.flip_coords = False

        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert coords_widget.Error.operation_failed.is_shown()

    def test_flip_active_summary_describes_selected_dims(self, coords_widget):
        """Preview text should summarize flip state."""
        coords_widget.operation = "flip"
        coords_widget.flip_dims_selected = ["distance", "time"]
        coords_widget.flip_data = True
        coords_widget.flip_coords = True

        assert coords_widget._active_summary() == "Flip: distance, time (data, coords)"

    def test_transpose_order_falls_back_on_replacement_patch(
        self, coords_widget, monkeypatch, qtbot
    ):
        """Transpose order is reconciled against replacement patch dims."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        replaced = patch.rename_coords(time="seconds")
        coords_widget.operation = "transpose"
        coords_widget.transpose_order = ["time", "distance"]

        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)
        coords_widget.set_patch(replaced)
        wait_for_output(qtbot, received, 2)

        assert coords_widget.transpose_order == ["distance", "seconds"]
        assert received[-1] is not None

    def test_invalid_sort_selection_shows_error(
        self, coords_widget, monkeypatch, qtbot
    ):
        """Saved coord selections that are missing on the patch fail clearly."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        coords_widget.operation = "sort_coords"
        coords_widget.sort_coords_selected = ["missing"]

        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert received[-1] is None
        assert coords_widget.Error.invalid_selection.is_shown()

    def test_preview_updates_after_success(self, coords_widget, monkeypatch, qtbot):
        """The main-area summary shows active config and output shape metadata."""
        received = capture_output(coords_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        coords_widget.operation = "rename_coords"
        coords_widget.rename_rows = [["distance", "channel"]]

        coords_widget.set_patch(patch)
        wait_for_output(qtbot, received)

        assert "dims=distance, time" in coords_widget._input_label.text()
        assert "Rename: distance->channel" == coords_widget._active_label.text()
        assert "coords=time, channel" in coords_widget._output_label.text()


class TestCoordsDefaults(TestWidgetDefaults):
    """Shared default/smoke tests for Coords."""

    __test__ = True
    widget = Coords
    inputs = (("patch", dc.get_example_patch("example_event_2")),)
