"""Parse and compare pytest-codspeed walltime benchmark results.

This module is deliberately dependency-free (standard library only) so it can
be imported and unit-tested without pulling in Qt, NumPy, or pytest. The
subprocess and git orchestration that feeds it lives in
``scripts/bench_compare.py``.

The statistics choice matters. ``min_ns`` is the minimum of ``rounds``
samples, and pytest-codspeed picks the round count adaptively against a time
budget: a slower build gets fewer rounds, so its minimum is drawn from a
smaller sample and is biased upward. That bias amplifies apparent
regressions. ``median_ns`` is therefore the primary comparator and ``min_ns``
only corroborates it, with a change reported only when both agree.
"""

from __future__ import annotations

import json
import math
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

__all__ = [
    "BenchDelta",
    "BenchStat",
    "Comparison",
    "combine_comparisons",
    "compare_benchmarks",
    "compare_environments",
    "format_comparison",
    "has_regression",
    "load_walltime_results",
    "newest_results_file",
    "normalize_uri",
    "parse_walltime_results",
]

#: Default fraction a benchmark must move before it is called a change.
DEFAULT_THRESHOLD = 0.20

#: Benchmarks faster than this are reported but never counted as regressions;
#: below roughly this duration a walltime swing is timer and scheduler noise.
DEFAULT_NOISE_FLOOR_NS = 50_000.0

#: Maximum baseline stdev/median ratio for a comparison to be trusted.
DEFAULT_MAX_REL_STDEV = 0.10

#: Fraction the control benchmark may move before the whole run is suspect.
DEFAULT_CONTROL_TOLERANCE = 0.10

#: Test id of the fixed-work control benchmark.
CONTROL_KEY = (
    "benchmarks/core/test_control_benchmarks.py::"
    "TestControlBenchmarks::test_fixed_python_work"
)

REGRESSED = "regressed"
IMPROVED = "improved"
UNCHANGED = "unchanged"
NOISY = "noisy"


@dataclass(frozen=True)
class BenchStat:
    """One benchmark's walltime statistics from a CodSpeed results file."""

    key: str
    name: str
    min_ns: float
    median_ns: float
    mean_ns: float
    stdev_ns: float
    rounds: int
    iqr_outlier_rounds: int = 0
    stdev_outlier_rounds: int = 0

    @property
    def rel_stdev(self) -> float:
        """Return the standard deviation as a fraction of the median."""
        if self.median_ns <= 0:
            return 0.0
        return self.stdev_ns / self.median_ns


@dataclass(frozen=True)
class BenchDelta:
    """Baseline-to-head change for one benchmark."""

    key: str
    baseline: BenchStat
    head: BenchStat
    median_ratio: float
    min_ratio: float
    verdict: str
    note: str = ""


@dataclass(frozen=True)
class Comparison:
    """A full baseline-to-head comparison, ranked worst-first."""

    deltas: tuple[BenchDelta, ...]
    added: tuple[str, ...]
    removed: tuple[str, ...]
    warnings: tuple[str, ...]
    control: BenchDelta | None
    trustworthy: bool

    @property
    def regressions(self) -> tuple[BenchDelta, ...]:
        """Return the deltas classified as regressions."""
        return tuple(d for d in self.deltas if d.verdict == REGRESSED)

    @property
    def improvements(self) -> tuple[BenchDelta, ...]:
        """Return the deltas classified as improvements."""
        return tuple(d for d in self.deltas if d.verdict == IMPROVED)


def normalize_uri(uri: str, *, anchor: str = "benchmarks/") -> str:
    """Return a path-prefix-independent key for one benchmark uri.

    Baseline and head run from different working trees, so their uris may
    carry different absolute prefixes. Everything from ``anchor`` onward is
    the stable part.

    Parameters
    ----------
    uri
        The ``path::class::test`` identifier from a results file.
    anchor
        Path fragment that begins the portable part of the uri.

    Returns
    -------
    str
        The uri truncated to start at ``anchor``, or unchanged when the
        anchor is absent.

    Examples
    --------
    >>> normalize_uri("/tmp/wt/benchmarks/core/test_a.py::test_b")
    'benchmarks/core/test_a.py::test_b'
    """
    normalized = uri.replace("\\", "/")
    index = normalized.find(anchor)
    if index == -1:
        return normalized
    return normalized[index:]


def _positive(value: Any, field: str) -> float:
    """Return a finite, strictly positive float or raise.

    A zero or non-finite duration would make every ratio meaningless -- a
    zero baseline divides into "unchanged" no matter how slow head is -- so
    it is rejected at the boundary rather than propagated.
    """
    number = float(value)
    if not math.isfinite(number) or number <= 0:
        raise ValueError(f"{field} must be a finite positive duration, got {value!r}")
    return number


