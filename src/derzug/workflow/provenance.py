"""
Run manifest model for workflow provenance.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

import yaml
from pydantic import computed_field, field_validator

from derzug.constants import yaml_extensions

from ..core import DerzugModel

if TYPE_CHECKING:
    from .pipe import Pipe


class Provenance(DerzugModel):
    """Structured record of pipeline provenance and run metadata."""

    pipe: Pipe
    derzug_version: str
    created_at: datetime
    python_version: str
    system_info: dict[str, str]
    metadata: dict[str, Any]
    source_provenance: tuple[Provenance, ...] = ()

    @field_validator("pipe", mode="before")
    @classmethod
    def _coerce_pipe(cls, value):
        from .pipe import Pipe

        if isinstance(value, Pipe):
            return value
        if isinstance(value, dict):
            return Pipe._from_dict(value)
        return value

    @computed_field
    @property
    def fingerprint(self) -> str:
        """Return the fingerprint of the recorded pipeline."""
        return self.pipe.fingerprint

    def to_source_provenance(self) -> tuple[Provenance, ...]:
        """Return source manifests with the current manifest appended."""
        return (*self.source_provenance, self)

    def __hash__(self) -> int:
        """Hash based on the stable pipeline fingerprint."""
        return hash(self.fingerprint)

    def save(self, path: str | Path) -> Provenance:
        """
        Serialize the provenance to disk.

        Parameters
        ----------
        path : str or Path
            Destination file path. The extension determines the format:
            `.yaml`/`.yml` for YAML, otherwise JSON is used. If no extension is
            provided, JSON is written.

        Returns
        -------
        Provenance
            Returns self to enable call chaining.
        """
        path = Path(path)
        path.parent.mkdir(exist_ok=True, parents=True)
        format_target = path.suffix.lstrip(".").lower() or "json"
        # Don't dump pipe or source provenance; we handle those explicitly
        payload = self.model_dump(mode="json")
        payload["pipeline"] = self.pipe._to_dict()
        payload.pop("pipe", None)
        payload["fingerprint"] = self.fingerprint
        # Convert to yaml if requested.
        if format_target in yaml_extensions:
            payload = yaml.safe_dump(payload, sort_keys=False)
            path.write_text(payload, encoding="utf-8")
        else:
            path.write_text(
                json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8"
            )
        return self

    @classmethod
    def load(cls, path: str | Path) -> Provenance:
        """
        Load a provenance manifest from disk.

        Parameters
        ----------
        path : str or Path
            Path to a JSON or YAML provenance file.

        Returns
        -------
        Provenance
            Parsed provenance instance.
        """
        path = Path(path)
        contents = path.read_text(encoding="utf-8")
        file_format = path.suffix.lstrip(".").lower()
        if file_format in yaml_extensions:
            data = yaml.safe_load(contents)
        else:
            data = json.loads(contents)
        if "pipeline" in data and "pipe" not in data:
            data["pipe"] = data.pop("pipeline")
        return cls.model_validate(data)


class ProvenanceMap(DerzugModel):
    """A serializable provenance map."""

    data: dict[str, Provenance]


class FingerPrintTuple(DerzugModel):
    """Serializable tuple for provenance fingerprints."""

    data: tuple[str, ...]
