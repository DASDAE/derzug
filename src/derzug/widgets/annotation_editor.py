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
        self._text = QLineEdit(annotation.text or "", self)
        self._tags = QLineEdit(", ".join(annotation.tags), self)
        self._group = QLineEdit(annotation.group or "", self)
        self._properties = QLineEdit(
            json.dumps(annotation.properties, sort_keys=True),
            self,
        )

        form.addRow("Type", self._semantic_type)
        form.addRow("Text", self._text)
        form.addRow("Tags", self._tags)
        form.addRow("Group", self._group)
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
            "text": self._text.text().strip() or None,
            "tags": tuple(tag.strip() for tag in raw_tags.split(",") if tag.strip()),
            "group": self._group.text().strip() or None,
            "properties": properties,
        }


__all__ = ("AnnotationEditorDialog",)