def _non_negative(value: Any, field: str) -> float:
    """Return a finite, non-negative float or raise."""
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError(f"{field} must be finite and non-negative, got {value!r}")
    return number


def parse_walltime_results(payload: Mapping[str, Any]) -> dict[str, BenchStat]:
    """Convert one parsed results document into keyed statistics.

    Parameters
    ----------
    payload
        The decoded contents of a ``.codspeed/results_*.json`` file.

    Returns
    -------
    dict
        Mapping of normalized uri to :class:`BenchStat`.

    Raises
    ------
    ValueError
        If the document is not walltime-instrumented or its schema is
        unrecognised. Failing loudly here is deliberate: a silent zero would
        be read as a spectacular performance win.
    """
    instrument = payload.get("instrument")
    if not isinstance(instrument, Mapping):
        raise ValueError("results file has no 'instrument' section")
    kind = instrument.get("type")
    if kind != "walltime":
        raise ValueError(
            f"expected walltime results, got {kind!r}; "
            "comparison only supports walltime mode"
        )
    benchmarks = payload.get("benchmarks")
    if not isinstance(benchmarks, list):
        raise ValueError("results file has no 'benchmarks' list")
    if not benchmarks:
        raise ValueError("results file contains no benchmarks")

    out: dict[str, BenchStat] = {}
    for entry in benchmarks:
        try:
            uri = entry["uri"]
            stats = entry["stats"]
            stat = BenchStat(
                key=normalize_uri(uri),
                name=entry.get("name", uri),
                min_ns=_positive(stats["min_ns"], "min_ns"),
                median_ns=_positive(stats["median_ns"], "median_ns"),
                mean_ns=_positive(stats["mean_ns"], "mean_ns"),
                stdev_ns=_non_negative(stats["stdev_ns"], "stdev_ns"),
                rounds=int(stats["rounds"]),
                iqr_outlier_rounds=int(stats.get("iqr_outlier_rounds", 0)),
                stdev_outlier_rounds=int(stats.get("stdev_outlier_rounds", 0)),
            )
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError(f"unrecognised benchmark entry schema: {error}") from error
        out[stat.key] = stat
    return out


def load_walltime_results(path: str | Path) -> dict[str, BenchStat]:
    """Read and parse one ``.codspeed/results_*.json`` file."""
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return parse_walltime_results(payload)


def newest_results_file(
    directory: str | Path,
    *,
    exclude: Collection[Path] = (),
) -> Path:
    """Return the most recent ``results_*.json`` in a ``.codspeed`` directory.

    Parameters
    ----------
    directory
        The ``.codspeed`` directory to search.
    exclude
        Files to ignore, typically a snapshot taken before the run so the
        newly written file can be identified unambiguously.

    Raises
    ------
    FileNotFoundError
        When no candidate file remains.
    """
    root = Path(directory)
    skip = {Path(item).resolve() for item in exclude}
    candidates = [
        path for path in root.glob("results_*.json") if path.resolve() not in skip
    ]
    if not candidates:
        raise FileNotFoundError(f"no new results_*.json found in {root}")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def _ratio(baseline: float, head: float) -> float:
    """Return the fractional change from baseline to head."""
    if baseline <= 0:
        return 0.0
    return head / baseline - 1.0


def _classify(
    baseline: BenchStat,
    head: BenchStat,
    *,
    threshold: float,
    noise_floor_ns: float,
    max_rel_stdev: float,
) -> tuple[str, str]:
    """Return the verdict and an explanatory note for one benchmark pair."""
    if baseline.median_ns < noise_floor_ns:
        return NOISY, "below noise floor"
    if baseline.rel_stdev > max_rel_stdev:
        return NOISY, f"baseline rel stdev {baseline.rel_stdev:.0%}"

    median_ratio = _ratio(baseline.median_ns, head.median_ns)
    min_ratio = _ratio(baseline.min_ns, head.min_ns)
    note = ""
    if baseline.rounds and head.rounds:
        spread = max(baseline.rounds, head.rounds) / min(baseline.rounds, head.rounds)
        if spread > 2:
            note = f"round counts differ {baseline.rounds} vs {head.rounds}"

    if median_ratio > threshold and min_ratio > threshold:
        return REGRESSED, note
    if median_ratio < -threshold and min_ratio < -threshold:
        return IMPROVED, note
    if (median_ratio > threshold) != (min_ratio > threshold):
        return UNCHANGED, note or "median and min disagree"
    return UNCHANGED, note


