"""Benchmarks for the cursor-readout helpers on the mouse-move hot path."""

from __future__ import annotations

import numpy as np
import pytest

pytest.importorskip("AnyQt.QtWidgets", reason="Qt is not installed")
pytest.importorskip("pyqtgraph", reason="pyqtgraph is not installed")

from derzug.utils.plot_axes import (  # noqa: E402
    nearest_axis_index,
    nearest_value_index,
)

_AXIS_SIZE = 20_000
_PROBES = np.linspace(1.0, 999.0, 50)


@pytest.fixture(scope="module")
def ascending_axis() -> np.ndarray:
    """Return a monotonically increasing axis."""
    return np.linspace(0.0, 1000.0, _AXIS_SIZE)


@pytest.fixture(scope="module")
def descending_axis(ascending_axis) -> np.ndarray:
    """Return a monotonically decreasing axis.

    Reversed axes take an extra copy inside ``nearest_axis_index``, so this is
    the slower of the two monotonic branches.
    """
    return ascending_axis[::-1].copy()


@pytest.fixture(scope="module")
def unsorted_values(rng) -> np.ndarray:
    """Return an unsorted value array with no monotonicity to exploit."""
    return rng.random(_AXIS_SIZE) * 1000.0


class TestPlotAxesBenchmarks:
    """Benchmarks for :mod:`derzug.utils.plot_axes` cursor mapping."""

    @pytest.mark.benchmark
    def test_nearest_axis_ascending(self, ascending_axis):
        """Locate cursor positions on an ascending axis."""
        for _ in range(20):
            for probe in _PROBES:
                nearest_axis_index(probe, ascending_axis)

    @pytest.mark.benchmark
    def test_nearest_axis_descending(self, descending_axis):
        """Locate cursor positions on a descending axis."""
        for _ in range(20):
            for probe in _PROBES:
                nearest_axis_index(probe, descending_axis)

    @pytest.mark.benchmark
    def test_nearest_value_unsorted(self, unsorted_values):
        """Locate the nearest value with no ordering assumption."""
        for probe in _PROBES:
            nearest_value_index(probe, unsorted_values)
