"""Small modal editor for persisted annotation metadata."""

from __future__ import annotations

import json
from typing import Any

from AnyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from derzug.models.annotations import Annotation
from derzug.utils.annotation_metadata import (
    ANNOTATION_TEXT_FIELD_SPECS,
    optional_text,
)


class AnnotationEditorDialog(QDialog):
    """Small modal editor for one annotation's metadata."""

    def __init__(self, annotation: Annotation, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Edit Annotation")
        self.setModal(True)
        self.resize(320, 220)

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._semantic_type = QLineEdit(annotation.semantic_type, self)
        self._tags = QLineEdit(", ".join(annotation.tags), self)
        self._text_inputs: dict[str, QLineEdit] = {}
        self._properties = QLineEdit(
            json.dumps(annotation.properties, sort_keys=True),
            self,
        )

        form.addRow("Type", self._semantic_type)
        form.addRow("Tags", self._tags)
        for spec in ANNOTATION_TEXT_FIELD_SPECS:
            line_edit = QLineEdit(getattr(annotation, spec.name) or "", self)
            self._text_inputs[spec.name] = line_edit
            setattr(self, f"_{spec.name}", line_edit)
            form.addRow(spec.label, line_edit)
        form.addRow("Properties", self._properties)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def values(self) -> dict[str, Any]:
        """Return validated dialog values."""
        raw_tags = self._tags.text().strip()
        raw_properties = self._properties.text().strip()
        if raw_properties:
            properties = json.loads(raw_properties)
            if not isinstance(properties, dict):
                raise ValueError("properties must decode to a JSON object")
        else:
            properties = {}
        return {
            "semantic_type": self._semantic_type.text().strip() or "generic",
            "tags": tuple(tag.strip() for tag in raw_tags.split(",") if tag.strip()),
            **{
                name: optional_text(line_edit.text())
                for name, line_edit in self._text_inputs.items()
            },
            "properties": properties,
        }


__all__ = ("AnnotationEditorDialog",)
