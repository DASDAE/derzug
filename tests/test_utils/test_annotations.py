"""Tests for annotation store utilities."""

from __future__ import annotations

from pathlib import Path

from derzug.models.annotations import Annotation, AnnotationSet, PointGeometry
from derzug.utils.annotations import (
    build_state,
    delete_entry,
    entry_to_state,
    format_file_size,
    import_annotation_set,
    load_store,
    make_entry,
    merge_annotation_sets,
    normalize_selected_id,
    persist_entries_with_metadata,
    selected_annotation_set,
    summarize_entries,
)


def _set(ids: tuple[str, ...], dims=("time",)) -> AnnotationSet:
    return AnnotationSet(
        dims=dims,
        annotations=tuple(
            Annotation(
                id=annotation_id,
                geometry=PointGeometry(dims=dims, values=tuple(float(i + 1) for i in range(len(dims)))),
            )
            for annotation_id in ids
        ),
    )


def test_merge_annotation_sets_replaces_colliding_ids():
    current = _set(("a", "b"))
    incoming = AnnotationSet(
        dims=("time",),
        annotations=(
            Annotation(id="b", geometry=PointGeometry(dims=("time",), values=(9.0,))),
            Annotation(id="c", geometry=PointGeometry(dims=("time",), values=(3.0,))),
        ),
    )
    merged = merge_annotation_sets(current, incoming)
    assert [item.id for item in merged.annotations] == ["a", "b", "c"]
    assert merged.annotations[1].geometry.values == (9.0,)


def test_import_annotation_set_appends_to_selected_matching_dims():
    entry = make_entry(_set(("a",)), name="Annotations 1")
    result = import_annotation_set((entry,), _set(("b",)), selected_id=entry.id)
    assert result.selected_id == entry.id
    assert len(result.entries) == 1
    assert [item.id for item in result.entries[0].annotation_set.annotations] == ["a", "b"]


def test_import_annotation_set_creates_new_row_for_dim_mismatch():
    entry = make_entry(_set(("a",), dims=("time",)), name="Annotations 1")
    result = import_annotation_set(
        (entry,),
        _set(("b",), dims=("distance",)),
        selected_id=entry.id,
    )
    assert len(result.entries) == 2
    assert result.selected_id == result.entries[-1].id


def test_import_annotation_set_creates_new_row_when_none_selected():
    result = import_annotation_set((), _set(("a",)), selected_id=None)
    assert len(result.entries) == 1
    assert result.selected_id == result.entries[0].id


def test_summarize_entries_reports_type_counts():
    entry = make_entry(_set(("a", "b")))
    summary = summarize_entries((entry,))[0]
    assert summary.annotation_count == 2
    assert summary.point_count == 2
    assert summary.span_count == 0


def test_format_file_size_is_human_readable():
    assert format_file_size(10) == "10 B"
    assert format_file_size(2048) == "2.0 KiB"


def test_persist_and_load_entries_round_trip(tmp_path):
    entry = make_entry(_set(("a",)), name="Custom Name")
    persisted = persist_entries_with_metadata((entry,), tmp_path)
    loaded = load_store(directory=str(tmp_path), state_entries=[])
    assert persisted[0].file_path is not None
    assert len(loaded) == 1
    assert loaded[0].name == "Custom Name"
    assert loaded[0].annotation_set == entry.annotation_set


def test_delete_entry_updates_selected():
    first = make_entry(_set(("a",)), name="One")
    second = make_entry(_set(("b",)), name="Two")
    entries, selected = delete_entry((first, second), first.id, selected_id=first.id)
    assert entries == (second,)
    assert selected == second.id


def test_build_state_serializes_entries():
    entry = make_entry(_set(("a",)), name="One")
    state = build_state((entry,), directory="", selected_id=entry.id)
    assert state.selected_id == entry.id
    assert state.entries[0]["name"] == "One"


def test_normalize_selected_id_picks_first_available():
    first = make_entry(_set(("a",)), name="One")
    second = make_entry(_set(("b",)), name="Two")
    assert normalize_selected_id((first, second), "missing") == first.id


def test_selected_annotation_set_returns_matching_payload():
    entry = make_entry(_set(("a",)), name="One")
    assert selected_annotation_set((entry,), entry.id) == entry.annotation_set

