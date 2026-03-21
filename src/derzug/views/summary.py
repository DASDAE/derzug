"""Signal summary registrations for DerZug data types."""

from __future__ import annotations

import json
from html import escape

import dascore as dc
from orangewidget.utils.signals import PartialSummary, summarize

from derzug.models.annotations import AnnotationSet


def _safe_repr(value: object) -> str:
    """Return a robust ``repr`` for summary details."""
    try:
        return repr(value)
    except Exception:  # pragma: no cover - defensive fallback
        return f"<{type(value).__name__}>"


def _format_detail_html(value: object) -> str:
    """Return HTML-safe detail text that preserves newlines and indentation."""
    return (
        f"<pre style='margin:0; white-space:pre-wrap'>{escape(_safe_repr(value))}</pre>"
    )


def _format_annotation_set_detail_html(value: AnnotationSet) -> str:
    """Return HTML-safe pretty-printed AnnotationSet details."""
    text = json.dumps(value.model_dump(mode="json"), indent=2, sort_keys=False)
    return f"<pre style='margin:0; white-space:pre-wrap'>{escape(text)}</pre>"


@summarize.register(dc.BaseSpool)
def summarize_spool(value: dc.BaseSpool) -> PartialSummary:
    """Summarize DASCore spool-like values for Orange signal UI."""
    return PartialSummary(summary="Spool", details=_format_detail_html(value))


@summarize.register(dc.Patch)
def summarize_patch(value: dc.Patch) -> PartialSummary:
    """Summarize DASCore patch values for Orange signal UI."""
    return PartialSummary(summary="Patch", details=_format_detail_html(value))


@summarize.register(AnnotationSet)
def summarize_annotation_set(value: AnnotationSet) -> PartialSummary:
    """Summarize persisted annotation-set values for Orange signal UI."""
    return PartialSummary(
        summary="Annotations",
        details=_format_annotation_set_detail_html(value),
    )
