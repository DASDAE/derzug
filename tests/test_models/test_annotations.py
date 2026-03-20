"""Tests for persisted annotation models."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import numpy as np
import pytest
from derzug.models.annotations import Annotation, AnnotationSet
from pydantic import ValidationError


def test_annotation_set_accepts_mixed_1d_and_2d_geometry():
    """Geometry-level dims should allow 1D and 2D annotations in one set."""
    annotation_set = AnnotationSet(
        dims=("distance", "time"),
        annotations=(
            Annotation(
                id="pick-1",
                semantic_type="arrival_pick",
                geometry={
                    "type": "point",
                    "dims": ("distance", "time"),
                    "values": (10.0, 2.5),
                },
            ),
            Annotation(
                id="window-1",
                semantic_type="ringdown_window",
                geometry={
                    "type": "span",
                    "dim": "time",
                    "start": 2.0,
                    "end": 3.5,
                },
            ),
        ),
    )

    assert annotation_set.schema_version == "2"
    assert "basis" not in annotation_set.model_dump()
    assert annotation_set.annotations[0].geometry.type == "point"
    assert annotation_set.annotations[1].geometry.type == "span"


def test_annotation_set_rejects_legacy_basis_field():
    """Legacy basis-bearing payloads should fail validation."""
    with pytest.raises(ValidationError):
        AnnotationSet.model_validate(
            {
                "dims": ("distance",),
                "basis": "coord",
                "annotations": (),
            }
        )


def test_annotation_set_rejects_legacy_index_basis_field():
    """Legacy index-basis payloads should fail validation."""
    with pytest.raises(ValidationError):
        AnnotationSet.model_validate(
            {
                "dims": ("distance",),
                "basis": "index",
                "annotations": (),
            }
        )


def test_annotation_set_rejects_geometry_dims_outside_set_dims():
    """Annotations should not reference dimensions unknown to the set."""
    with pytest.raises(ValidationError, match="outside the annotation set"):
        AnnotationSet(
            dims=("distance", "time"),
            annotations=(
                Annotation(
                    id="bad",
                    geometry={
                        "type": "span",
                        "dim": "offset",
                        "start": 1.0,
                        "end": 2.0,
                    },
                ),
            ),
        )


def test_path_geometry_requires_points_to_match_dims():
    """Path points should have one value per geometry dimension."""
    with pytest.raises(ValidationError, match="match dims length"):
        Annotation(
            id="bad-path",
            geometry={
                "type": "path",
                "dims": ("distance", "time"),
                "points": ((0.0,), (1.0, 2.0)),
            },
        )


def test_derived_annotations_use_properties_not_fit_schema():
    """Derived metadata should round-trip through the open properties field."""
    annotation = Annotation(
        id="fit-1",
        semantic_type="arrival_trend",
        geometry={
            "type": "path",
            "dims": ("distance", "time"),
            "points": ((0.0, 1.0), (10.0, 3.0)),
        },
        properties={
            "fit_model": "line",
            "fit_parameters": {"slope": 0.2, "intercept": 1.0},
            "derived_from": ["pick-1", "pick-2"],
        },
    )

    dumped = annotation.model_dump(mode="json")

    assert dumped["properties"]["fit_model"] == "line"
    assert dumped["properties"]["derived_from"] == ["pick-1", "pick-2"]


def test_hyperbola_annotations_round_trip_through_properties():
    """Hyperbola fits should persist as sampled paths plus explicit metadata."""
    annotation = Annotation(
        id="hyperbola-1",
        semantic_type="hyperbola",
        geometry={
            "type": "path",
            "dims": ("distance", "time"),
            "points": ((0.0, 1.0), (0.5, 1.2), (1.5, 2.0)),
        },
        properties={
            "fit_model": "hyperbola",
            "fit_parameters": {
                "axis_angle": 0.0,
                "direction": 1,
                "vertex_x": 0.0,
                "vertex_y": 1.0,
                "a": 1.5,
                "b": 0.4,
                "extent": 1.0,
                "samples": 96,
            },
            "hyperbola_source": "fit",
            "derived_from": ["pick-1", "pick-2", "pick-3"],
        },
    )

    dumped = annotation.model_dump(mode="json")

    assert dumped["properties"]["fit_model"] == "hyperbola"
    assert dumped["properties"]["fit_parameters"]["axis_angle"] == 0.0
    assert dumped["properties"]["hyperbola_source"] == "fit"


def test_ellipse_annotations_round_trip_through_properties():
    """Ellipse fits should persist as sampled paths plus explicit metadata."""
    annotation = Annotation(
        id="ellipse-1",
        semantic_type="ellipse",
        geometry={
            "type": "path",
            "dims": ("distance", "time"),
            "points": ((0.0, 1.0), (0.5, 1.2), (1.0, 1.0), (0.5, 0.8)),
        },
        properties={
            "fit_model": "ellipse",
            "fit_parameters": {
                "center_x": 0.5,
                "center_y": 1.0,
                "radius_x": 0.5,
                "radius_y": 0.2,
                "axis_angle": 0.0,
                "samples": 96,
            },
            "ellipse_source": "fit",
            "derived_from": ["pick-1", "pick-2", "pick-3"],
        },
    )

    dumped = annotation.model_dump(mode="json")

    assert dumped["properties"]["fit_model"] == "ellipse"
    assert dumped["properties"]["fit_parameters"]["radius_x"] == 0.5
    assert dumped["properties"]["fit_parameters"]["axis_angle"] == 0.0
    assert dumped["properties"]["ellipse_source"] == "fit"


def test_unknown_geometry_type_is_rejected():
    """The schema should only admit the simplified geometry primitives."""
    with pytest.raises(ValidationError, match="Input tag 'line'"):
        Annotation(
            id="bad-geometry",
            geometry={
                "type": "line",
                "dims": ("distance", "time"),
                "start": (0.0, 0.0),
                "end": (1.0, 1.0),
            },
        )


def test_annotation_accepts_datetime_coord_values_and_json_round_trips():
    """Datetime coordinates should normalize into persisted JSON-safe values."""
    annotation = Annotation(
        id="dt-point",
        geometry={
            "type": "point",
            "dims": ("time",),
            "values": (np.datetime64("2024-01-02T03:04:05"),),
        },
    )

    assert annotation.geometry.values == (
        datetime(2024, 1, 2, 3, 4, 5, tzinfo=timezone.utc),
    )
    dumped = annotation.model_dump(mode="json")
    assert dumped["geometry"]["values"] == ["2024-01-02T03:04:05Z"]


def test_annotation_accepts_timedelta_coord_values_and_json_round_trips():
    """Timedelta coordinates should normalize into persisted JSON-safe values."""
    annotation = Annotation(
        id="td-span",
        geometry={
            "type": "span",
            "dim": "time",
            "start": np.timedelta64(5, "s"),
            "end": np.timedelta64(2500, "ms"),
        },
    )

    assert annotation.geometry.start == timedelta(seconds=5)
    assert annotation.geometry.end == timedelta(seconds=2.5)
    dumped = annotation.model_dump(mode="json")
    assert dumped["geometry"]["start"] == "PT5S"
    assert dumped["geometry"]["end"] == "PT2.5S"


def test_annotation_accepts_string_coord_values():
    """Categorical coordinates should be allowed in coordinate-based annotations."""
    annotation = Annotation(
        id="str-point",
        geometry={
            "type": "point",
            "dims": ("channel",),
            "values": ("channel-12",),
        },
    )

    assert annotation.geometry.values == ("channel-12",)
