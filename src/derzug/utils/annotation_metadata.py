"""Shared annotation metadata and label-slot helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from derzug.models.annotations import Annotation

LABEL_SLOTS = tuple(str(index) for index in range(1, 10))
DEFAULT_ANNOTATION_RGB = (40, 225, 255)
LABEL_SLOT_COLORS: dict[str, tuple[int, int, int]] = {
    "1": (0, 200, 255),
    "2": (255, 170, 0),
    "3": (80, 225, 120),
    "4": (255, 95, 95),
    "5": (190, 120, 255),
    "6": (255, 210, 70),
    "7": (0, 220, 185),
    "8": (255, 120, 210),
    "9": (175, 235, 255),
}


class AnnotationLabelConfig(Protocol):
    """Minimal config API for label-slot resolution helpers."""

    def label_name(self, slot: str) -> str:
        """Return the configured label for a numeric slot."""
        ...

    def slot_for_label(self, label: str | None) -> str | None:
        """Return the numeric slot backing a persisted annotation label."""
        ...


@dataclass(frozen=True)
class AnnotationTextFieldSpec:
    """One editable free-text annotation metadata field."""

    name: str
    label: str


ANNOTATION_TEXT_FIELD_SPECS = (
    AnnotationTextFieldSpec("notes", "Notes"),
    AnnotationTextFieldSpec("group", "Group"),
    AnnotationTextFieldSpec("label", "Label"),
)


def optional_text(value: object | None) -> str | None:
    """Normalize one optional free-text metadata value."""
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def annotation_label_from_slot(
    slot: str | None,
    config: AnnotationLabelConfig,
) -> str | None:
    """Resolve one numeric slot into the configured persisted annotation label."""
    if slot is None:
        return None
    return config.label_name(str(slot))


def annotation_label_slot(
    label: str | None,
    config: AnnotationLabelConfig,
) -> str | None:
    """Return the numeric slot backing one persisted annotation label."""
    return config.slot_for_label(label)


def annotation_label_color(
    label: str | None,
    config: AnnotationLabelConfig,
) -> tuple[int, int, int]:
    """Return the deterministic display color for one annotation label."""
    slot = annotation_label_slot(label, config)
    if slot is None:
        return DEFAULT_ANNOTATION_RGB
    return LABEL_SLOT_COLORS.get(slot, DEFAULT_ANNOTATION_RGB)


def annotation_metadata_row(annotation: Annotation) -> dict[str, object]:
    """Return shared metadata columns for tabular annotation displays."""
    return {
        "semantic_type": annotation.semantic_type,
        "notes": annotation.notes,
        "group": annotation.group,
        "label": annotation.label,
        "tags": ", ".join(annotation.tags),
    }
