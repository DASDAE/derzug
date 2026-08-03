"""Benchmarks for the bounded-decimation helpers used by large-array display."""

from __future__ import annotations

import numpy as np
import pytest
from derzug.utils.sampling import strided_sample, strided_step


@pytest.fixture(scope="module")
def big_array(rng) -> np.ndarray:
    """Return a 2-million element float64 array."""
    return rng.random((1000, 2000))


class TestSamplingBenchmarks:
    """Benchmarks for :mod:`derzug.utils.sampling`."""

    @pytest.mark.benchmark
    def test_strided_sample(self, big_array):
        """Take a bounded strided view of a large array."""
        for _ in range(100):
            strided_sample(big_array, 1_000_000)

    @pytest.mark.benchmark
    def test_strided_step(self):
        """Compute strides across a range of source sizes."""
        for size in range(1, 10_000):
            strided_step(size * 1000, 1_000_000)

    @pytest.mark.benchmark
    def test_percentile_levels_subsampled(self, big_array):
        """Compute display levels from a strided sample.

        The fast path: this is what the waterfall actually does, and it must
        stay far cheaper than :meth:`test_percentile_levels_full`.
        """
        np.nanpercentile(strided_sample(big_array, 100_000), [1, 99])

    @pytest.mark.benchmark
    def test_percentile_levels_full(self, big_array):
        """Compute display levels from the full array.

        The slow path kept as a reference point; the ratio between the two is
        the property worth guarding.
        """
        np.nanpercentile(big_array, [1, 99])
