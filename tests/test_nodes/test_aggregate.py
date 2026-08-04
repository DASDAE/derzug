"""Tests for the Qt-free Aggregate node."""

from __future__ import annotations

import dascore as dc
import pytest
from derzug.nodes.aggregate import (
    AggregateParams,
    aggregate_task_from_params,
    default_phase_weighted_stack_dim,
)


class TestDefaultPhaseWeightedStackDim:
    """Tests for the shared phase-weighted-stack default stack dim."""

    def test_prefers_distance(self):
        """Distance wins whenever the patch has it."""
        assert default_phase_weighted_stack_dim(("time", "distance")) == "distance"

    def test_falls_back_to_first_dim(self):
        """Without distance the first patch dim wins."""
        assert default_phase_weighted_stack_dim(("depth", "time")) == "depth"

    def test_empty_dims_return_none(self):
        """No dims means no default."""
        assert default_phase_weighted_stack_dim(()) is None


class TestAggregateTaskPhaseWeightedStack:
    """Headless behavior of the phase-weighted-stack method."""

    def test_unset_stack_dim_defaults_like_the_widget(self):
        """An empty selected_dim runs with the shared default instead of raising."""
        patch = dc.get_example_patch("example_event_2")
        params = AggregateParams(method="phase_weighted_stack", selected_dim="")

        out = aggregate_task_from_params(params).run(patch)

        expected = patch.phase_weighted_stack(
            "distance", transform_dim="time", dim_reduce="empty"
        )
        assert out.dims == expected.dims
        assert out.shape == expected.shape
        assert out.data == pytest.approx(expected.data)

    def test_explicit_stack_dim_still_wins(self):
        """A concrete selected_dim is used unchanged."""
        patch = dc.get_example_patch("example_event_2")
        params = AggregateParams(method="phase_weighted_stack", selected_dim="time")

        out = aggregate_task_from_params(params).run(patch)

        expected = patch.phase_weighted_stack(
            "time", transform_dim="distance", dim_reduce="empty"
        )
        assert out.dims == expected.dims
        assert out.shape == expected.shape

    def test_transform_dim_equal_to_defaulted_stack_dim_is_reinferred(self):
        """A saved transform dim colliding with the resolved stack dim re-infers."""
        patch = dc.get_example_patch("example_event_2")
        params = AggregateParams(
            method="phase_weighted_stack", selected_dim="", transform_dim="distance"
        )

        out = aggregate_task_from_params(params).run(patch)

        expected = patch.phase_weighted_stack(
            "distance", transform_dim="time", dim_reduce="empty"
        )
        assert out.dims == expected.dims
        assert out.shape == expected.shape

    def test_stale_stack_dim_resets_like_the_widget(self):
        """A selected_dim missing from the patch falls back to the default."""
        patch = dc.get_example_patch("example_event_2")
        params = AggregateParams(method="phase_weighted_stack", selected_dim="stale")

        out = aggregate_task_from_params(params).run(patch)

        expected = patch.phase_weighted_stack(
            "distance", transform_dim="time", dim_reduce="empty"
        )
        assert out.dims == expected.dims
        assert out.shape == expected.shape


class TestAggregateTaskStaleDims:
    """Stale persisted dims must behave the same on and off the canvas."""

    def test_plain_aggregate_with_stale_dim_reduces_all(self):
        """A stale dim aggregates over all dims, like the widget's reset to All."""
        patch = dc.get_example_patch("example_event_2")
        params = AggregateParams(method="mean", selected_dim="stale")

        out = aggregate_task_from_params(params).run(patch)

        expected = patch.aggregate(dim=None, method="mean", dim_reduce="empty")
        assert out.dims == expected.dims
        assert out.shape == expected.shape
