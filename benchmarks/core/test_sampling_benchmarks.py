"""Benchmarks for the bounded-decimation helpers used by large-array display."""

from __future__ import annotations

import numpy as np
import pytest
from derzug.utils.sampling import strided_sample


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
    def test_percentile_levels_subsampled(self, big_array):
        """Compute display levels from a strided sample.

        This is the path the waterfall actually takes; the equivalent call on
        the full array costs roughly twenty times as much.
        """
        np.nanpercentile(strided_sample(big_array, 100_000), [1, 99])
