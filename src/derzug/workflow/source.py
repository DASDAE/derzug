"""
A source is an iterable a pipe consumes (with metadata).
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from collections.abc import Iterator
from typing import TypeVar

from .model import WorkflowModel
from .provenance import Provenance

DataType = TypeVar("DataType")


class Source[DataType](WorkflowModel, ABC):
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
