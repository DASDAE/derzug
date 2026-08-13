"""Tests for the version-independent DASCore accessors."""

from __future__ import annotations

import shutil

import dascore as dc
import pandas as pd
import pytest
from derzug.utils.dascore_compat import (
    contents_dims,
    contents_path_column,
    is_directory_spool,
    is_file_spool,
    selectable_contents_keys,
    spool_source_path,
)


def _contents_df() -> pd.DataFrame:
    """Return a small synthetic spool contents dataframe."""
    return pd.DataFrame(
        {
            "dims": [("distance", "time"), ("distance", "time"), ("distance", "time")],
            "distance_min": [0.0, 100.0, 200.0],
            "distance_max": [50.0, 150.0, 250.0],
            "time_min": [0.0, 0.0, 0.0],
            "time_max": [10.0, 10.0, 10.0],
            "tag": ["first", "second", "third"],
        }
    )


@pytest.fixture(scope="module")
def memory_spool() -> dc.BaseSpool:
    """Return a spool whose patches live in memory."""
    return dc.get_example_spool("random_das")


@pytest.fixture(scope="module")
def directory_spool(tmp_path_factory, memory_spool) -> dc.BaseSpool:
    """Return a spool backed by a directory of DASDAE files."""
    directory = tmp_path_factory.mktemp("spool_directory")
    dc.examples.spool_to_directory(memory_spool, directory)
    return dc.spool(directory).update()


@pytest.fixture(scope="module")
def file_spool(tmp_path_factory, memory_spool) -> dc.BaseSpool:
    """Return a spool backed by one multi-patch file."""
    path = tmp_path_factory.mktemp("spool_file") / "patches.h5"
    dc.write(memory_spool, path, file_format="DASDAE")
    return dc.spool(path)


class TestSpoolSourcePath:
    """The backing store of a spool, whichever DASCore built it."""

    def test_memory_spool_has_no_source_path(self, memory_spool):
        """A spool of live patches reads from nothing on disk."""
        assert spool_source_path(memory_spool) is None
        assert not is_directory_spool(memory_spool)
        assert not is_file_spool(memory_spool)

    def test_directory_spool_reports_its_directory(self, directory_spool):
        """A directory spool names the directory it indexed."""
        path = spool_source_path(directory_spool)

        assert path is not None and path.is_dir()
        assert is_directory_spool(directory_spool)
        assert not is_file_spool(directory_spool)

    def test_file_spool_reports_its_file(self, file_spool):
        """A single-file spool names its file, not its parent directory."""
        path = spool_source_path(file_spool)

        assert path is not None and path.is_file()
        assert is_file_spool(file_spool)
        assert not is_directory_spool(file_spool)

    @pytest.mark.parametrize("op", [lambda s: s.select(tag="*"), lambda s: s[:2]])
    def test_derived_directory_spool_keeps_its_directory(self, directory_spool, op):
        """Selecting or slicing does not detach a spool from its directory."""
        assert spool_source_path(op(directory_spool)) == spool_source_path(
            directory_spool
        )

    def test_vanished_directory_is_still_a_directory_spool(
        self, tmp_path, memory_spool
    ):
        """An unreadable directory must not make its spool look file-backed."""
        directory = tmp_path / "vanishing"
        dc.examples.spool_to_directory(memory_spool, directory)
        spool = dc.spool(directory).update()
        shutil.rmtree(directory)

        assert is_directory_spool(spool)
        assert not is_file_spool(spool)

    def test_path_attribute_does_not_make_a_memory_spool_file_backed(self):
        """A patch attribute named ``path`` is metadata, not a backing file."""
        patch = dc.get_example_patch().update_attrs(path="nonexistent-source.h5")
        spool = dc.spool([patch])

        assert not is_file_spool(spool)
        assert not is_directory_spool(spool)


class TestContentsPathColumn:
    """Resolving the contents column that names each patch's source file."""

    def test_prefers_current_column_name(self):
        """The newer name wins when a table somehow carries both."""
        df = pd.DataFrame({"path": ["a.h5"], "source_path": ["b.h5"]})

        assert contents_path_column(df) == "source_path"

    def test_falls_back_to_legacy_column_name(self):
        """Older contents tables spell the column ``path``."""
        assert contents_path_column(pd.DataFrame({"path": ["a.h5"]})) == "path"

    def test_missing_column_returns_none(self):
        """Contents without any source column resolve to nothing."""
        assert contents_path_column(pd.DataFrame({"tag": ["a"]})) is None

    def test_directory_contents_carry_a_path_column(self, directory_spool):
        """A real directory spool always names its files somewhere."""
        assert contents_path_column(directory_spool.get_contents()) is not None


class TestSelectKeys:
    """Turning a contents table into the names ``Spool.select`` accepts."""

    def test_dims_are_read_in_first_seen_order(self):
        """Every dimension a spool's patches use is reported once."""
        df = pd.DataFrame({"dims": [("distance", "time"), ("time", "depth")]})

        assert contents_dims(df) == ["distance", "time", "depth"]

    def test_contents_without_dims_have_none(self):
        """A table that never names its dimensions reports none."""
        assert contents_dims(pd.DataFrame({"tag": ["a"]})) == []

    def test_dims_replace_their_flattened_columns(self):
        """``distance_min`` describes a coordinate; ``distance`` selects on it."""
        keys = selectable_contents_keys(_contents_df())

        assert keys == ("distance", "tag", "time")

    def test_source_columns_are_not_offered(self):
        """Where a patch was read from is bookkeeping, not a select key."""
        df = pd.DataFrame(
            {
                "dims": [("time",)],
                "source_path": ["a.h5"],
                "source_format": ["DASDAE"],
                "path": ["a.h5"],
                "_patch_id": ["abc"],
                "station": ["A1"],
            }
        )

        assert selectable_contents_keys(df) == ("station", "time")

    def test_candidate_columns_restrict_metadata_but_not_dims(self):
        """Callers narrow the metadata columns; every dimension stays offered."""
        keys = selectable_contents_keys(_contents_df(), ["distance_min"])

        assert keys == ("distance", "time")

    def test_auxiliary_coordinates_are_offered_by_name(self):
        """A coordinate DASCore summarizes but ``dims`` never names is selectable."""
        df = _contents_df().assign(
            latitude_min=[0.0, 1.0, 2.0],
            latitude_max=[1.0, 2.0, 3.0],
            latitude_units=["deg", "deg", "deg"],
        )

        keys = selectable_contents_keys(df)

        assert keys == ("distance", "latitude", "tag", "time")

    def test_real_spool_offers_only_names_dascore_accepts(self):
        """Every offered key must survive a real ``Spool.select`` call."""
        spool = dc.spool([dc.get_example_patch("random_patch_with_lat_lon")])

        for key in selectable_contents_keys(spool.get_contents()):
            spool.select(**{key: (None, None)})
