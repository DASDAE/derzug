"""
A sink (deposition) of pipe outputs.
"""

from __future__ import annotations

import shutil
import uuid
from abc import ABC, abstractmethod
from collections.abc import Iterator
from functools import lru_cache
from pathlib import Path
from typing import Any, ClassVar, Generic, Literal, Self, TypeVar

import pandas as pd
from dascore.utils.mapping import FrozenDict
from pydantic import Field

from .pipe import Pipe
from .provenance import Provenance
from .source import Source
from .task import Task

SourceType = TypeVar("SourceType", bound=Source[Any])
DataType = TypeVar("DataType")


def get_provmap_and_fingerprints_from_path(path, fmt_str=".yaml"):
    """
    Get the provenance map and managed fingerprints from a source path.
    """
    destination_path = Path(path)
    assert destination_path.is_dir(), "A directory is required."
    if fmt_str and not fmt_str.startswith("."):
        fmt_str = f".{fmt_str}"
    provenance_map = {}
    fingerprints = []
    for prov_path in destination_path.glob(f"*{fmt_str}"):
        fingerprint = prov_path.name[: -len(fmt_str)]
        fingerprint = fingerprint.rstrip(".")
        provenance_map[fingerprint] = Provenance.load(prov_path)
        fingerprints.append(fingerprint)
    return provenance_map, fingerprints


class Sink(Task, ABC, Generic[DataType]):
    """
    An abstract base class for sinks.
    """

    managed_fingerprints: tuple[str, ...] = Field(default_factory=tuple)
    provenance_map: FrozenDict[str, Provenance] = Field(default_factory=FrozenDict)

    # Methods common to all Sinks.
    def __iter__(self) -> Iterator[tuple[str, Source[DataType]]]:
        """Iterate over (fingerprint, Source) pairs."""
        for fingerprint in self.managed_fingerprints:
            fp = self.get_source(fingerprint)
            yield fingerprint, fp

    def __getitem__(self, id: str | Pipe | int) -> Source[DataType]:
        return self.get_source(self._get_fingerprint(id))

    def __len__(self):
        return len(self.managed_fingerprints)

    def run(self, data: Any, context) -> Any:
        """
        Write the data to storage and create manifest.
        """
        self.put_data(data, context.pipe)
        return data

    @abstractmethod
    def put_data(self, data: DataType, pipe: Pipe, **kwargs) -> Self:
        """
        Write the data contents to storage.

        Parameters
        ----------
        data
            The input data to be saved.
        fingerprint
            The fingerprint of the pipeline that produced the data.
        **kwargs
            extra kwargs are passed to subclass method.
        """

    @abstractmethod
    def get_provenance(self, fingerprint: str, **kwargs) -> Provenance:
        """
        Get the provenance of a specific fingerprint.

        Parameters
        ----------
        fingerprint: str
        """

    # Optional methods.
    def get_content_df(self) -> pd.DataFrame:
        """Get the contents of the in a dataframe."""
        raise NotImplementedError(f"{self.__class__} does not implement get_contents")

    def get_source(self, pipe_or_fingerprint, **kwargs) -> Source[DataType]:
        """Get a source corresponding to a specific pipe from the sink."""
        raise NotImplementedError(f"{self.__class__} does not implement get_source")

    def delete(self, fingerprint: str | None = None) -> Self:
        """Delete contents of the source."""
        raise NotImplementedError(f"{self.__class__} does not implement delete")

    def _get_fingerprint(self, indexer: Pipe | str | int) -> str:
        """Get the fingerprint from a variety of sources."""
        if isinstance(indexer, int):
            msg = f"int indexer not supported by {self.__class__}"
            raise TypeError(msg)
        fp = indexer
        return getattr(fp, "fingerprint", fp)


