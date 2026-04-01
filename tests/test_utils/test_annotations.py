"""Tests for annotation store utilities."""

from __future__ import annotations

import json

from derzug.models.annotations import Annotation, AnnotationSet, PointGeometry
from derzug.utils.annotations import (
    build_state,
    delete_entry,
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
                geometry=PointGeometry(
                    coords={dim: float(i + 1) for i, dim in enumerate(dims)}
                ),
            )
            for annotation_id in ids
        ),
    )


def test_merge_annotation_sets_replaces_colliding_ids():
    """Merging replaces existing annotations whose IDs collide."""
    current = _set(("a", "b"))
    incoming = AnnotationSet(
        dims=("time",),
        annotations=(
            Annotation(id="b", geometry=PointGeometry(coords={"time": 9.0})),
            Annotation(id="c", geometry=PointGeometry(coords={"time": 3.0})),
        ),
    )
    merged = merge_annotation_sets(current, incoming)
    assert [item.id for item in merged.annotations] == ["a", "b", "c"]
    assert merged.annotations[1].geometry.coords == {"time": 9.0}


def test_import_annotation_set_appends_to_selected_matching_dims():
    """Importing into a selected entry with matching dims appends annotations."""
    entry = make_entry(_set(("a",)), name="Annotations 1")
    result = import_annotation_set((entry,), _set(("b",)), selected_id=entry.id)
    assert result.selected_id == entry.id
    assert len(result.entries) == 1
    assert [item.id for item in result.entries[0].annotation_set.annotations] == [
        "a",
        "b",
    ]


def test_import_annotation_set_creates_new_row_for_dim_mismatch():
    """Importing with mismatched dims creates a new entry instead of merging."""
    entry = make_entry(_set(("a",), dims=("time",)), name="Annotations 1")
    result = import_annotation_set(
        (entry,),
        _set(("b",), dims=("distance",)),
        selected_id=entry.id,
    )
    assert len(result.entries) == 2
    assert result.selected_id == result.entries[-1].id


def test_import_annotation_set_creates_new_row_when_none_selected():
    """Importing with no selection creates the first entry and selects it."""
    result = import_annotation_set((), _set(("a",)), selected_id=None)
    assert len(result.entries) == 1
    assert result.selected_id == result.entries[0].id


def test_summarize_entries_reports_type_counts():
    """Summarize correctly counts geometry types within each entry."""
    entry = make_entry(_set(("a", "b")))
    summary = summarize_entries((entry,))[0]
    assert summary.annotation_count == 2
    assert summary.point_count == 2
    assert summary.span_count == 0


def test_format_file_size_is_human_readable():
    """format_file_size returns a human-readable byte string."""
    assert format_file_size(10) == "10 B"
    assert format_file_size(2048) == "2.0 KiB"


def test_persist_and_load_entries_round_trip(tmp_path):
    """Persisted entries can be reloaded with the same name and annotation set."""
    entry = make_entry(_set(("a",)), name="Custom Name")
    persisted = persist_entries_with_metadata((entry,), tmp_path)
    loaded = load_store(directory=str(tmp_path), state_entries=[])
    assert persisted[0].file_path is not None
    assert len(loaded) == 1
    assert loaded[0].name == "Custom Name"
    assert loaded[0].annotation_set == entry.annotation_set


def test_load_store_skips_old_schema_entries(tmp_path):
    """Stored entries with old schema versions should be ignored."""
    payload = {
        "name": "Legacy",
        "annotation_set": {
            "schema_version": "2",
            "dims": ["time"],
            "annotations": [],
        },
    }
    (tmp_path / "legacy.json").write_text(json.dumps(payload), encoding="utf-8")

    loaded = load_store(directory=str(tmp_path), state_entries=[])

    assert loaded == ()


def test_delete_entry_updates_selected():
    """Deleting the selected entry moves selection to the next available entry."""
    first = make_entry(_set(("a",)), name="One")
    second = make_entry(_set(("b",)), name="Two")
    entries, selected = delete_entry((first, second), first.id, selected_id=first.id)
    assert entries == (second,)
    assert selected == second.id


def test_build_state_serializes_entries():
    """build_state serializes entries and selection into a dict-compatible payload."""
    entry = make_entry(_set(("a",)), name="One")
    state = build_state((entry,), directory="", selected_id=entry.id)
    assert state.selected_id == entry.id
    assert state.entries[0]["name"] == "One"


def test_normalize_selected_id_picks_first_available():
    """A missing selected ID falls back to the first available entry."""
    first = make_entry(_set(("a",)), name="One")
    second = make_entry(_set(("b",)), name="Two")
    assert normalize_selected_id((first, second), "missing") == first.id


def test_selected_annotation_set_returns_matching_payload():
    """selected_annotation_set returns the annotation set for the given entry ID."""
    entry = make_entry(_set(("a",)), name="One")
    assert selected_annotation_set((entry,), entry.id) == entry.annotation_set
