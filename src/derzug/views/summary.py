"""Signal summary registrations for DerZug data types."""

from __future__ import annotations

import json
from html import escape

import dascore as dc
from orangewidget.utils.signals import PartialSummary, summarize

from derzug.models.annotations import AnnotationSet
from derzug.models.selection import SelectParams


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
    return _format_model_detail_html(value)


def _format_model_detail_html(value) -> str:
    """Return HTML-safe pretty-printed pydantic model details."""
    text = json.dumps(
        value.model_dump(mode="python"),
        default=_json_default,
        indent=2,
        sort_keys=False,
    )
    return f"<pre style='margin:0; white-space:pre-wrap'>{escape(text)}</pre>"


def _json_default(value: object) -> object:
    """Return a JSON-compatible representation for scalar-ish model values."""
    item = getattr(value, "item", None)
    if callable(item):
        try:
            return item()
        except Exception:
            pass
    return _safe_repr(value)


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


@summarize.register(SelectParams)
def summarize_select_params(value: SelectParams) -> PartialSummary:
    """Summarize public patch.select parameters for Orange signal UI."""
    return PartialSummary(
        summary=f"{len(value.kwargs)} select range(s)",
        details=_format_model_detail_html(value),
    )
