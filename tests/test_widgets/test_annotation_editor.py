"""Tests for the annotation metadata editor dialog."""

from __future__ import annotations

import pytest
from derzug.models.annotations import Annotation, PointGeometry
from derzug.widgets.annotation_editor import AnnotationEditorDialog


def _annotation() -> Annotation:
    """Return one representative annotation for dialog tests."""
    return Annotation(
        id="a1",
        semantic_type="arrival_pick",
        notes="picked",
        tags=("arrival", "manual"),
        group="event-1",
        label="p_pick",
        properties={"confidence": 0.9},
        geometry=PointGeometry(dims=("distance", "time"), values=(10.0, 2.0)),
    )


def test_dialog_populates_fields_from_annotation(qtbot):
    """Dialog controls should reflect the supplied annotation metadata."""
    dialog = AnnotationEditorDialog(_annotation())
    qtbot.addWidget(dialog)

    assert dialog._semantic_type.text() == "arrival_pick"
    assert dialog._notes.text() == "picked"
    assert dialog._tags.text() == "arrival, manual"
    assert dialog._group.text() == "event-1"
    assert dialog._label.text() == "p_pick"
    assert '"confidence": 0.9' in dialog._properties.text()


def test_values_normalize_blank_fields(qtbot):
    """Blank semantic/notes/group/label/properties fields normalize cleanly."""
    dialog = AnnotationEditorDialog(_annotation())
    qtbot.addWidget(dialog)
    dialog._semantic_type.setText("   ")
    dialog._notes.setText("   ")
    dialog._tags.setText(" arrival , manual ,, ")
    dialog._group.setText("")
    dialog._label.setText("")
    dialog._properties.setText("")

    values = dialog.values()

    assert values["semantic_type"] == "generic"
    assert values["notes"] is None
    assert values["tags"] == ("arrival", "manual")
    assert values["group"] is None
    assert values["label"] is None
    assert values["properties"] == {}


def test_values_require_properties_json_object(qtbot):
    """Properties must decode into a JSON object rather than a scalar or list."""
    dialog = AnnotationEditorDialog(_annotation())
    qtbot.addWidget(dialog)
    dialog._properties.setText("[1, 2, 3]")

    with pytest.raises(ValueError, match="JSON object"):
        dialog.values()
