"""Tests for DerZug signal summaries."""

from __future__ import annotations

import dascore as dc
from derzug.models.annotations import Annotation, AnnotationSet, PointGeometry
from derzug.views.summary import (
    _format_detail_html,
    summarize_annotation_set,
    summarize_patch,
    summarize_spool,
)


class _ReprValue:
    """A test helper with a multiline repr containing HTML-like characters."""

    def __repr__(self) -> str:
        return "line 1\n  <tag>\nline & 3"


def test_format_detail_html_preserves_newlines_and_escapes_html():
    """Summary detail HTML should preserve formatting and escape markup."""
    out = _format_detail_html(_ReprValue())
    assert out.startswith("<pre")
    assert "white-space:pre-wrap" in out
    assert "line 1\n  &lt;tag&gt;\nline &amp; 3" in out


def test_summarize_patch_uses_formatted_html_details():
    """Patch summaries should provide HTML-safe multiline details."""
    patch = dc.get_example_patch("example_event_2")
    out = summarize_patch(patch)
    assert out.summary == "Patch"
    assert out.details is not None
    assert out.details.startswith("<pre")
    assert "white-space:pre-wrap" in out.details


def test_summarize_spool_uses_formatted_html_details():
    """Spool summaries should provide HTML-safe multiline details."""
    spool = dc.get_example_spool("random_das")
    out = summarize_spool(spool)
    assert out.summary == "Spool"
    assert out.details is not None
    assert out.details.startswith("<pre")
    assert "white-space:pre-wrap" in out.details


def test_summarize_annotation_set_uses_formatted_html_details():
    """AnnotationSet summaries should provide HTML-safe pretty-printed details."""
    ann_set = AnnotationSet(
        dims=("time",),
        annotations=(
            Annotation(
                id="a",
                geometry=PointGeometry(coords={"time": 1.0}),
            ),
        ),
    )

    out = summarize_annotation_set(ann_set)

    assert out.summary == "Annotations"
    assert out.details is not None
    assert out.details.startswith("<pre")
    assert "&quot;schema_version&quot;: &quot;3&quot;" in out.details
    assert "&quot;dims&quot;: [" in out.details
    assert "\n  &quot;annotations&quot;: [" in out.details
    assert "&quot;id&quot;: &quot;a&quot;" in out.details
