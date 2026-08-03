"""End-to-end benchmarks for DAS processing workflows.

These benchmarks execute a realistic DASCore processing chain (detrend, filter,
taper, envelope aggregation) through the DerZug workflow engine. They capture
both the engine overhead and the cost of the patch operations a user chains
together on the canvas.
"""

from __future__ import annotations

import dascore as dc
import numpy as np
import pytest
from derzug.workflow import PipeBuilder
from derzug.workflow.task import task

# Patch sizes are kept modest so a full run stays in the millisecond range
# while remaining representative of interactive DAS workloads.
CHANNELS = 64
SAMPLES = 4_096
SPOOL_PATCHES = 4
SPOOL_CHANNELS = 32
SPOOL_SAMPLES = 2_048


def make_patch(
    channels: int = CHANNELS,
    samples: int = SAMPLES,
    *,
    seed: int = 42,
    start: str = "2023-01-01T00:00:00",
) -> dc.Patch:
    """Return a deterministic random patch with time and distance dims."""
    rng = np.random.default_rng(seed)
    data = rng.normal(size=(channels, samples)).astype("float32")
    time_start = np.datetime64(start)
    coords = {
        "distance": np.arange(channels) * 10.0,
        "time": time_start + np.arange(samples) * np.timedelta64(1_000, "us"),
    }
    return dc.Patch(data=data, coords=coords, dims=("distance", "time"))


@task
def detrend_patch(patch, dim: str = "time"):
    """Remove the linear trend along one dimension."""
    detrended = patch.detrend(dim)
    return detrended


@task
def filter_patch(patch, low: float = 2.0, high: float = 100.0):
    """Apply a band-pass filter along time."""
    filtered = patch.pass_filter(time=(low, high))
    return filtered


@task
def taper_patch(patch, fraction: float = 0.05):
    """Taper the edges of the patch along time."""
    tapered = patch.taper(time=fraction)
    return tapered


@task
def envelope_mean(patch, dim: str = "time"):
    """Aggregate the absolute amplitude of the patch along one dimension."""
    envelope = patch.abs().aggregate(dim, "mean")
    return envelope


def build_processing_pipe():
    """Return a validated detrend/filter/taper/aggregate workflow."""
    builder = PipeBuilder()
    detrend = builder.add(detrend_patch(), name="detrend")
    band_pass = builder.add(filter_patch(), name="filter")
    taper = builder.add(taper_patch(), name="taper")
    envelope = builder.add(envelope_mean(), name="envelope")
    builder.connect(detrend, band_pass)
    builder.connect(band_pass, taper)
    builder.connect(taper, envelope)
    return builder.build()


@pytest.fixture(scope="module")
def patch():
    """Return a reusable random patch."""
    return make_patch()


@pytest.fixture(scope="module")
def processing_pipe():
    """Return a reusable processing workflow."""
    return build_processing_pipe()


@pytest.fixture(scope="module")
def patch_spool():
    """Return a small in-memory spool of contiguous patches."""
    patches = []
    for index in range(SPOOL_PATCHES):
        patches.append(
            make_patch(
                SPOOL_CHANNELS,
                SPOOL_SAMPLES,
                seed=index,
                start=f"2023-01-01T00:00:0{index}",
            )
        )
    return dc.spool(patches)


def test_build_processing_pipe(benchmark):
    """Build and validate a workflow made of function-backed tasks."""
    pipe = benchmark(build_processing_pipe)
    assert len(pipe.tasks) == 4


def test_run_processing_pipe(benchmark, processing_pipe, patch):
    """Run the full processing chain on one patch."""
    results = benchmark(processing_pipe.run, patch, output_keys=["envelope"])
    assert results["envelope"].shape == (CHANNELS, 1)


def test_map_processing_pipe_over_spool(benchmark, processing_pipe, patch_spool):
    """Map the processing chain over every patch of a spool."""

    def run_map():
        """Consume the map generator over the spool."""
        return [
            result["envelope"]
            for result in processing_pipe.map(patch_spool, output_keys=["envelope"])
        ]

    assert len(benchmark(run_map)) == SPOOL_PATCHES


def test_run_single_task_pipe(benchmark, patch):
    """Measure engine overhead for a workflow with one cheap task."""
    builder = PipeBuilder()
    builder.add(envelope_mean(), name="envelope")
    pipe = builder.build()
    results = benchmark(pipe.run, patch, output_keys=["envelope"])
    assert results.ok
