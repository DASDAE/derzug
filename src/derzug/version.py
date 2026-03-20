"""Module for reporting versions."""

from __future__ import annotations

from contextlib import suppress
from importlib.metadata import PackageNotFoundError, version

__version__ = "0.0.0"

# try to get version from installed metadata
with suppress(PackageNotFoundError):
    __version__ = version("derzug")

__last_version__ = ".".join(__version__.split(".")[:3])
