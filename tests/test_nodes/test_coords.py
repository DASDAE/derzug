"""Tests for the Qt-free Coords node."""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.nodes.coords import (
    CoordsParams,
    CoordsValidationError,
    coords_task_from_params,
)


@pytest.fixture
def patch() -> dc.Patch:
    """Return a small example patch."""
    return dc.get_example_patch("random_das")


class TestSetCoordsDraftPromotion:
    """Headless draft fields must run like the widget's applied promotion."""

    def test_draft_fields_alone_apply(self, patch):
        """A headless author filling only the draft fields gets a real update."""
        params = CoordsParams(
            operation="set_coords", set_coords_dim="distance", set_coords_start="10"
        )

        out = coords_task_from_params(params).run(patch)

        assert float(out.get_array("distance")[0]) == pytest.approx(10.0)

    def test_drafts_win_over_applied_fields(self, patch):
        """Drafts beat the applied mirror, as canvas rehydration would."""
        params = CoordsParams(
            operation="set_coords",
            set_coords_dim="distance",
            set_coords_start="99",
            set_coords_applied_dim="distance",
            set_coords_applied_start="10",
        )

        out = coords_task_from_params(params).run(patch)

        assert float(out.get_array("distance")[0]) == pytest.approx(99.0)

    def test_applied_fields_used_when_no_draft(self, patch):
        """Hand-authored applied fields still run when drafts are empty."""
        params = CoordsParams(
            operation="set_coords",
            set_coords_applied_dim="distance",
            set_coords_applied_start="10",
        )

        out = coords_task_from_params(params).run(patch)

        assert float(out.get_array("distance")[0]) == pytest.approx(10.0)

    def test_empty_draft_values_stay_a_noop(self, patch):
        """A draft dim with no start/stop/step still passes through."""
        params = CoordsParams(operation="set_coords", set_coords_dim="distance")

        out = coords_task_from_params(params).run(patch)

        assert np.array_equal(out.get_array("distance"), patch.get_array("distance"))


class TestPreflight:
    """preflight must raise the same structured errors run would."""

    def test_valid_params_pass(self, patch):
        """A valid rename preflights without raising."""
        params = CoordsParams(
            operation="rename_coords", rename_rows=[["distance", "offset"]]
        )
        coords_task_from_params(params).preflight(patch)

    def test_invalid_mapping_raises_structured_error(self, patch):
        """A rename from a missing coord raises with banner routing info."""
        params = CoordsParams(
            operation="rename_coords", rename_rows=[["missing", "offset"]]
        )
        task = coords_task_from_params(params)

        with pytest.raises(CoordsValidationError) as info:
            task.preflight(patch)

        assert info.value.kind == "mapping"
        assert info.value.label == "rename"
        assert "'missing' is not available" in info.value.detail

    def test_invalid_transpose_raises_structured_error(self, patch):
        """A transpose order not matching the patch raises a selection error."""
        params = CoordsParams(operation="transpose", transpose_order=["time"])
        task = coords_task_from_params(params)

        with pytest.raises(CoordsValidationError) as info:
            task.preflight(patch)

        assert info.value.kind == "selection"
        assert info.value.label == "transpose"

    def test_data_flip_of_non_dim_coord_raises_structured_error(self, patch):
        """Data-flipping a non-dimension coordinate is rejected in preflight."""
        with_coord = patch.update_coords(
            quality=("distance", np.arange(patch.shape[patch.dims.index("distance")]))
        )
        params = CoordsParams(
            operation="flip", flip_dims_selected=["quality"], flip_coords=False
        )
        task = coords_task_from_params(params)

        with pytest.raises(CoordsValidationError) as info:
            task.preflight(with_coord)

        assert info.value.kind == "selection"
        assert "data flip requires dimension coordinates" in info.value.detail
