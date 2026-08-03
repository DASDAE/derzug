"""Benchmarks for streaming workflow execution."""

from __future__ import annotations

import pytest
from derzug.workflow.executor import build_task_runtime_specs


@pytest.fixture(scope="module")
def warm_chain(chain_pipe):
    """Return a chain pipe that has already executed once.

    The first run pays for validation and pydantic model warm-up, neither of
    which belongs in the measured region.
    """
    chain_pipe.run(1)
    return chain_pipe


@pytest.fixture(scope="module")
def warm_diamond(diamond_pipe):
    """Return a diamond pipe that has already executed once."""
    diamond_pipe.run(1)
    return diamond_pipe


@pytest.fixture(scope="module")
def stream_items():
    """Return the input list consumed by the streaming pipe."""
    return list(range(200))


class TestExecutionBenchmarks:
    """Benchmarks for the executor and its per-run setup."""

    @pytest.mark.benchmark
    def test_build_runtime_specs(self, chain_pipe):
        """Precompute per-task runtime specs for a 50-node pipe."""
        for _ in range(5):
            build_task_runtime_specs(chain_pipe)

    @pytest.mark.benchmark
    def test_run_chain(self, warm_chain):
        """Execute a 50-node linear pipe once.

        Runtime specs are rebuilt per call here, so this is the slow-path
        counterpart to :meth:`test_map_chain`.
        """
        warm_chain.run(1)

    @pytest.mark.benchmark
    def test_map_chain(self, warm_chain):
        """Map a 50-node linear pipe over ten inputs.

        ``map`` hoists runtime-spec construction out of the per-item loop; if
        that hoisting regresses, this moves while :meth:`test_run_chain` does
        not.
        """
        list(warm_chain.map(range(10)))

    @pytest.mark.benchmark
    def test_run_diamond(self, warm_diamond):
        """Execute a fan-out/fan-in pipe once."""
        warm_diamond.run(1)

    @pytest.mark.benchmark
    def test_stream_pipeline(self, stream_pipe, stream_items):
        """Execute a generator producer feeding a generator consumer."""
        stream_pipe.run(stream_items, output_keys=["collect"])

    @pytest.mark.benchmark
    def test_get_provenance(self, warm_chain):
        """Build a provenance record, guarding the runtime-environment cache."""
        for _ in range(20):
            warm_chain.get_provenance()
