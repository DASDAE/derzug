"""Benchmarks for the task identity, port-spec, and synthesis layer."""

from __future__ import annotations

import pytest
from _bench_tasks import AddOne, plain_add_two
from derzug.workflow.task import (
    _build_task_port_spec,
    _create_function_task_class,
    _extract_return_names,
    _get_callable_source_hash,
)


class _ColdSpec(AddOne):
    """Throwaway subclass used to defeat the per-class port-spec cache."""


class TestTaskBenchmarks:
    """Benchmarks for :class:`derzug.workflow.Task` class-level machinery."""

    @pytest.mark.benchmark
    def test_port_spec_cold(self):
        """Rebuild a task port spec from type hints.

        Calls the builder directly to bypass the ``cls.__dict__`` cache, so
        this always measures the full introspection cost.
        """
        for _ in range(20):
            _build_task_port_spec(_ColdSpec)

    @pytest.mark.benchmark
    def test_port_spec_cached(self):
        """Read an already-cached port spec.

        The fast-path counterpart to :meth:`test_port_spec_cold`; it guards
        the per-class memo against accidental invalidation.
        """
        AddOne.port_spec()
        for _ in range(5000):
            AddOne.port_spec()

    @pytest.mark.benchmark
    def test_task_fingerprint(self):
        """Fingerprint 100 freshly built task instances.

        Instance construction is inside the timed region on purpose:
        ``fingerprint`` is a ``cached_property``, so reusing one instance
        would measure an attribute read rather than the hash.
        """
        for _ in range(100):
            AddOne().fingerprint

    @pytest.mark.benchmark
    def test_function_task_class_creation(self):
        """Synthesize a Task subclass from a plain function."""
        _create_function_task_class(plain_add_two, "1.0")

    @pytest.mark.benchmark
    def test_extract_return_names(self):
        """Parse a function body to recover its return names."""
        for _ in range(20):
            _extract_return_names(plain_add_two)

    @pytest.mark.benchmark
    def test_callable_source_hash(self):
        """Hash a task class's source for its fingerprint."""
        for _ in range(20):
            _get_callable_source_hash(AddOne)