def compare_benchmarks(
    baseline: Mapping[str, BenchStat],
    head: Mapping[str, BenchStat],
    *,
    threshold: float = DEFAULT_THRESHOLD,
    noise_floor_ns: float = DEFAULT_NOISE_FLOOR_NS,
    max_rel_stdev: float = DEFAULT_MAX_REL_STDEV,
    control_key: str | None = CONTROL_KEY,
    control_tolerance: float = DEFAULT_CONTROL_TOLERANCE,
) -> Comparison:
    """Join two benchmark result sets and classify every shared benchmark.

    Parameters
    ----------
    baseline, head
        Keyed statistics as returned by :func:`parse_walltime_results`.
    threshold
        Fractional change required in both median and min before a benchmark
        is called changed.
    noise_floor_ns
        Benchmarks whose baseline median is faster than this are marked
        ``noisy`` and never counted as regressions.
    max_rel_stdev
        Baselines jitterier than this are marked ``noisy``.
    control_key
        Key of the fixed-work control benchmark, or None to skip the check.
    control_tolerance
        How far the control may move before the run is declared untrustworthy.

    Returns
    -------
    Comparison
        Deltas ranked worst-first, plus added/removed keys and warnings.
    """
    shared = sorted(set(baseline) & set(head))
    added = tuple(sorted(set(head) - set(baseline)))
    removed = tuple(sorted(set(baseline) - set(head)))

    deltas: list[BenchDelta] = []
    control: BenchDelta | None = None
    for key in shared:
        base_stat, head_stat = baseline[key], head[key]
        verdict, note = _classify(
            base_stat,
            head_stat,
            threshold=threshold,
            noise_floor_ns=noise_floor_ns,
            max_rel_stdev=max_rel_stdev,
        )
        delta = BenchDelta(
            key=key,
            baseline=base_stat,
            head=head_stat,
            median_ratio=_ratio(base_stat.median_ns, head_stat.median_ns),
            min_ratio=_ratio(base_stat.min_ns, head_stat.min_ns),
            verdict=verdict,
            note=note,
        )
        if control_key is not None and key == control_key:
            control = delta
        else:
            deltas.append(delta)

    warnings: list[str] = []
    trustworthy = True
    if control is not None and abs(control.median_ratio) > control_tolerance:
        trustworthy = False
        warnings.append(
            f"control benchmark moved {control.median_ratio:+.1%} "
            f"(tolerance {control_tolerance:.0%}); the machine drifted during "
            "the run, so every verdict below is only a hint"
        )
    elif control is None and control_key is not None:
        trustworthy = False
        warnings.append(
            "control benchmark missing; measurement drift cannot be detected"
        )
    # Both sides run the same benchmark files, so a key present on only one
    # side means a run was partial or skipped differently -- not a real
    # comparison. Saying "no regression" there would be a dangerous lie.
    if added:
        trustworthy = False
        warnings.append(f"{len(added)} benchmark(s) only present in head")
    if removed:
        trustworthy = False
        warnings.append(f"{len(removed)} benchmark(s) only present in baseline")
    if not deltas:
        trustworthy = False
        warnings.append("no benchmarks were comparable between the two runs")

    deltas.sort(key=lambda item: item.median_ratio, reverse=True)
    return Comparison(
        deltas=tuple(deltas),
        added=added,
        removed=removed,
        warnings=tuple(warnings),
        control=control,
        trustworthy=trustworthy,
    )


def combine_comparisons(comparisons: Collection[Comparison]) -> Comparison:
    """Reduce several interleaved pass comparisons to one conservative result.

    Each comparison must come from a *paired* baseline and head pass, so that
    machine drift affects both sides of the ratio alike. For every benchmark
    the least alarming delta wins, which means a regression is only reported
    when it reproduced in every pass. Merging the raw statistics instead --
    say, the best median per side across all passes -- would pair a baseline
    from one pass with a head from another and invent or hide changes.

    Parameters
    ----------
    comparisons
        One comparison per interleaved pass pair, in run order.

    Returns
    -------
    Comparison
        Deltas ranked worst-first, trustworthy only if every input was.
    """
    items = list(comparisons)
    if not items:
        raise ValueError("cannot combine an empty set of comparisons")
    if len(items) == 1:
        return items[0]

    best: dict[str, BenchDelta] = {}
    for comparison in items:
        for delta in comparison.deltas:
            current = best.get(delta.key)
            if current is None or abs(delta.median_ratio) < abs(current.median_ratio):
                best[delta.key] = delta

    warnings: list[str] = []
    for index, comparison in enumerate(items, start=1):
        warnings.extend(f"pass {index}: {text}" for text in comparison.warnings)

    # Report the *worst* control across passes, so the headline number agrees
    # with the trustworthy flag rather than contradicting it.
    controls = [item.control for item in items if item.control is not None]
    worst_control = (
        max(controls, key=lambda item: abs(item.median_ratio)) if controls else None
    )

    deltas = sorted(best.values(), key=lambda item: item.median_ratio, reverse=True)
    return Comparison(
        deltas=tuple(deltas),
        added=tuple(sorted({key for item in items for key in item.added})),
        removed=tuple(sorted({key for item in items for key in item.removed})),
        warnings=tuple(warnings),
        control=worst_control,
        trustworthy=all(item.trustworthy for item in items),
    )


