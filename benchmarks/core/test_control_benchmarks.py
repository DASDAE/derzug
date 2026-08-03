"""A control benchmark whose runtime must never change.

``scripts/bench_compare.py`` treats this benchmark specially: if it moves
between the baseline and head runs, the machine drifted (thermal throttling,
background load, a different interpreter) and every other verdict in that
comparison is downgraded to a warning.
"""

from __future__ import annotations

import pytest


class TestControlBenchmarks:
    """Fixed-work controls used to detect measurement drift."""

    @pytest.mark.benchmark
    def test_fixed_python_work(self):
        """Sum squares in pure Python, touching no DerZug or NumPy code."""
        total = 0
        for index in range(200_000):
            total += index * index
        assert total > 0
