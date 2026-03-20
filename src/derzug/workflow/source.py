"""
A source is an iterable a pipe consumes (with metadata).
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import ClassVar, Generic, Literal, Self, TypeVar

import pandas as pd
from pydantic import Field

from ..core import SlanRodModel
from .provenance import Provenance

DataType = TypeVar("DataType")


class Source(SlanRodModel, ABC, Generic[DataType]):
    """
    A Source of pipe inputs.

    This allows the provenance of input data to be accounted for.
    """

    provenance: Provenance | None = None

    # Common methods
    def get_single_data(self) -> DataType:
        """
        Get the first data from a source.

        Raise a warning if source contains multiple data.
        """
        if not len(self):
            msg = f"Source: {self} contains no data!"
            raise ValueError(msg)
        if len(self) > 1:
            msg = f"Source: {self} contains more than one data!"
            warnings.warn(msg)
        return self[0]

    # Required methods.

    @abstractmethod
    def __len__(self):
        """Get the length of a source."""
        raise NotImplementedError("Not implemented")

    @abstractmethod
    def __getitem__(self, item) -> DataType:
        """Get the content of a source."""
        raise NotImplementedError("Not implemented")

    @abstractmethod
    def __iter__(self) -> Iterator[DataType]:
        """Iterate over the source."""
        raise NotImplementedError("Not implemented")

    # Optional methods.
    @classmethod
    def from_path(cls, path, provenance=None, **kwargs) -> Self:
        """Load a source from a path."""
        raise NotImplementedError("Not implemented")


class FileSystemSource(Source, ABC, Generic[DataType]):
    """
    Base class for sources that read from the filesystem.
    """

    path: Path
    provenance: tuple[Provenance, ...] = Field(default_factory=tuple)
    data_extension: ClassVar[str] = ""
    # Indicates if the sink data is stored in a single file next to the
    # provenance or in a directory.
    storage_type: Literal["file", "directory"] = "directory"

    @classmethod
    def from_path(cls, path, provenance=None, fingerprint=None, **kwargs):
        """
        Load a source from a provenance or data path.
        """
        from slanrod.workflow.sink import get_provmap_and_fingerprints_from_path

        path = Path(path)
        if provenance is not None:
            normalized = cls._normalize_provenance(provenance)
            return cls(path=path, provenance=normalized)
        # This should support two modes; if you pass a directory with data
        # files, or if you pass the Sink directory plus the fingerprint.
        if fingerprint is not None:
            prov_map, fps = get_provmap_and_fingerprints_from_path(path)
            if isinstance(fingerprint, int):
                fingerprint = fps[fingerprint]
            provenance = prov_map.get(fingerprint)
            path = path / fingerprint
        else:
            fingerprint = path.stem
            prov_map, _ = get_provmap_and_fingerprints_from_path(path.parent)
            provenance = prov_map.get(fingerprint)
            # In this case the provenance is not on the same level as the
            # data file, we need to look inside the data file.
            if provenance is None:
                prov_map, _ = get_provmap_and_fingerprints_from_path(path)
                provenance = prov_map.get(fingerprint)
        normalized = cls._normalize_provenance(provenance)
        return cls(path=path, provenance=normalized)

    @classmethod
    def _normalize_provenance(
        cls, provenance: Provenance | tuple[Provenance, ...] | None
    ) -> tuple[Provenance, ...]:
        """Normalize provenance inputs into a tuple."""
        if provenance is None:
            return ()
        if hasattr(provenance, "to_source_provenance"):
            return provenance.to_source_provenance()
        if isinstance(provenance, tuple):
            return provenance
        return (provenance,)

    @lru_cache
    def get_content_df(self) -> pd.DataFrame:
        """Get a dataframe containing the contents of this source."""
        out = []
        if self.data_extension:
            pattern = f"*.{self.data_extension}"
        else:
            pattern = "*"
        root = Path(self.path)
        for path in root.rglob(pattern):
            stat = path.stat()
            data_root = root
            if root.is_dir():
                try:
                    rel = path.relative_to(root)
                except ValueError:
                    rel = None
                if rel is not None and rel.parts:
                    first_path = root / rel.parts[0]
                    data_root = first_path if first_path.is_dir() else root
            sub = {
                "st_size": stat.st_size,
                "st_mtime": stat.st_mtime,
                "st_ctime": stat.st_ctime,
            }
            sub["path"] = str(path)
            sub["data_root"] = str(data_root)
            out.append(sub)
        df = pd.DataFrame(out)
        if not df.empty:
            df = df.sort_values(["st_ctime", "st_mtime", "path"], kind="mergesort")
        return df

    def get_single_data(self) -> DataType:
        """
        Get the first data from a filesystem source.

        If multiple directory roots exist, return the first directory's data.
        """
        df = self.get_content_df()
        if df.empty:
            msg = f"Source: {self} contains no data!"
            raise ValueError(msg)
        root_col = "data_root" if "data_root" in df.columns else "path"
        root_values = df[root_col]
        if len(root_values.unique()) > 1:
            msg = f"Source: {self} contains more than one data!"
            warnings.warn(msg)
        first_root = Path(root_values.iloc[0])
        if first_root.is_dir():
            return self.deserialize_data(first_root)
        return self.deserialize_data(Path(df["path"].iloc[0]))

    def __len__(self) -> int:
        return len(self.get_content_df())

    def __iter__(self) -> Iterator[DataType]:
        for path in self.get_content_df()["path"].values:
            yield self.deserialize_data(Path(path))

    def __getitem__(self, item) -> DataType:
        path = self.get_content_df()["path"].values[item]
        return self.deserialize_data(Path(path))

    @abstractmethod
    def deserialize_data(self, path: Path) -> DataType:
        """Deserialize the contents of a path."""
