"""Benchmarks for the shared display, sampling and parsing utilities.

These helpers run once per rendered cell, tick label or slider move, and the
bounded-decimation helpers are applied to full patch arrays before plotting.
"""

from __future__ import annotations

import datetime

import numpy as np
import pytest
from derzug.utils.display import format_display, format_nd_coord_value
from derzug.utils.parsing import (
    parse_patch_text_value,
    parse_text_value,
    parse_timedelta_text,
)
from derzug.utils.sampling import strided_sample, strided_step

# A waterfall-sized array: the decimation helpers bound this to a plottable
# number of points before pyqtgraph ever sees the data.
WATERFALL_SHAPE = (512, 2_048)
TARGET_SIZE = 100_000

DISPLAY_VALUES = (
    None,
    1,
    -12345,
    3.14159265,
    1e-9,
    "station_01",
    np.float32(2.5),
    np.int64(7),
    np.datetime64("2023-01-01T00:00:00.123456"),
    np.timedelta64(1_500, "us"),
    datetime.timedelta(seconds=90),
    datetime.timedelta(microseconds=250),
)

TEXT_VALUES = (
    "10",
    "-3",
    "1.5",
    "1e-3",
    "1.25e3",
    "",
    "auto",
)

PATCH_TEXT_VALUES = (
    "10",
    "-3",
    "1.5",
    "1e-3",
    "",
    "10 m",
    "0.5 s",
    "20 Hz",
)

TIMEDELTA_TEXTS = (
    "250 milliseconds",
    "1500 microseconds",
    "3 seconds",
    "90 seconds",
    "2 hours",
)


@pytest.fixture(scope="module")
def waterfall_array():
    """Return a large 2D float array shaped like patch data."""
    rng = np.random.default_rng(11)
    return rng.normal(size=WATERFALL_SHAPE).astype("float32")


def test_strided_sample_2d(benchmark, waterfall_array):
    """Decimate a waterfall-sized array down to a plottable size."""
    sample = benchmark(strided_sample, waterfall_array, TARGET_SIZE)
    assert sample.size <= TARGET_SIZE


def test_strided_sample_1d(benchmark, waterfall_array):
    """Decimate a single long trace down to a plottable size."""
    trace = waterfall_array.ravel()
    sample = benchmark(strided_sample, trace, 10_000)
    assert sample.size <= 10_000


def test_strided_step(benchmark):
    """Compute strides for many candidate array sizes."""

    def compute_steps():
        """Return the stride for a range of array sizes."""
        return [strided_step(size, 5_000) for size in range(1, 20_000, 7)]

    assert benchmark(compute_steps)


def test_format_display(benchmark):
    """Format every supported scalar kind for table display."""

    def format_all():
        """Return display strings for all representative values."""
        return [format_display(value) for value in DISPLAY_VALUES * 32]

    assert benchmark(format_all)


def test_format_nd_coord_value(benchmark):
    """Format slider coordinate labels for every supported scalar kind."""

    def format_all():
        """Return compact labels for all representative values."""
        return [format_nd_coord_value(value) for value in DISPLAY_VALUES[1:] * 32]

    assert benchmark(format_all)


def test_parse_text_value(benchmark):
    """Parse textbox values into their narrowest python type."""

    def parse_all():
        """Return parsed values for all representative texts."""
        return [parse_text_value(text) for text in TEXT_VALUES * 32]

    assert benchmark(parse_all)


def test_parse_patch_text_value(benchmark):
    """Parse textbox values destined for DASCore patch methods."""

    def parse_all():
        """Return parsed patch arguments for all representative texts."""
        return [
            parse_patch_text_value(text, allow_none=True)
            for text in PATCH_TEXT_VALUES * 8
        ]

    assert benchmark(parse_all)


def test_parse_timedelta_text(benchmark):
    """Parse free-form timedelta text back into numpy timedeltas."""

    def parse_all():
        """Return parsed timedeltas for all representative texts."""
        return [parse_timedelta_text(text) for text in TIMEDELTA_TEXTS * 16]

    assert benchmark(parse_all)
