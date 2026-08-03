"""Benchmarks for workflow graph construction, validation, and serialization."""

from __future__ import annotations

import pytest
from _bench_tasks import build_chain
from derzug.workflow.graph import PipeGraph, topological_sort


@pytest.fixture(scope="module")
def validated_chain(chain_pipe):
    """Return a chain pipe whose validation cache is already warm."""
    chain_pipe.ensure_validated()
    return chain_pipe


@pytest.fixture(scope="module")
def chain_payload(chain_pipe):
    """Return the serialized payload of the chain pipe."""
    return chain_pipe._to_dict()


class TestGraphBenchmarks:
    """Benchmarks for the Qt-free workflow graph layer."""

    @pytest.mark.benchmark
    def test_build_chain_pipe(self):
        """Build a 50-node linear pipe from scratch."""
        build_chain(50)

    @pytest.mark.benchmark
    def test_topological_sort(self, chain_pipe):
        """Sort a 50-node linear graph."""
        for _ in range(20):
            topological_sort(chain_pipe.tasks, chain_pipe.edges)

    @pytest.mark.benchmark
    def test_validate_uncached(self, chain_pipe):
        """Fully validate a 50-node graph.

        This is the slow path: ``validate`` always re-imports every task code
        path and re-checks every edge.
        """
        chain_pipe.validate()

    @pytest.mark.benchmark
    def test_ensure_validated_cached(self, validated_chain):
        """Re-enter validation on an already-validated graph.

        This is the fast path guarding the ``_validated_object_id``
        short-circuit; it must stay orders of magnitude cheaper than
        :meth:`test_validate_uncached`.
        """
        for _ in range(1000):
            validated_chain.ensure_validated()

    @pytest.mark.benchmark
    def test_serialize_to_dict(self, chain_pipe):
        """Serialize a 50-node graph to its portable dict form."""
        chain_pipe._to_dict()

    @pytest.mark.benchmark
    def test_deserialize_from_dict(self, chain_payload):
        """Rebuild a 50-node graph from its portable dict form."""
        PipeGraph._from_dict(chain_payload)
