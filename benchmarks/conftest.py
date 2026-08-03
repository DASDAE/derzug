"""Shared fixtures for the DerZug performance benchmarks.

The benchmarks in this directory intentionally avoid Qt/Orange widgets so the
measurements stay deterministic and free of GUI event-loop noise. They target
the pure-python hot paths that widgets call into: the workflow engine, the
annotation models, spool metadata helpers, and the display/sampling utilities.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
import pytest
from derzug.models.annotations import Annotation, AnnotationSet

# Number of rows in the synthetic spool contents dataframe.
SPOOL_ROW_COUNT = 2_000
# Number of annotations in the synthetic annotation set.
ANNOTATION_COUNT = 200
# Row stride between consecutive annotations, keeps ~10% of rows uncovered so
# the vectorized overlap kernels never exit early on a fully-true mask.
ANNOTATION_ROW_STRIDE = 9

TIME_START = np.datetime64("2023-01-01T00:00:00")
TIME_STEP = np.timedelta64(10, "s")
DISTANCE_STEP = 10.0
GEOMETRY_TYPES = ("point", "span", "box", "path", "polygon")


def _row_time(row: int) -> np.datetime64:
    """Return the start time of one synthetic spool row."""
    return TIME_START + row * TIME_STEP


def _row_distance(row: int) -> float:
    """Return the start distance of one synthetic spool row."""
    return row * DISTANCE_STEP


def _point_coords(row: int, offset: float = 0.5) -> dict[str, object]:
    """Return coordinates inside one synthetic spool row."""
    return {
        "time": _row_time(row) + np.timedelta64(int(offset * 10), "s"),
        "distance": _row_distance(row) + offset * DISTANCE_STEP,
    }


def make_annotation(index: int) -> Annotation:
    """Build one annotation whose geometry type cycles through all variants."""
    row = (index * ANNOTATION_ROW_STRIDE) % SPOOL_ROW_COUNT
    kind = GEOMETRY_TYPES[index % len(GEOMETRY_TYPES)]
    if kind == "point":
        geometry: dict[str, object] = {
            "type": "point",
            "coords": _point_coords(row),
        }
    elif kind == "span":
        geometry = {
            "type": "span",
            "dim": "time",
            "start": _row_time(row),
            "end": _row_time(row + 1),
        }
    elif kind == "box":
        geometry = {
            "type": "box",
            "bounds": {
                "time": {"min": _row_time(row), "max": _row_time(row + 2)},
                "distance": {
                    "min": _row_distance(row),
                    "max": _row_distance(row + 2),
                },
            },
        }
    elif kind == "path":
        geometry = {
            "type": "path",
            "points": [_point_coords(row + step, 0.25) for step in range(3)],
        }
    else:
        geometry = {
            "type": "polygon",
            "points": [_point_coords(row + step, 0.75) for step in range(4)],
        }
    return Annotation(
        id=f"annotation-{index:04d}",
        geometry=geometry,
        semantic_type="event" if index % 2 else "generic",
        annotator="benchmark",
        label=f"label {index}",
        tags=("bench", f"group-{index % 7}"),
        properties={"score": index / ANNOTATION_COUNT, "kind": kind},
    )


def make_annotation_set(count: int = ANNOTATION_COUNT) -> AnnotationSet:
    """Build one annotation set with a mix of geometry types."""
    return AnnotationSet(
        dims=("time", "distance"),
        annotations=tuple(make_annotation(index) for index in range(count)),
        provenance={"source": "benchmarks"},
    )


def make_spool_contents(rows: int = SPOOL_ROW_COUNT) -> pd.DataFrame:
    """Build a spool contents dataframe resembling DASCore spool metadata."""
    index = np.arange(rows)
    time_min = TIME_START + index * TIME_STEP
    distance_min = index * DISTANCE_STEP
    return pd.DataFrame(
        {
            "path": [f"patch_{value:05d}.h5" for value in index],
            "file_format": "DASDAE",
            "time_min": time_min,
            "time_max": time_min + TIME_STEP,
            "distance_min": distance_min,
            "distance_max": distance_min + DISTANCE_STEP,
            "d_time": np.full(rows, TIME_STEP),
            "d_distance": np.full(rows, 1.0),
            "tag": ["" if value % 3 else f"tag_{value % 11}" for value in index],
            "station": np.where(index % 2, "SN01", "SN02"),
            "network": "",
            "dims": "(time, distance)",
        }
    )


@pytest.fixture(scope="session")
def annotation_set() -> AnnotationSet:
    """Return a reusable annotation set with mixed geometries."""
    return make_annotation_set()


@pytest.fixture(scope="session")
def spool_contents() -> pd.DataFrame:
    """Return a reusable synthetic spool contents dataframe."""
    return make_spool_contents()
