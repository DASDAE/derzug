"""Global annotation configuration persisted outside workflow files."""

from __future__ import annotations

from dataclasses import dataclass

from AnyQt.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)
from orangecanvas.utils.settings import QSettings

from derzug.utils.annotation_metadata import LABEL_SLOTS

_SETTINGS_GROUP = "annotations"
_ANNOTATOR_KEY = "annotator"
_ORGANIZATION_KEY = "organization"
_LABEL_PREFIX = "labels/"
_ANNOTATION_CONFIG_CACHE: AnnotationConfig | None = None


@dataclass(frozen=True)
class AnnotationConfig:
    """Current global annotation configuration."""

    annotator: str = ""
    organization: str = ""
    label_names: dict[str, str] | None = None

    def __post_init__(self) -> None:
        label_names = dict(self.label_names or {})
        normalized = {
            slot: (str(label_names.get(slot, slot)).strip() or slot)
            for slot in LABEL_SLOTS
        }
        object.__setattr__(self, "label_names", normalized)

    def label_name(self, slot: str) -> str:
        """Return the configured label for one numeric slot."""
        return self.label_names.get(str(slot), str(slot))

    def slot_for_label(self, label: str | None) -> str | None:
        """Return the current slot backing one stored label value."""
        if label is None:
            return None
        normalized = str(label).strip()
        if not normalized:
            return None
        if normalized in LABEL_SLOTS:
            return normalized
        for slot in LABEL_SLOTS:
            if self.label_name(slot) == normalized:
                return slot
        return None


def _read_annotation_config(settings: QSettings) -> AnnotationConfig:
    """Read annotation configuration from one settings object."""
    settings.beginGroup(_SETTINGS_GROUP)
    try:
        annotator = str(settings.value(_ANNOTATOR_KEY, "", type=str) or "").strip()
        organization = str(
            settings.value(_ORGANIZATION_KEY, "", type=str) or ""
        ).strip()
        label_names = {
            slot: str(settings.value(f"{_LABEL_PREFIX}{slot}", slot, type=str) or slot)
            for slot in LABEL_SLOTS
        }
    finally:
        settings.endGroup()
    return AnnotationConfig(
        annotator=annotator,
        organization=organization,
        label_names=label_names,
    )


def load_annotation_config(
    settings: QSettings | None = None,
    *,
    force_reload: bool = False,
) -> AnnotationConfig:
    """Load the user's global annotation configuration.

    Default application settings are cached because overlay styling and
    annotation creation paths consult this frequently.
    """
    global _ANNOTATION_CONFIG_CACHE
    if settings is not None:
        return _read_annotation_config(settings)
    if _ANNOTATION_CONFIG_CACHE is None or force_reload:
        _ANNOTATION_CONFIG_CACHE = _read_annotation_config(QSettings())
    return _ANNOTATION_CONFIG_CACHE


def save_annotation_config(
    config: AnnotationConfig, settings: QSettings | None = None
) -> None:
    """Persist the user's global annotation configuration."""
    global _ANNOTATION_CONFIG_CACHE
    use_default_settings = settings is None
    settings = QSettings() if settings is None else settings
    settings.beginGroup(_SETTINGS_GROUP)
    try:
        settings.setValue(_ANNOTATOR_KEY, config.annotator.strip())
        settings.setValue(_ORGANIZATION_KEY, config.organization.strip())
        for slot in LABEL_SLOTS:
            settings.setValue(f"{_LABEL_PREFIX}{slot}", config.label_name(slot))
    finally:
        settings.endGroup()
    if use_default_settings:
        _ANNOTATION_CONFIG_CACHE = config


def clear_annotation_config_cache() -> None:
    """Clear the cached default annotation configuration."""
    global _ANNOTATION_CONFIG_CACHE
    _ANNOTATION_CONFIG_CACHE = None


class AnnotationSettingsDialog(QDialog):
    """Modal editor for global annotation configuration."""

    def __init__(
        self,
        config: AnnotationConfig | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Annotation Settings")
        self.setModal(True)
        self.resize(360, 320)

        config = AnnotationConfig() if config is None else config

        layout = QVBoxLayout(self)
        form = QFormLayout()
        layout.addLayout(form)

        self._annotator = QLineEdit(config.annotator, self)
        self._annotator.setObjectName("annotation-settings-annotator")
        self._organization = QLineEdit(config.organization, self)
        self._organization.setObjectName("annotation-settings-organization")
        form.addRow("Annotator", self._annotator)
        form.addRow("Organization", self._organization)

        self._label_inputs: dict[str, QLineEdit] = {}
        for slot in LABEL_SLOTS:
            line_edit = QLineEdit(config.label_name(slot), self)
            line_edit.setObjectName(f"annotation-settings-label-{slot}")
            self._label_inputs[slot] = line_edit
            form.addRow(f"Label {slot}", line_edit)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=self,
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def config(self) -> AnnotationConfig:
        """Return the dialog values as one normalized config object."""
        return AnnotationConfig(
            annotator=self._annotator.text().strip(),
            organization=self._organization.text().strip(),
            label_names={
                slot: line_edit.text().strip() or slot
                for slot, line_edit in self._label_inputs.items()
            },
        )


__all__ = (
    "AnnotationConfig",
    "AnnotationSettingsDialog",
    "clear_annotation_config_cache",
    "load_annotation_config",
    "save_annotation_config",
)