def compare_environments(
    baseline: Mapping[str, str],
    head: Mapping[str, str],
    *,
    ignore: Collection[str] = ("derzug",),
) -> tuple[str, ...]:
    """Return warnings for dependency drift between two environments.

    Any difference -- a version mismatch, or a package installed on only one
    side -- means the two runs differ by more than DerZug's source. A
    one-sided package matters as much as a version bump: an auto-loaded
    pytest plugin present in only one environment changes what runs.
    """
    skipped = {name.lower() for name in ignore}
    warnings = []
    for name in sorted(set(baseline) & set(head)):
        if name.lower() in skipped:
            continue
        if baseline[name] != head[name]:
            warnings.append(
                f"dependency drift: {name} {baseline[name]} (baseline) "
                f"vs {head[name]} (head)"
            )
    for name in sorted(set(baseline) - set(head)):
        if name.lower() not in skipped:
            warnings.append(f"dependency drift: {name} installed in baseline only")
    for name in sorted(set(head) - set(baseline)):
        if name.lower() not in skipped:
            warnings.append(f"dependency drift: {name} installed in head only")
    return tuple(warnings)


def _format_ns(value: float) -> str:
    """Return a compact human-readable duration for a nanosecond count."""
    if value >= 1e9:
        return f"{value / 1e9:.2f}s"
    if value >= 1e6:
        return f"{value / 1e6:.2f}ms"
    if value >= 1e3:
        return f"{value / 1e3:.1f}us"
    return f"{value:.0f}ns"


_MARKERS = {
    REGRESSED: "SLOWER",
    IMPROVED: "FASTER",
    UNCHANGED: "  --  ",
    NOISY: "noisy ",
}


def format_comparison(
    comparison: Comparison,
    *,
    threshold: float = DEFAULT_THRESHOLD,
    width: int = 100,
) -> str:
    """Render one comparison as a fixed-width table, worst regression first."""
    name_width = max(width - 46, 20)
    lines: list[str] = []
    header = (
        f"{'benchmark':<{name_width}} {'baseline':>10} {'head':>10} "
        f"{'median':>9} {'min':>9} status"
    )
    lines.append(header)
    lines.append("-" * len(header))

    for delta in comparison.deltas:
        key = delta.key
        if len(key) > name_width:
            key = "..." + key[-(name_width - 3) :]
        lines.append(
            f"{key:<{name_width}} "
            f"{_format_ns(delta.baseline.median_ns):>10} "
            f"{_format_ns(delta.head.median_ns):>10} "
            f"{delta.median_ratio:>+8.1%} "
            f"{delta.min_ratio:>+8.1%} "
            f"{_MARKERS[delta.verdict]}" + (f"  ({delta.note})" if delta.note else "")
        )

    if comparison.control is not None:
        lines.append("")
        lines.append(
            f"control: {comparison.control.median_ratio:+.1%} "
            f"({'ok' if comparison.trustworthy else 'DRIFTED'})"
        )

    for key in comparison.added:
        lines.append(f"added (head only):     {key}")
    for key in comparison.removed:
        lines.append(f"removed (baseline only): {key}")

    if comparison.warnings:
        lines.append("")
        for warning in comparison.warnings:
            lines.append(f"warning: {warning}")

    regressions = comparison.regressions
    improvements = comparison.improvements
    lines.append("")
    lines.append(
        f"threshold {threshold:.0%}: "
        f"{len(regressions)} slower, {len(improvements)} faster, "
        f"{len(comparison.deltas)} compared"
    )
    return "\n".join(lines)


def has_regression(comparison: Comparison) -> bool:
    """Return True when a trustworthy benchmark regressed past the threshold.

    An untrustworthy comparison (the control benchmark drifted) never reports
    a regression, because the measurement itself is not believable.
    """
    return comparison.trustworthy and bool(comparison.regressions)
