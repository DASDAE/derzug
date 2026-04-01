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
CoordMap = dict[str, CoordScalar]


class CoordRange(_StrictModel):
    """One inclusive coordinate interval on a named dimension."""

    min: CoordScalar
    max: CoordScalar

    @field_validator("min", "max", mode="before")
    @classmethod
    def _normalize_value(cls, value) -> CoordScalar:
        return normalize_coord_value(value)


def normalize_coord_value(value: Any) -> CoordScalar:
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


def _normalize_coord_map(value: Any) -> CoordMap:
    """Normalize one mapping of dimension names to coordinate values."""
    if not isinstance(value, dict):
        raise TypeError("geometry coordinates must be a mapping")
    coords: CoordMap = {}
    for dim, coord in value.items():
        dim_name = str(dim).strip()
        if not dim_name:
            raise ValueError("geometry dimensions must be non-empty")
        if dim_name in coords:
            raise ValueError("geometry dimensions must be unique")
        coords[dim_name] = normalize_coord_value(coord)
    return coords


def geometry_dims(geometry: Geometry) -> tuple[str, ...]:
    """Return geometry dimensions in display order."""
    if isinstance(geometry, SpanGeometry):
        return (geometry.dim,)
    if isinstance(geometry, PointGeometry):
        return tuple(geometry.coords)
    if isinstance(geometry, BoxGeometry):
        return tuple(geometry.bounds)
    if isinstance(geometry, PathGeometry | PolygonGeometry):
        if geometry.points:
            return tuple(geometry.points[0])
        return ()
    raise TypeError(f"unsupported geometry type {type(geometry)!r}")


def geometry_coord(geometry: Geometry, dim: str) -> CoordScalar | None:
    """Return a point-like coordinate for one dim when available."""
    if isinstance(geometry, SpanGeometry):
        return geometry.start if geometry.dim == dim else None
    if isinstance(geometry, PointGeometry):
        return geometry.coords.get(dim)
    if isinstance(geometry, BoxGeometry):
        bounds = geometry.bounds.get(dim)
        return None if bounds is None else bounds.min
    if isinstance(geometry, PathGeometry | PolygonGeometry):
        if not geometry.points:
            return None
        return geometry.points[0].get(dim)
    raise TypeError(f"unsupported geometry type {type(geometry)!r}")


def geometry_ordered_coords(
    geometry: PointGeometry, dims: tuple[str, ...]
) -> tuple[CoordScalar, ...]:
    """Return point coordinates in the requested order."""
    return tuple(geometry.coords[dim] for dim in dims)


def geometry_bounds(geometry: Geometry, dim: str) -> CoordRange | None:
    """Return bounds for one dimension when the geometry defines them."""
    if isinstance(geometry, SpanGeometry):
        if geometry.dim != dim:
            return None
        return CoordRange(min=geometry.start, max=geometry.end)
    if isinstance(geometry, BoxGeometry):
        return geometry.bounds.get(dim)
    if isinstance(geometry, PointGeometry):
        value = geometry.coords.get(dim)
        return None if value is None else CoordRange(min=value, max=value)
    if isinstance(geometry, PathGeometry | PolygonGeometry):
        values = [point[dim] for point in geometry.points if dim in point]
        if not values:
            return None
        return CoordRange(min=min(values), max=max(values))
    raise TypeError(f"unsupported geometry type {type(geometry)!r}")


def geometry_point_coords(
    geometry: PathGeometry | PolygonGeometry,
    index: int,
    dims: tuple[str, ...],
) -> tuple[CoordScalar, ...]:
    """Return one path/polygon point in the requested dimension order."""
    return tuple(geometry.points[index][dim] for dim in dims)


class PointGeometry(_StrictModel):
    """One point annotation in one or more dimensions."""

    type: Literal["point"] = "point"
    coords: CoordMap

    @field_validator("coords", mode="before")
    @classmethod
    def _normalize_coords(cls, value) -> CoordMap:
        return _normalize_coord_map(value)

    @model_validator(mode="after")
    def _validate_coords(self) -> PointGeometry:
        if not self.coords:
            raise ValueError("point coords must not be empty")
        return self