class FileSystemSink(Sink, Generic[DataType]):
    """
    A sink that uses a file system.

    This has the following structure
    -> destination_path   # The base directory for all data contents
    ---> {fingerprint}.{prov_format} # The provenance for a particular
    ---> {fingerprint}{maybe_extension}  # The data file or directory

    """

    # The attributes to pull out of the stat object.
    _stat_attrs: ClassVar[tuple[str, ...]] = ("st_size", "st_mtime", "st_ctime")
    _df_columns: classmethod[tuple[str, ...]] = (
        *_stat_attrs,
        "file_path",
        "fingerprint",
    )

    destination_path: Path
    # Class variable that subclasses should override
    data_extension: ClassVar[str] = ""
    provenance_format: ClassVar[str] = "yaml"

    # Indicates if the sink data is stored in a single file next to the
    # provenance or in a directory.
    storage_type: Literal["file", "directory"] = "directory"

    @classmethod
    def from_path(cls, path) -> Self:
        """
        Load provenance and fingerprints from an existing destination path.

        All the files on the top level with the provenance_format are
        provenance files, named by fingerprint. This is used to re-create
        the provenance_map and managed_fingerprints tuple.
        """
        path = Path(path)
        provmap, fingerprints = get_provmap_and_fingerprints_from_path(
            path, cls.provenance_format
        )
        return cls(
            destination_path=path,
            provenance_map=provmap,
            managed_fingerprints=tuple(sorted(fingerprints)),
        )

    def get_provenance_path(self, fp_or_pipe) -> Path:
        """Get the path to the manifest file."""
        fp = self._get_fingerprint(fp_or_pipe)
        fmt_str = self.provenance_format
        if fmt_str and not fmt_str.startswith("."):
            fmt_str = f".{fmt_str}"
        return self.destination_path / f"{fp}{fmt_str}"

    def get_provenance(self, fingerprint, **kwargs):
        """Get the provenance for a fingerprint."""
        path = self.get_provenance_path(fingerprint)
        if not path.exists():
            raise FileNotFoundError(f"Provenance not found at {path}")
        return Provenance.load(path)

    @abstractmethod
    def serialize_data(self, data, path):
        """Abstract method for serializing data."""

    def get_file_name_in_directory(self, base_path, data=None):
        """
        Get a file name from data to save.

        By default generates a random name for the file, but can be overridden
        by subclasses.
        """
        filename = f"{uuid.uuid4().hex}"
        extension = f".{self.data_extension}" if self.data_extension else ""
        path = base_path / f"{filename}{extension}"
        return path

    def put_data(self, data: Any, pipe_or_fingerprint, **kwargs):
        """Persist data to the filesystem."""
        fp = self._get_fingerprint(pipe_or_fingerprint)
        data_path = self.get_data_source_path(fp)
        if self.storage_type == "directory":
            data_path.mkdir(parents=True, exist_ok=True)
            path = self.get_file_name_in_directory(data_path, data=data)
        elif self.storage_type == "file":
            path = f"{data_path}.{self.data_extension}"
        self.serialize_data(data, path)
        if fp in self.managed_fingerprints:
            return self
        return self.new(managed_fingerprints=(*self.managed_fingerprints, fp))

    def get_data_source_path(self, pipe_or_fingerprint) -> Path:
        """Get the path to the data source (directory or file)."""
        fingerprint = self._get_fingerprint(pipe_or_fingerprint)
        out = self.destination_path / f"{fingerprint}"
        if self.storage_type == "file":
            out = out / f"{self.data_extension}"
        return out

    def get_source(self, pipe_or_fingerprint, **kwargs) -> SourceType:
        """Get a source corresponding to a specific pipe from the sink."""
        if self.source_type is None:
            raise NotImplementedError(f"Source type not implemented on {self}")
        data_path = self.get_data_source_path(pipe_or_fingerprint)
        provenance_path = self.get_provenance_path(pipe_or_fingerprint)
        provenance = None
        if provenance_path.exists():
            provenance = Provenance.load(provenance_path)
        return self.source_type.from_path(data_path, provenance=provenance, **kwargs)

    @lru_cache
    def get_fingerprints(self) -> frozenset[str]:
        """Return a tuple of fingerprints in managed in the sink."""
        files = self.destination_path.glob(f"*{self.provenance_format}")
        return frozenset(sorted(files))

    def __len__(self) -> int:
        """Return the number of datasets stored."""
        return len(self.get_content_df())

    def get_content_df(self) -> pd.DataFrame:
        """
        Return a dataframe of the directory contents.

        This includes the fingerprint, the file path, and file
        size in bytes. It is sorted by fingerprint.
        """
        data = []
        fmt_str = self.provenance_format
        if fmt_str and not fmt_str.startswith("."):
            fmt_str = f".{fmt_str}"
        provenance_paths = Path(self.destination_path).glob(f"*{fmt_str}")
        for prov_path in provenance_paths:
            fingerprint = prov_path.name[: -len(fmt_str)].rstrip(".")
            data_folder = self.get_data_source_path(fingerprint)
            if not data_folder.exists():
                continue
            pattern = f"*.{self.data_extension}" if self.data_extension else "*"
            for data_file in data_folder.rglob(pattern):
                stats = dict(data_file.stat())
                stats["fingerprint"] = fingerprint
                stats["file_path"] = str(data_file)
                data.append(stats)

        if not data:
            return pd.DataFrame(columns=["fingerprint", "file_path", "size_bytes"])

        df = pd.DataFrame(data)
        return df.sort_values("fingerprint")

    def delete(self, fingerprint: str | None = None) -> None:
        """
        Delete files associated with a fingerprint or the entire directory.

        Parameters
        ----------
        fingerprint
            The fingerprint of the files to delete. If None, deletes the entire
            directory and all its contents.
        """
        if fingerprint is None:
            # Delete entire directory
            if self.destination_path.exists():
                shutil.rmtree(self.destination_path)
                # Recreate the empty directory
                self.destination_path.mkdir(parents=True, exist_ok=True)
        else:
            # Delete specific files for this fingerprint
            data_path = self.get_data_source_path(fingerprint)
            if data_path.exists():
                if data_path.is_dir():
                    shutil.rmtree(data_path)
                else:
                    data_path.unlink()
            self.get_provenance_path(fingerprint).unlink(missing_ok=True)
