"""State-level tests for the shared selection helpers."""

from __future__ import annotations

import dascore as dc
import numpy as np
from derzug.widgets.selection import (
    PatchSelectionBasis,
    SelectionMode,
    SelectionState,
)


class TestSelectionState:
    """Tests for the typed selection state."""

    def test_patch_source_initializes_full_extent_ranges(self):
        """Setting a patch source seeds all dims from the full extents."""
        state = SelectionState()
        patch = dc.get_example_patch("example_event_2")

        state.set_patch_source(patch)

        assert state.mode is SelectionMode.PATCH
        assert state.patch.basis is PatchSelectionBasis.ABSOLUTE
        assert tuple(state.patch.extents) == tuple(patch.dims)
        assert state.patch.ranges == state.patch.extents
        assert state.patch_kwargs() == {}

    def test_patch_kwargs_only_include_narrowed_dims(self):
        """Only dims narrowed away from the full extent appear in patch kwargs."""
        state = SelectionState()
        patch = dc.get_example_patch("example_event_2")
        state.set_patch_source(patch)
        dim = patch.dims[1]
        extent = state.patch_extent(dim)
        midpoint = patch.get_array(dim)[len(patch.get_array(dim)) // 2]

        state.update_patch_range(dim, extent[0], midpoint)

        assert set(state.patch_kwargs()) == {dim}

    def test_spool_source_initializes_filter_options(self):
        """Setting a spool source extracts visible metadata options."""
        state = SelectionState()
        spool = dc.get_example_spool()

        state.set_spool_source(spool)

        assert state.mode is SelectionMode.SPOOL
        assert state.spool.options
        assert state.spool.key == ""
        assert state.spool.raw_value == ""

    def test_reset_clears_spool_filter(self):
        """Reset removes any active spool filter."""
        state = SelectionState()
        spool = dc.get_example_spool()
        state.set_spool_source(spool)
        first_option = state.spool.options[0]
        state.set_spool_filter(first_option, "1")

        state.reset()

        assert state.spool.key == ""
        assert state.spool.raw_value == ""

    def test_relative_patch_selection_matches_relative_select(self):
        """Relative basis applies offsets through patch.select(relative=True)."""
        state = SelectionState()
        patch = dc.get_example_patch("example_event_2").update_coords(
            time=dc.get_example_patch("example_event_2").get_array("time") + 10
        )
        state.set_patch_source(patch)
        state.set_patch_basis(PatchSelectionBasis.RELATIVE)

        state.update_patch_range("time", 0.0, 0.01)

        selected = state.apply_to_patch(patch)
        expected = patch.select(copy=False, relative=True, time=(0.0, 0.01))
        assert selected.shape == expected.shape
        assert state.patch_select_flags() == {"relative": True, "samples": False}

    def test_samples_patch_selection_matches_samples_select(self):
        """Sample basis applies sample indices through patch.select(samples=True)."""
        state = SelectionState()
        patch = dc.get_example_patch("example_event_2")
        state.set_patch_source(patch)
        state.set_patch_basis(PatchSelectionBasis.SAMPLES)

        state.update_patch_range("time", 10, 20)

        selected = state.apply_to_patch(patch)
        expected = patch.select(copy=False, samples=True, time=(10, 20))
        assert selected.shape == expected.shape
        assert state.patch_select_flags() == {"relative": False, "samples": True}

    def test_reset_preserves_patch_basis(self):
        """Reset clears ranges but leaves the chosen patch basis intact."""
        state = SelectionState()
        patch = dc.get_example_patch("example_event_2")
        state.set_patch_source(patch)
        state.set_patch_basis(PatchSelectionBasis.SAMPLES)
        state.update_patch_range("time", 10, 20)

        state.reset()

        assert state.patch.basis is PatchSelectionBasis.SAMPLES
        assert state.patch.ranges == state.patch.extents

    def test_patch_source_reseed_preserves_relative_ranges(self):
        """Relative ranges should persist when a new patch replaces the source."""
        state = SelectionState()
        patch = dc.get_example_patch("example_event_2")
        shifted = patch.update_coords(
            time=patch.get_array("time") + 10,
            distance=patch.get_array("distance") + 100,
        )
        state.set_patch_source(patch)
        state.set_patch_basis(PatchSelectionBasis.RELATIVE)
        state.update_patch_range("time", 0.0, 0.01)

        state.set_patch_source(shifted)

        assert state.patch.basis is PatchSelectionBasis.RELATIVE
        assert state.current_patch_range("time") == (0.0, 0.01)
        selected = state.apply_to_patch(shifted)
        expected = shifted.select(copy=False, relative=True, time=(0.0, 0.01))
        assert selected.shape == expected.shape

    def test_patch_source_reseed_resets_inactive_basis_and_ranges(self):
        """Replacement patches reset to blank absolute state without a selection."""
        state = SelectionState()
        patch = dc.get_example_patch("example_event_2")

        state.set_patch_source(patch)
        state.set_patch_basis(PatchSelectionBasis.SAMPLES)

        state.set_patch_source(
            patch.update_coords(distance=patch.get_array("distance") + 1)
        )

        assert state.patch.basis is PatchSelectionBasis.ABSOLUTE
        assert state.patch.ranges == state.patch.extents

    def test_patch_source_reseed_resets_incompatible_absolute_ranges(self):
        """Absolute ranges reset when the replacement patch uses a new coord type."""
        state = SelectionState()
        datetime_patch = dc.get_example_patch()
        float_patch = dc.get_example_patch("example_event_2")

        state.set_patch_source(datetime_patch)
        state.update_patch_range(
            "time",
            datetime_patch.get_array("time")[0],
            datetime_patch.get_array("time")[5],
        )

        state.set_patch_source(float_patch)

        time_range = state.current_patch_range("time")
        assert state.patch.basis is PatchSelectionBasis.ABSOLUTE
        assert time_range == state.patch_extent("time")
        assert all(
            np.issubdtype(np.asarray(value).dtype, np.number) for value in time_range
        )
        selected = state.apply_to_patch(float_patch)
        assert selected.shape == float_patch.shape
