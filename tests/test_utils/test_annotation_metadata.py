"""Tests for shared annotation metadata helpers."""

from __future__ import annotations

from derzug.annotations_config import AnnotationConfig
from derzug.models.annotations import Annotation, PointGeometry
from derzug.utils.annotation_metadata import (
    ANNOTATION_TEXT_FIELD_SPECS,
    LABEL_SLOTS,
    annotation_label_color,
    annotation_label_from_slot,
    annotation_metadata_row,
    optional_text,
)


def _annotation() -> Annotation:
    """Return one representative annotation for metadata helper tests."""
    return Annotation(
        id="a1",
        semantic_type="arrival_pick",
        notes="picked",
        group="event-1",
        label="p_pick",
        tags=("arrival", "manual"),
        geometry=PointGeometry(coords={"distance": 10.0, "time": 2.0}),
    )


def test_annotation_text_field_specs_cover_shared_text_metadata():
    """Shared text-field specs should stay aligned with editable text metadata."""
    assert tuple(spec.name for spec in ANNOTATION_TEXT_FIELD_SPECS) == (
        "notes",
        "group",
        "label",
    )


def test_optional_text_normalizes_blank_values():
    """Optional text helper should trim strings and collapse blanks to None."""
    assert optional_text("  hello ") == "hello"
    assert optional_text("   ") is None
    assert optional_text(None) is None


def test_annotation_slot_label_helpers_use_global_slot_mapping():
    """Slot-driven label helpers should resolve configured label values and colors."""
    config = AnnotationConfig(label_names={"3": "p_pick"})

    assert LABEL_SLOTS == tuple(str(index) for index in range(1, 10))
    assert annotation_label_from_slot("3", config) == "p_pick"
    assert annotation_label_color("p_pick", config) == (80, 225, 120)


def test_annotation_metadata_row_exports_shared_metadata_columns():
    """Shared annotation metadata rows should expose the common tabular fields."""
    row = annotation_metadata_row(_annotation())

    assert row == {
        "semantic_type": "arrival_pick",
        "notes": "picked",
        "group": "event-1",
        "label": "p_pick",
        "tags": "arrival, manual",
    }
