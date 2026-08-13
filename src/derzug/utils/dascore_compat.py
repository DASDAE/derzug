"""Version-independent accessors for the DASCore APIs DerZug depends on.

DASCore collapsed its spool class hierarchy into a single concrete ``dc.Spool``
and renamed several ``get_contents()`` columns. DerZug supports the DASCore
releases on either side of that change, so everything it needs to know about a
spool's backing store and its contents table is answered here -- through
duck-typed public accessors rather than ``isinstance`` checks against classes
that exist in only one version.
"""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path

import dascore as dc
import pandas as pd

from derzug.utils.spool import normalize_dims_value

#: ``get_contents()`` column naming each patch's source file, newest name
#: first. DASCore renamed ``path`` to ``source_path``.
_PATH_COLUMNS = ("source_path", "path")

#: Contents columns recording where a patch came from rather than what it
#: holds. DASCore keeps them for its own bookkeeping and rejects them as
#: select keys.
_SOURCE_COLUMNS = frozenset(_PATH_COLUMNS) | {
    "dims",
    "history",
    "patch",
    "file_format",
    "file_version",
    "source_format",
    "source_version",
    "source_patch_id",
}

#: Suffixes DASCore appends when it flattens a coordinate into contents
#: columns. ``distance_min`` describes the distance coordinate rather than
#: naming something selectable -- ``distance`` is the select key.
_COORD_COLUMN_SUFFIXES = ("min", "max", "step", "units", "dtype")


def contents_path_column(df: pd.DataFrame) -> str | None:
    """Return the contents column naming each row's source file.

    Parameters
    ----------
    df
        A spool contents table from :meth:`dascore.BaseSpool.get_contents`.

    Returns
    -------
    The column name, or None when the contents carry no source paths.
    """
    for name in _PATH_COLUMNS:
        if name in df.columns:
            return name
    return None


def contents_dims(df: pd.DataFrame) -> list[str]:
    """Return every dimension named by a contents table, in first-seen order.

    Parameters
    ----------
    df
        A spool contents table from :meth:`dascore.BaseSpool.get_contents`.
    """
    if "dims" not in df.columns:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for value in df["dims"]:
        for dim in normalize_dims_value(value):
            if dim not in seen:
                seen.add(dim)
                out.append(dim)
    return out


def contents_coord_names(df: pd.DataFrame) -> set[str]:
    """Return every coordinate a contents table summarizes.

    A coordinate is flattened into ``<name>_min``/``<name>_max`` columns
    whether or not it is a dimension, so this covers auxiliary coordinates
    (latitude, longitude, ...) that ``dims`` never names.

    Parameters
    ----------
    df
        A spool contents table from :meth:`dascore.BaseSpool.get_contents`.
    """
    columns = {str(column) for column in df.columns}
    summarized = {
        column.removesuffix("_min")
        for column in columns
        if column.endswith("_min") and f"{column.removesuffix('_min')}_max" in columns
    }
    return summarized | set(contents_dims(df))


def selectable_contents_keys(
    df: pd.DataFrame,
    columns: Iterable[str] | None = None,
) -> tuple[str, ...]:
    """Return the names a spool's contents offer as ``Spool.select`` keys.

    Newer DASCore validates select names against the spool's attributes and
    coordinates, so the flattened coordinate columns and source bookkeeping
    it also publishes in ``get_contents()`` are not offerable.

    Parameters
    ----------
    df
        A spool contents table from :meth:`dascore.BaseSpool.get_contents`.
    columns
        Candidate column names, defaulting to every column in ``df``. Use it
        to restrict the result to columns the caller already displays.

    Returns
    -------
    Each coordinate, plus the metadata columns naming a patch attribute rather
    than describing a coordinate or a source file, sorted case-insensitively.
    """
    coords = contents_coord_names(df)
    derived = {
        f"{coord}_{suffix}" for coord in coords for suffix in _COORD_COLUMN_SUFFIXES
    }
    candidates = df.columns if columns is None else columns
    keys = {
        str(column)
        for column in candidates
        if not str(column).startswith("_")
        and column not in _SOURCE_COLUMNS
        and column not in derived
    }
    return tuple(sorted(keys | coords, key=str.casefold))


def spool_source_path(spool: dc.BaseSpool) -> Path | None:
    """Return the directory or file one spool reads from.

    Parameters
    ----------
    spool
        Any spool; in-memory spools have no source path.

    Returns
    -------
    The backing path, or None for a spool with no file source.
    """
    if hasattr(spool, "spool_path"):
        # Newer DASCore answers this for every spool, including in-memory
        # ones (as None); an older one answers only for directory spools.
        path = spool.spool_path
    else:
        path = _single_source_path(spool)
    return None if path is None else Path(path)


def is_directory_spool(spool: dc.BaseSpool) -> bool:
    """Return True when a spool indexes a directory of files.

    Both DASCore layouts hand a directory spool -- and only a directory
    spool -- an indexer, so this stays correct while the directory is
    unreadable or temporarily missing.
    """
    return getattr(spool, "indexer", None) is not None


def is_file_spool(spool: dc.BaseSpool) -> bool:
    """Return True when a spool reads from a single file."""
    return not is_directory_spool(spool) and spool_source_path(spool) is not None


def _single_source_path(spool: dc.BaseSpool) -> str | None:
    """Return the lone source file in a spool's contents, if there is one.

    Older DASCore file spools expose their path only through their contents
    table, where an ordinary patch attribute named ``path`` looks the same.
    Requiring a readable file tells the two apart: a file spool cannot be
    built from a path that does not exist.
    """
    get_contents = getattr(spool, "get_contents", None)
    if not callable(get_contents):
        return None
    try:
        df = get_contents()
    except Exception:
        return None
    column = contents_path_column(df)
    if column is None:
        return None
    values = df[column].dropna()
    paths = {str(value).strip() for value in values if str(value).strip()}
    if len(paths) != 1:
        return None
    path = paths.pop()
    return path if Path(path).is_file() else None
