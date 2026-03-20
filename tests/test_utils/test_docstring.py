"""Tests for NumPy-style docstring parsing helpers."""

from __future__ import annotations

from derzug.utils.docstring import parse_numpy_docstring


def test_empty_docstring_returns_empty_model():
    """Blank docstrings should produce empty structured metadata."""
    parsed = parse_numpy_docstring("")

    assert parsed.parameters == {}
    assert parsed.returns == ()
    assert parsed.raises == ()
    assert parsed.warns == ()


def test_parameters_and_returns_are_parsed():
    """Named NumPy sections should yield parameter and return metadata."""
    parsed = parse_numpy_docstring(
        """
        Transform a value.

        Parameters
        ----------
        patch : object
            Input patch.
        scale : float
            Scale factor.

        Returns
        -------
        processed : object
            Output patch.
        """
    )

    assert parsed.parameters == {
        "patch": "Input patch.",
        "scale": "Scale factor.",
    }
    assert len(parsed.returns) == 1
    assert parsed.returns[0].name == "processed"
    assert parsed.returns[0].description == "Output patch."


def test_multiline_descriptions_are_joined():
    """Indented continuation lines should be merged into one description."""
    parsed = parse_numpy_docstring(
        """
        Parameters
        ----------
        patch : object
            First sentence.
            Second sentence.

        Raises
        ------
        ValueError
            First line.
            Second line.
        """
    )

    assert parsed.parameters["patch"] == "First sentence. Second sentence."
    assert parsed.raises[0].description == "First line. Second line."


def test_tuple_return_names_are_preserved():
    """Multiple structured return entries should keep their names and order."""
    parsed = parse_numpy_docstring(
        """
        Returns
        -------
        left : int
            Left result.
        right : int
            Right result.
        """
    )

    assert [item.name for item in parsed.returns] == ["left", "right"]


def test_warns_and_raises_are_independent():
    """Warns and Raises sections should not overwrite each other."""
    parsed = parse_numpy_docstring(
        """
        Raises
        ------
        ValueError
            Hard failure.

        Warns
        -----
        RuntimeWarning
            Soft warning.
        """
    )

    assert parsed.raises[0].name == "ValueError"
    assert parsed.warns[0].name == "RuntimeWarning"


def test_non_numpy_headers_are_ignored():
    """Unsupported docstring layouts should degrade to empty structured output."""
    parsed = parse_numpy_docstring(
        """
        Args:
            patch: Input patch.

        Returns:
            Output patch.
        """
    )

    assert parsed.parameters == {}
    assert parsed.returns == ()


def test_returns_without_explicit_name_are_kept_as_unnamed_entries():
    """Unnamed return entries should preserve their descriptions for fallback use."""
    parsed = parse_numpy_docstring(
        """
        Returns
        -------
        tuple[int, int]
            Pair of results.
        """
    )

    assert len(parsed.returns) == 1
    assert parsed.returns[0].name == ""
    assert parsed.returns[0].description == "Pair of results."