class SpanGeometry(_StrictModel):
    """One 1D span annotation."""

    type: Literal["span"] = "span"
    dim: str
    start: CoordScalar
    end: CoordScalar

    @field_validator("dim")
    @classmethod
    def _validate_dim(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("span dim must not be empty")
        return value

    @field_validator("start", "end", mode="before")
    @classmethod
    def _normalize_bounds(cls, value) -> CoordScalar:
        return normalize_coord_value(value)


class BoxGeometry(_StrictModel):
    """One axis-aligned box annotation across two or more dimensions."""

    type: Literal["box"] = "box"
    bounds: dict[str, CoordRange]

    @field_validator("bounds", mode="before")
    @classmethod
    def _normalize_bounds(cls, value) -> dict[str, CoordRange]:
        if not isinstance(value, dict):
            raise TypeError("box bounds must be a mapping")
        bounds: dict[str, CoordRange] = {}
        for dim, coord_range in value.items():
            dim_name = str(dim).strip()
            if not dim_name:
                raise ValueError("box dimensions must be non-empty")
            if dim_name in bounds:
                raise ValueError("box dimensions must be unique")
            bounds[dim_name] = (
                coord_range
                if isinstance(coord_range, CoordRange)
                else CoordRange.model_validate(coord_range)
            )
        return bounds

    @model_validator(mode="after")
    def _validate_bounds(self) -> BoxGeometry:
        if len(self.bounds) < 2:
            raise ValueError("box bounds must contain at least two dimensions")
        return self


class PathGeometry(_StrictModel):
    """One ordered path annotation."""

    type: Literal["path"] = "path"
    points: tuple[CoordMap, ...]

    @field_validator("points", mode="before")
    @classmethod
    def _normalize_points(cls, value) -> tuple[CoordMap, ...]:
        return tuple(_normalize_coord_map(point) for point in tuple(value))

    @model_validator(mode="after")
    def _validate_points(self) -> PathGeometry:
        if not self.points:
            raise ValueError("path points must not be empty")
        dims = tuple(self.points[0])
        if not dims:
            raise ValueError("path points must not be empty")
        if any(tuple(point) != dims for point in self.points[1:]):
            raise ValueError("each path point must use the same dims")
        return self


class PolygonGeometry(_StrictModel):
    """One polygon annotation."""

    type: Literal["polygon"] = "polygon"
    points: tuple[CoordMap, ...]

    @field_validator("points", mode="before")
    @classmethod
    def _normalize_points(cls, value) -> tuple[CoordMap, ...]:
        return tuple(_normalize_coord_map(point) for point in tuple(value))

    @model_validator(mode="after")
    def _validate_points(self) -> PolygonGeometry:
        if len(self.points) < 3:
            raise ValueError("polygon points must contain at least three points")
        dims = tuple(self.points[0])
        if len(dims) < 2:
            raise ValueError("polygon points must contain at least two dimensions")
        if any(tuple(point) != dims for point in self.points[1:]):
            raise ValueError("each polygon point must use the same dims")
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

    schema_version: Literal["3"] = "3"
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
            if not set(geometry_dims(annotation.geometry)) <= valid_dims:
                raise ValueError(
                    f"annotation {annotation.id!r} uses dims outside the annotation set"
                )
        return self


__all__ = (
    "Annotation",
    "AnnotationSet",
    "BoxGeometry",
    "CoordMap",
    "CoordRange",
    "CoordScalar",
    "Geometry",
    "PathGeometry",
    "PointGeometry",
    "PolygonGeometry",
    "SpanGeometry",
    "geometry_bounds",
    "geometry_coord",
    "geometry_dims",
    "geometry_ordered_coords",
    "geometry_point_coords",
    "normalize_coord_value",
)
