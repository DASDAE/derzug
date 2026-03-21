"""Persisted annotation models."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated, Any, Literal

import numpy as np
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class _StrictModel(BaseModel):
    """Base model for persisted annotation schema objects."""

    model_config = ConfigDict(extra="forbid")


CoordScalar = datetime | timedelta | float | int | str


def _normalize_coord_value(value: Any) -> CoordScalar:
    """Normalize coordinate-like scalars into JSON-safe Python values."""
    if isinstance(value, np.generic):
        if np.issubdtype(value.dtype, np.datetime64):
            ns_value = value.astype("datetime64[ns]").astype(np.int64).item()
            return datetime.fromtimestamp(ns_value / 1e9, tz=UTC)
        if np.issubdtype(value.dtype, np.timedelta64):
            ns_value = value.astype("timedelta64[ns]").astype(np.int64).item()
            return timedelta(microseconds=ns_value / 1000)
        value = value.item()
    if isinstance(value, datetime | timedelta | float | int | str):
        return value
    raise TypeError(f"unsupported coordinate value {value!r}")


def _normalize_coord_sequence(values: tuple[Any, ...]) -> tuple[CoordScalar, ...]:
    """Normalize one flat coordinate sequence."""
    return tuple(_normalize_coord_value(value) for value in values)


class PointGeometry(_StrictModel):
    """One point annotation in one or more dimensions."""

    type: Literal["point"] = "point"
    dims: tuple[str, ...]
    values: tuple[CoordScalar, ...]

    @field_validator("dims")
    @classmethod
    def _validate_dims(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("point dims must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("point dims must be unique")
        return value

    @field_validator("values", mode="before")
    @classmethod
    def _normalize_values(cls, value) -> tuple[CoordScalar, ...]:
        return _normalize_coord_sequence(tuple(value))

    @model_validator(mode="after")
    def _validate_values(self) -> PointGeometry:
        if len(self.dims) != len(self.values):
            raise ValueError("point values must match dims length")
        return self


class SpanGeometry(_StrictModel):
    """One 1D span annotation."""

    type: Literal["span"] = "span"
    dim: str
    start: CoordScalar
    end: CoordScalar

    @field_validator("start", "end", mode="before")
    @classmethod
    def _normalize_bounds(cls, value) -> CoordScalar:
        return _normalize_coord_value(value)


class BoxGeometry(_StrictModel):
    """One axis-aligned box annotation across two or more dimensions."""

    type: Literal["box"] = "box"
    dims: tuple[str, ...]
    min_corner: tuple[CoordScalar, ...]
    max_corner: tuple[CoordScalar, ...]

    @field_validator("dims")
    @classmethod
    def _validate_dims(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) < 2:
            raise ValueError("box dims must contain at least two dimensions")
        if len(set(value)) != len(value):
            raise ValueError("box dims must be unique")
        return value

    @field_validator("min_corner", "max_corner", mode="before")
    @classmethod
    def _normalize_corners(cls, value) -> tuple[CoordScalar, ...]:
        return _normalize_coord_sequence(tuple(value))

    @model_validator(mode="after")
    def _validate_corners(self) -> BoxGeometry:
        dim_count = len(self.dims)
        if len(self.min_corner) != dim_count or len(self.max_corner) != dim_count:
            raise ValueError("box corners must match dims length")
        return self


class PathGeometry(_StrictModel):
    """One ordered path annotation."""

    type: Literal["path"] = "path"
    dims: tuple[str, ...]
    points: tuple[tuple[CoordScalar, ...], ...]

    @field_validator("dims")
    @classmethod
    def _validate_dims(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("path dims must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("path dims must be unique")
        return value

    @field_validator("points", mode="before")
    @classmethod
    def _normalize_points(cls, value) -> tuple[tuple[CoordScalar, ...], ...]:
        return tuple(_normalize_coord_sequence(tuple(point)) for point in tuple(value))

    @model_validator(mode="after")
    def _validate_points(self) -> PathGeometry:
        if not self.points:
            raise ValueError("path points must not be empty")
        dim_count = len(self.dims)
        if any(len(point) != dim_count for point in self.points):
            raise ValueError("each path point must match dims length")
        return self


class PolygonGeometry(_StrictModel):
    """One polygon annotation."""

    type: Literal["polygon"] = "polygon"
    dims: tuple[str, ...]
    points: tuple[tuple[CoordScalar, ...], ...]

    @field_validator("dims")
    @classmethod
    def _validate_dims(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(value) < 2:
            raise ValueError("polygon dims must contain at least two dimensions")
        if len(set(value)) != len(value):
            raise ValueError("polygon dims must be unique")
        return value

    @field_validator("points", mode="before")
    @classmethod
    def _normalize_points(cls, value) -> tuple[tuple[CoordScalar, ...], ...]:
        return tuple(_normalize_coord_sequence(tuple(point)) for point in tuple(value))

    @model_validator(mode="after")
    def _validate_points(self) -> PolygonGeometry:
        if len(self.points) < 3:
            raise ValueError("polygon points must contain at least three points")
        dim_count = len(self.dims)
        if any(len(point) != dim_count for point in self.points):
            raise ValueError("each polygon point must match dims length")
        return self


Geometry = Annotated[
    PointGeometry | SpanGeometry | BoxGeometry | PathGeometry | PolygonGeometry,
    Field(discriminator="type"),
]


class Annotation(_StrictModel):
    """One persisted annotation."""

    id: str
    geometry: Geometry
    semantic_type: str = "generic"
    annotator: str | None = None
    organization: str | None = None
    notes: str | None = None
    tags: tuple[str, ...] = ()
    group: str | None = None
    label: str | None = None
    properties: dict[str, Any] = Field(default_factory=dict)
    ui: dict[str, Any] = Field(default_factory=dict)


class AnnotationSet(_StrictModel):
    """One collection of persisted annotations in absolute coordinates."""

    schema_version: str = "2"
    dims: tuple[str, ...]
    annotations: tuple[Annotation, ...] = ()
    provenance: dict[str, Any] = Field(default_factory=dict)

    @field_validator("dims")
    @classmethod
    def _validate_dims(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if not value:
            raise ValueError("annotation set dims must not be empty")
        if len(set(value)) != len(value):
            raise ValueError("annotation set dims must be unique")
        return value

    @model_validator(mode="after")
    def _validate_annotation_dims(self) -> AnnotationSet:
        valid_dims = set(self.dims)
        for annotation in self.annotations:
            geometry = annotation.geometry
            if isinstance(geometry, SpanGeometry):
                geometry_dims = {geometry.dim}
            else:
                geometry_dims = set(geometry.dims)
            if not geometry_dims <= valid_dims:
                raise ValueError(
                    f"annotation {annotation.id!r} uses dims outside the annotation set"
                )
        return self


__all__ = (
    "Annotation",
    "AnnotationSet",
    "BoxGeometry",
    "Geometry",
    "PathGeometry",
    "PointGeometry",
    "PolygonGeometry",
    "SpanGeometry",
)
