"""Tests for shared bounded-decimation helpers."""

from __future__ import annotations

import numpy as np
from derzug.utils.sampling import strided_sample, strided_step


class TestStridedStep:
    """Tests for the 1D stride computation."""

    def test_small_inputs_keep_unit_stride(self):
        """Arrays within budget are never decimated."""
        assert strided_step(10, 100) == 1
        assert strided_step(100, 100) == 1
        assert strided_step(0, 100) == 1

    def test_stride_bounds_sample_count(self):
        """The computed stride keeps the sampled count within the budget."""
        for size in (101, 1_000, 999_999, 1_000_001, 2_000_002):
            step = strided_step(size, 1_000)
            assert int(np.ceil(size / step)) <= 1_000


class TestStridedSample:
    """Tests for the n-dimensional bounded sample."""

    def test_within_budget_returns_input(self):
        """Arrays at or below the budget pass through unchanged."""
        values = np.arange(10)

        assert strided_sample(values, 10) is values
        assert strided_sample(np.float64(3.0), 1).ndim == 0

    def test_1d_sample_is_bounded_and_regular(self):
        """1D output respects the budget with a regular stride."""
        values = np.arange(1_000)

        sampled = strided_sample(values, 100)

        assert sampled.size <= 100
        assert sampled[0] == values[0]
        assert np.all(np.diff(sampled) == sampled[1] - sampled[0])

    def test_2d_sample_is_bounded(self):
        """2D output stays within the element budget."""
        values = np.zeros((317, 511))

        assert strided_sample(values, 1_000).size <= 1_000

    def test_3d_sample_is_bounded(self):
        """Higher-rank arrays are also bounded, halving the largest axis."""
        values = np.zeros((37, 53, 71))

        assert strided_sample(values, 500).size <= 500

    def test_extreme_aspect_ratio_is_bounded(self):
        """A single long axis cannot overflow the budget."""
        values = np.zeros((2, 1_000_000))

        assert strided_sample(values, 1_000).size <= 1_000

    def test_sample_is_a_view_without_copying(self):
        """Decimation must stay a strided view of the source array."""
        values = np.broadcast_to(np.asarray(1.0), (10_000, 10_000))

        sampled = strided_sample(values, 4_000_000)

        assert sampled.size <= 4_000_000
        assert np.shares_memory(sampled, values)

    def test_short_axis_keeps_at_least_one_row(self):
        """A very short axis still contributes at least one sample row."""
        values = np.zeros((3, 200_000))

        sampled = strided_sample(values, 10_000)

        assert sampled.shape[0] >= 1
        assert sampled.size <= 10_000
