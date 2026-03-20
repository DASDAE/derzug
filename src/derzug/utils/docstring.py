"""Helpers for parsing structured NumPy-style docstrings."""

from __future__ import annotations

import inspect

from pydantic import BaseModel, Field


class ParsedDocEntry(BaseModel):
    """One parsed item from a structured docstring section."""

    name: str = ""
    description: str = ""


class ParsedNumpyDocstring(BaseModel):
    """Structured subset of a NumPy-style docstring."""

    parameters: dict[str, str] = Field(default_factory=dict)
    returns: tuple[ParsedDocEntry, ...] = ()
    raises: tuple[ParsedDocEntry, ...] = ()
    warns: tuple[ParsedDocEntry, ...] = ()


_DOC_SECTION_NAMES: dict[str, str] = {
    "parameters": "parameters",
    "returns": "returns",
    "raises": "raises",
    "warns": "warns",
}


def parse_numpy_docstring(docstring: str) -> ParsedNumpyDocstring:
    """Return a small structured view of a NumPy-style docstring."""
    sections = {value: [] for value in _DOC_SECTION_NAMES.values()}
    if not docstring:
        return ParsedNumpyDocstring()

    lines = inspect.cleandoc(docstring).splitlines()
    current_section: str | None = None
    index = 0
    while index < len(lines):
        line = lines[index].rstrip()
        section_key = _DOC_SECTION_NAMES.get(line.strip().lower())
        if (
            section_key is not None
            and index + 1 < len(lines)
            and _is_section_underline(lines[index + 1])
        ):
            current_section = section_key
            index += 2
            continue
        if current_section is not None:
            sections[current_section].append(line)
        index += 1

    return ParsedNumpyDocstring(
        parameters=_parse_parameters_section(sections["parameters"]),
        returns=_parse_returns_section(sections["returns"]),
        raises=_parse_issue_section(sections["raises"]),
        warns=_parse_issue_section(sections["warns"]),
    )


def _is_section_underline(text: str) -> bool:
    """Return True when one docstring line is a section underline."""
    stripped = text.strip()
    return bool(stripped) and set(stripped) == {"-"}


def _parse_parameters_section(lines: list[str]) -> dict[str, str]:
    """Parse one NumPy-style Parameters section into name/description pairs."""
    output: dict[str, str] = {}
    for entry in _parse_doc_entries(lines):
        if entry.name:
            output[entry.name] = entry.description
    return output


def _parse_returns_section(lines: list[str]) -> tuple[ParsedDocEntry, ...]:
    """Parse one NumPy-style Returns section into named entries."""
    return _parse_doc_entries(lines, allow_unnamed=True)


def _parse_issue_section(lines: list[str]) -> tuple[ParsedDocEntry, ...]:
    """Parse one NumPy-style Raises/Warns section into named entries."""
    return _parse_doc_entries(lines)


def _parse_doc_entries(
    lines: list[str],
    *,
    allow_unnamed: bool = False,
) -> tuple[ParsedDocEntry, ...]:
    """Parse a simple NumPy-style section block into entries."""
    entries: list[ParsedDocEntry] = []
    current_name: str | None = None
    current_description: list[str] = []

    for raw_line in lines:
        if not raw_line.strip():
            if current_name is not None:
                current_description.append("")
            continue

        if not raw_line.startswith(" "):
            if current_name is not None:
                entries.append(
                    ParsedDocEntry(
                        name=current_name,
                        description=_join_description_lines(current_description),
                    )
                )
            current_name = _parse_entry_name(raw_line, allow_unnamed=allow_unnamed)
            current_description = []
            continue

        if current_name is not None:
            current_description.append(raw_line.strip())

    if current_name is not None:
        entries.append(
            ParsedDocEntry(
                name=current_name,
                description=_join_description_lines(current_description),
            )
        )
    return tuple(entries)


def _parse_entry_name(line: str, *, allow_unnamed: bool) -> str:
    """Extract one entry name from a section heading line."""
    head = line.strip()
    if " : " in head:
        return head.split(" : ", maxsplit=1)[0].strip()
    if ":" in head:
        return head.split(":", maxsplit=1)[0].strip()
    if allow_unnamed and " " not in head and "." not in head and head[:1].islower():
        return head
    if allow_unnamed:
        return ""
    return head


def _join_description_lines(lines: list[str]) -> str:
    """Return one compact prose string from docstring description lines."""
    if not lines:
        return ""
    return " ".join(part for part in lines if part).strip()
