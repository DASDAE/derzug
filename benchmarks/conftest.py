"""Shared fixtures for the DerZug benchmark suites.

This module must stay import-light: it is loaded for both the Qt-free
``core`` tree and the Qt ``qt`` tree, so it may not import derzug, dascore,
or any Qt binding at module level.
"""

from __future__ import annotations

import numpy as np
import pytest

# Fixed seed: benchmark inputs must be byte-identical between runs, otherwise
# timings and instruction counts drift for reasons unrelated to the code.
BENCH_SEED = 20260803


@pytest.fixture(scope="session")
def rng() -> np.random.Generator:
    """Return the seeded generator used to build every benchmark input."""
    return np.random.default_rng(BENCH_SEED)
