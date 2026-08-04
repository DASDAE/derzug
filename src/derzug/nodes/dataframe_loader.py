"""The DataFrameLoader node: read a tabular file into a pandas DataFrame.

The format registry lives here rather than beside the file picker so a saved
workflow can resolve and read its own source with no UI attached.
"""

from __future__ import annotations

from pathlib import Path
from typing import ClassVar

import pandas as pd
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.utils.optional_imports import optional_import
from derzug.workflow.task import Task

# Display name → (reader callable, accepted extensions)
FORMATS: dict[str, tuple[object, tuple[str, ...]]] = {
    "CSV": (pd.read_csv, (".csv", ".tsv", ".txt")),
    "DuckDB": (None, (".duckdb",)),
    "Excel": (pd.read_excel, (".xlsx", ".xls", ".xlsm", ".xlsb", ".ods")),
    "Feather": (pd.read_feather, (".feather",)),
    "HDF5": (pd.read_hdf, (".h5", ".hdf5", ".hdf")),
    "JSON": (pd.read_json, (".json",)),
    "ORC": (pd.read_orc, (".orc",)),
    "Parquet": (pd.read_parquet, (".parquet", ".pq")),
    "Pickle": (pd.read_pickle, (".pkl", ".pickle")),
    "SPSS": (pd.read_spss, (".sav", ".zsav")),
    "Stata": (pd.read_stata, (".dta",)),
}

AUTO_FORMAT = "Auto"
FORMAT_NAMES = [AUTO_FORMAT, *sorted(FORMATS)]

# Extension → format name, for auto-detection
_EXT_TO_FORMAT: dict[str, str] = {
    ext: name for name, (_, exts) in FORMATS.items() for ext in exts
}


def detect_format(path: str) -> str | None:
    """Return the format name matching the file extension, or None."""
    return _EXT_TO_FORMAT.get(Path(path).suffix.lower())


def _quote_sql_identifier(name: str) -> str:
    """Return one SQL identifier quoted for direct interpolation."""
    return f'"{name.replace(chr(34), chr(34) * 2)}"'


def list_duckdb_tables(path: str) -> list[str]:
    """Return sorted user table names from one DuckDB database file."""
    duckdb = optional_import("duckdb")

    with duckdb.connect(path, read_only=True) as con:
        rows = con.execute(
            """
            SELECT DISTINCT table_name
            FROM information_schema.tables
            WHERE table_schema NOT IN ('information_schema', 'pg_catalog')
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """
        ).fetchall()
    return [str(name) for (name,) in rows]


def _resolve_duckdb_table(path: str, table_name: str) -> str:
    """Return a valid DuckDB table name, defaulting to the first sorted table."""
    tables = list_duckdb_tables(path)
    if not tables:
        raise ValueError("DuckDB file contains no user tables.")
    chosen = table_name.strip()
    if chosen in tables:
        return chosen
    return tables[0]


def _read_duckdb_table(path: str, table_name: str) -> tuple[pd.DataFrame, str]:
    """Read one DuckDB table into a pandas DataFrame and return the resolved name."""
    duckdb = optional_import("duckdb")

    resolved = _resolve_duckdb_table(path, table_name)
    query = f"SELECT * FROM {_quote_sql_identifier(resolved)}"
    with duckdb.connect(path, read_only=True) as con:
        df = con.execute(query).fetch_df()
    return df, resolved


class DataFrameLoaderTask(Task):
    """Portable DataFrame loader used for compiled bound-source execution."""

    output_variables: ClassVar[dict[str, object]] = {"data": object}

    file_path: str = ""
    format_name: str = AUTO_FORMAT
    table_name: str = ""

    def run(self):
        """Load the configured DataFrame and return it."""
        path = self.file_path.strip()
        if not path:
            return None
        format_name = self.format_name or AUTO_FORMAT
        if format_name == AUTO_FORMAT:
            detected = detect_format(path)
            if detected is None:
                suffix = Path(path).suffix or "(no extension)"
                raise ValueError(
                    "Cannot auto-detect format for "
                    f"'{suffix}'. Select a format explicitly."
                )
            format_name = detected
        if format_name == "DuckDB":
            df, _ = _read_duckdb_table(path, self.table_name)
            return df
        reader, _ = FORMATS[format_name]
        df = reader(path)
        if not isinstance(df, pd.DataFrame):
            raise TypeError(f"Reader returned {type(df).__name__}, expected DataFrame.")
        return df


class DataFrameLoaderParams(BaseModel):
    """Parameters for the DataFrame Loader node."""

    file_path: str = ""
    format_name: str = "Auto"
    table_name: str = ""


def dataframe_loader_task_from_params(
    params: DataFrameLoaderParams | None = None,
) -> DataFrameLoaderTask:
    """Build the configured DataFrame-loading source task."""
    params = DataFrameLoaderParams() if params is None else params
    return DataFrameLoaderTask(
        file_path=str(params.file_path or ""),
        format_name=str(params.format_name or AUTO_FORMAT),
        table_name=str(params.table_name or ""),
    )


NODE_SPEC = NodeSpec(
    name="DataFrame Loader",
    widget_qualified_name="derzug.widgets.dataframe_loader.DataFrameLoader",
    outputs=(PortSpec(name="data", display_name="Data", type=pd.DataFrame),),
    params_model=DataFrameLoaderParams,
    task_factory=dataframe_loader_task_from_params,
    is_source=True,
    category="IO",
    description=(
        "Load a tabular DataFrame from a file. "
        "Format is auto-detected from the file extension or can be set manually."
    ),
    keywords=("dataframe", "csv", "parquet", "excel", "table", "file", "load"),
    icon="icons/DataFrame.svg",
    priority=20,
)
