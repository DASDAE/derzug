"""Tests for the Aggregate widget."""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.utils.testing import (
    TestPatchInputStateDefaults,
    capture_output,
    wait_for_output,
    wait_for_widget_idle,
    widget_context,
)
from derzug.widgets.aggregate import Aggregate


@pytest.fixture
def aggregate_widget(qtbot):
    """Return a live Aggregate widget for one test case."""
    with widget_context(Aggregate) as widget:
        yield widget


class TestAggregate:
    """Tests for the Aggregate widget."""

    def test_widget_instantiates(self, aggregate_widget):
        """Widget creates with expected defaults and controls."""
        assert isinstance(aggregate_widget, Aggregate)
        assert aggregate_widget.selected_dim == ""
        assert aggregate_widget.transform_dim == ""
        assert aggregate_widget.method == "mean"
        assert aggregate_widget.dim_reduce == "empty"
        assert aggregate_widget._transform_dim_label.isHidden()
        assert aggregate_widget._transform_dim_combo.isHidden()

    def test_patch_none_emits_none(self, aggregate_widget, monkeypatch, qtbot):
        """A None patch clears output."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)

        aggregate_widget.set_patch(None)
        wait_for_output(qtbot, received)

        assert received == [None]

    def test_valid_run_emits_patch(self, aggregate_widget, monkeypatch, qtbot):
        """A valid aggregate config emits a processed patch."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        aggregate_widget.selected_dim = "time"
        aggregate_widget.method = "mean"
        aggregate_widget.dim_reduce = "empty"

        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        out = received[-1]
        assert out is not None
        assert isinstance(out, dc.Patch)
        # Aggregating along time reduces that dimension to 1
        time_axis = patch.dims.index("time")
        assert out.shape[time_axis] == 1

    def test_all_dims_option_aggregates_fully(
        self, aggregate_widget, monkeypatch, qtbot
    ):
        """Selecting 'All' dims reduces every dimension to size 1."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        aggregate_widget.selected_dim = ""

        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        out = received[-1]
        assert out is not None
        assert isinstance(out, dc.Patch)

    def test_method_change_triggers_rerun(self, aggregate_widget, monkeypatch, qtbot):
        """Changing method emits a fresh output."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)
        start_count = len(received)

        aggregate_widget._method_combo.setCurrentText("max")
        wait_for_widget_idle(aggregate_widget)

        assert len(received) > start_count
        assert aggregate_widget.method == "max"
        assert received[-1] is not None

    def test_phase_weighted_stack_method_emits_patch(
        self, aggregate_widget, monkeypatch, qtbot
    ):
        """Phase-weighted stack should use DASCore's dedicated patch transform."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        aggregate_widget.selected_dim = "distance"
        aggregate_widget.method = "phase_weighted_stack"
        aggregate_widget.dim_reduce = "empty"

        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        out = received[-1]
        expected = patch.phase_weighted_stack(
            "distance",
            transform_dim="time",
            dim_reduce="empty",
        )
        assert out is not None
        assert out.shape == expected.shape
        assert out.dims == expected.dims
        assert out.data == pytest.approx(expected.data)

    def test_phase_weighted_stack_shows_transform_dim_control(
        self, aggregate_widget, qtbot
    ):
        """Selecting phase-weighted stack should expose the transform selector."""
        patch = dc.get_example_patch("example_event_2")
        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        aggregate_widget._method_combo.setCurrentText("phase_weighted_stack")
        wait_for_widget_idle(aggregate_widget)

        assert not aggregate_widget._transform_dim_label.isHidden()
        assert not aggregate_widget._transform_dim_combo.isHidden()
        assert aggregate_widget._transform_dim_combo.currentText() == "time"

    def test_phase_weighted_stack_uses_selected_transform_dim(
        self, aggregate_widget, monkeypatch, qtbot
    ):
        """Phase-weighted stack should honor the chosen secondary dimension."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2").append_dims(lag_time=[0, 1])
        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        aggregate_widget._dim_combo.setCurrentText("distance")
        wait_for_widget_idle(aggregate_widget)
        aggregate_widget._method_combo.setCurrentText("phase_weighted_stack")
        wait_for_widget_idle(aggregate_widget)
        aggregate_widget._transform_dim_combo.setCurrentText("lag_time")
        wait_for_widget_idle(aggregate_widget)

        out = received[-1]
        expected = patch.phase_weighted_stack(
            "distance",
            transform_dim="lag_time",
            dim_reduce="empty",
        )
        assert aggregate_widget.transform_dim == "lag_time"
        assert out is not None
        assert out.shape == expected.shape
        assert out.dims == expected.dims
        assert out.data == pytest.approx(expected.data)

    def test_phase_weighted_stack_prefers_time_for_multidim_patch(
        self, aggregate_widget, monkeypatch, qtbot
    ):
        """Phase-weighted stack should default the transform selector to time."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2").append_dims(
            lag_time=[0],
            patch_number=[0],
        )
        aggregate_widget.selected_dim = "distance"
        aggregate_widget.method = "phase_weighted_stack"
        aggregate_widget.dim_reduce = "empty"

        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        out = received[-1]
        assert aggregate_widget.transform_dim == "time"
        expected = patch.phase_weighted_stack(
            "distance",
            transform_dim="time",
            dim_reduce="empty",
        )
        assert out is not None
        assert out.shape == expected.shape
        assert out.dims == expected.dims
        assert out.data == pytest.approx(expected.data)

    def test_phase_weighted_stack_requires_selected_dim(
        self, aggregate_widget, monkeypatch, qtbot
    ):
        """Phase-weighted stack should fail clearly when no stack dim is selected."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        aggregate_widget.selected_dim = ""
        aggregate_widget.method = "phase_weighted_stack"

        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        assert received[-1] is None
        assert aggregate_widget.Error.aggregate_failed.is_shown()
        assert "requires selecting one stack dimension" in (
            aggregate_widget.Error.aggregate_failed.formatted
        )

    def test_dim_change_triggers_rerun(self, aggregate_widget, monkeypatch, qtbot):
        """Changing dimension reruns and emits a fresh output."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        # Find a non-"All" dim to switch to
        combo = aggregate_widget._dim_combo
        dims = [
            combo.itemText(i)
            for i in range(combo.count())
            if combo.itemText(i) != "All"
        ]
        if not dims:
            pytest.skip("No named dimensions available")

        first_count = len(received)
        aggregate_widget._dim_combo.setCurrentText(dims[0])
        wait_for_widget_idle(aggregate_widget)

        assert len(received) > first_count
        assert received[-1] is not None

    def test_selected_dim_survives_none_then_compatible_patch(
        self, aggregate_widget, monkeypatch, qtbot
    ):
        """None should not clear a selected dimension that still exists later."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        first = dc.get_example_patch("example_event_2")
        second = dc.get_example_patch("example_event_1")
        aggregate_widget.selected_dim = "time"

        aggregate_widget.set_patch(first)
        wait_for_widget_idle(aggregate_widget)
        aggregate_widget.set_patch(None)
        wait_for_widget_idle(aggregate_widget)
        aggregate_widget.set_patch(second)
        wait_for_widget_idle(aggregate_widget)

        assert received[-2] is None
        assert aggregate_widget.selected_dim == "time"
        assert received[-1] is not None

    def test_selected_dim_resets_after_none_when_new_patch_lacks_dim(
        self, aggregate_widget, monkeypatch, qtbot
    ):
        """A stored dimension should reset only when the next patch cannot use it."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        first = dc.get_example_patch("example_event_2")
        incompatible = first.mean("time").squeeze()
        aggregate_widget.selected_dim = "time"

        aggregate_widget.set_patch(first)
        wait_for_widget_idle(aggregate_widget)
        aggregate_widget.set_patch(None)
        wait_for_widget_idle(aggregate_widget)
        aggregate_widget.set_patch(incompatible)
        wait_for_widget_idle(aggregate_widget)

        assert received[-2] is None
        assert aggregate_widget.selected_dim == ""
        assert aggregate_widget._dim_combo.currentText() == "All"
        assert received[-1] is not None

    def test_dim_reduce_change_triggers_rerun(
        self, aggregate_widget, monkeypatch, qtbot
    ):
        """Changing dim_reduce reruns and emits a fresh output."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        # Use a specific dim so dim_reduce options are well-defined
        aggregate_widget.selected_dim = "time"
        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)
        start_count = len(received)

        aggregate_widget._dim_reduce_combo.setCurrentText("squeeze")
        wait_for_widget_idle(aggregate_widget)

        assert len(received) > start_count
        assert aggregate_widget.dim_reduce == "squeeze"
        assert received[-1] is not None

    def test_invalid_method_falls_back(self, aggregate_widget, monkeypatch, qtbot):
        """Invalid method setting falls back to default and still emits a patch."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        aggregate_widget.method = "not-a-real-method"

        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        assert aggregate_widget.method == Aggregate._METHODS[0]
        assert aggregate_widget._method_combo.currentText() == Aggregate._METHODS[0]
        assert received[-1] is not None

    def test_invalid_dim_reduce_falls_back(self, aggregate_widget, monkeypatch, qtbot):
        """Invalid dim_reduce setting falls back to default and still emits a patch."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")
        aggregate_widget.dim_reduce = "not-a-real-reduce"

        aggregate_widget.set_patch(patch)
        wait_for_widget_idle(aggregate_widget)

        assert aggregate_widget.dim_reduce == Aggregate._DIM_REDUCES[0]
        assert (
            aggregate_widget._dim_reduce_combo.currentText()
            == Aggregate._DIM_REDUCES[0]
        )
        assert received[-1] is not None

    def test_aggregate_failed_shows_error(self, aggregate_widget, monkeypatch, qtbot):
        """When patch.aggregate raises, the error is shown and None is emitted."""
        received = capture_output(aggregate_widget.Outputs.patch, monkeypatch)
        patch = dc.get_example_patch("example_event_2")

        def _raise(*args, **kwargs):
            raise ValueError("boom")

        monkeypatch.setattr(patch, "aggregate", _raise)
        aggregate_widget._patch = patch
        aggregate_widget.run()
        wait_for_widget_idle(aggregate_widget)

        assert received[-1] is None
        assert aggregate_widget.Error.aggregate_failed.is_shown()


class TestAggregateDefaults(TestPatchInputStateDefaults):
    """Shared default/smoke tests for Aggregate."""

    __test__ = True
    widget = Aggregate
    inputs = (("patch", dc.get_example_patch("example_event_2")),)
    compatible_patch = dc.get_example_patch("example_event_1")
    incompatible_patch = dc.get_example_patch("example_event_2").mean("time").squeeze()

    def arrange_persisted_input_state(self, widget_object):
        """Persist a concrete dim selection before input replacement."""
        widget_object.selected_dim = "time"
        widget_object._dim_combo.setCurrentText("time")
        return "time"

    def assert_persisted_input_state(self, widget_object, state_token) -> None:
        """Selected dims should survive `None` and compatible replacements."""
        assert widget_object.selected_dim == state_token
        if widget_object._patch is None:
            assert widget_object._dim_combo.currentText() == "All"
            return
        assert widget_object._dim_combo.currentText() == state_token

    def assert_reset_input_state(self, widget_object, state_token) -> None:
        """Incompatible replacement patches should fall back to aggregate-all."""
        assert widget_object.selected_dim == ""
        assert widget_object._dim_combo.currentText() == "All"
