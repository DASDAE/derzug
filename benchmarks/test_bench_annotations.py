"""Benchmarks for annotation models and the annotation store helpers.

Annotation sets are validated, merged, serialized and summarized every time an
annotation widget emits or receives data, so these paths dominate the cost of
working with large annotation collections.
"""

from __future__ import annotations

import pytest
from conftest import ANNOTATION_COUNT, make_annotation, make_annotation_set
from derzug.models.annotations import AnnotationSet
from derzug.utils.annotations import (
    annotation_id_map,
    annotation_type_counts,
    build_state,
    deserialize_annotation_set,
    entries_from_state_items,
    make_entry,
    merge_annotation_sets,
    serialize_annotation_set,
    summarize_entries,
    upsert_annotation,
)

ENTRY_COUNT = 4


@pytest.fixture(scope="module")
def annotation_payload(annotation_set):
    """Return the JSON-safe mapping of one annotation set."""
    return annotation_set.model_dump(mode="json")


@pytest.fixture(scope="module")
def annotation_json(annotation_set):
    """Return the serialized JSON text of one annotation set."""
    return serialize_annotation_set(annotation_set)


@pytest.fixture(scope="module")
def store_entries(annotation_set):
    """Return a small annotation store holding several annotation sets."""
    entries: tuple = ()
    for _ in range(ENTRY_COUNT):
        entries = (*entries, make_entry(annotation_set, existing_entries=entries))
    return entries


def test_build_annotation_set(benchmark):
    """Validate a full annotation set built from python/numpy scalars."""
    annotations = benchmark(make_annotation_set)
    assert len(annotations.annotations) == ANNOTATION_COUNT


def test_validate_annotation_payload(benchmark, annotation_payload):
    """Validate an annotation set coming from serialized widget state."""
    annotations = benchmark(AnnotationSet.model_validate, annotation_payload)
    assert len(annotations.annotations) == ANNOTATION_COUNT


def test_serialize_annotation_set(benchmark, annotation_set):
    """Serialize an annotation set to JSON text."""
    assert benchmark(serialize_annotation_set, annotation_set)


def test_deserialize_annotation_set(benchmark, annotation_json):
    """Deserialize an annotation set from JSON text."""
    annotations = benchmark(deserialize_annotation_set, annotation_json)
    assert len(annotations.annotations) == ANNOTATION_COUNT


def test_annotation_id_map(benchmark, annotation_set):
    """Index annotations by id."""
    assert len(benchmark(annotation_id_map, annotation_set)) == ANNOTATION_COUNT


def test_annotation_type_counts(benchmark, annotation_set):
    """Count annotations per geometry type."""
    counts = benchmark(annotation_type_counts, annotation_set)
    assert sum(counts.values()) == ANNOTATION_COUNT


def test_upsert_annotation(benchmark, annotation_set):
    """Replace one annotation in a large set."""
    replacement = make_annotation(ANNOTATION_COUNT // 2)
    updated = benchmark(upsert_annotation, annotation_set, replacement)
    assert len(updated.annotations) == ANNOTATION_COUNT


def test_merge_annotation_sets(benchmark, annotation_set):
    """Merge two overlapping annotation sets."""
    incoming = make_annotation_set(ANNOTATION_COUNT // 2)
    merged = benchmark(merge_annotation_sets, annotation_set, incoming)
    assert len(merged.annotations) == ANNOTATION_COUNT


def test_summarize_entries(benchmark, store_entries):
    """Summarize every annotation store row for table display."""
    assert len(benchmark(summarize_entries, store_entries)) == ENTRY_COUNT


def test_build_store_state(benchmark, store_entries):
    """Serialize the annotation store into Orange widget state."""
    state = benchmark(
        build_state,
        store_entries,
        directory="",
        selected_id=store_entries[0].id,
    )
    assert len(state.entries) == ENTRY_COUNT


def test_restore_store_state(benchmark, store_entries):
    """Restore the annotation store from Orange widget state."""
    state = build_state(store_entries, directory="", selected_id=store_entries[0].id)
    items = list(state.entries)
    assert len(benchmark(entries_from_state_items, items)) == ENTRY_COUNT
