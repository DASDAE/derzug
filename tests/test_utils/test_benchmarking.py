"""Tests for the benchmark comparison helpers."""

from __future__ import annotations

import json

import pytest
from derzug.utils.benchmarking import (
    CONTROL_KEY,
    IMPROVED,
    NOISY,
    REGRESSED,
    UNCHANGED,
    BenchStat,
    combine_comparisons,
    compare_benchmarks,
    compare_environments,
    format_comparison,
    has_regression,
    load_walltime_results,
    newest_results_file,
    normalize_uri,
    parse_walltime_results,
)

_KEY = "benchmarks/core/test_a.py::TestA::test_b"


def make_stat(
    key: str = _KEY,
    *,
    median_ns: float = 1_000_000.0,
    min_ns: float | None = None,
    stdev_ns: float = 10_000.0,
    rounds: int = 100,
) -> BenchStat:
    """Return a benchmark statistic with sensible defaults."""
    return BenchStat(
        key=key,
        name=key.rsplit("::", maxsplit=1)[-1],
        min_ns=median_ns * 0.95 if min_ns is None else min_ns,
        median_ns=median_ns,
        mean_ns=median_ns,
        stdev_ns=stdev_ns,
        rounds=rounds,
    )


def make_payload(entries: list[dict], *, instrument: str = "walltime") -> dict:
    """Return a results document in pytest-codspeed's schema."""
    return {
        "creator": {"name": "pytest-codspeed", "version": "5.0.3", "pid": 1},
        "python": {"sysconfig": {}},
        "instrument": {"type": instrument},
        "benchmarks": entries,
    }


def make_entry(uri: str = _KEY, *, median_ns: float = 1_000_000.0) -> dict:
    """Return one benchmark entry in pytest-codspeed's schema."""
    return {
        "name": uri.rsplit("::", maxsplit=1)[-1],
        "uri": uri,
        "config": {},
        "stats": {
            "min_ns": median_ns * 0.95,
            "max_ns": median_ns * 1.2,
            "mean_ns": median_ns,
            "stdev_ns": median_ns * 0.01,
            "q1_ns": median_ns * 0.98,
            "median_ns": median_ns,
            "q3_ns": median_ns * 1.02,
            "rounds": 100,
            "total_time": 1.0,
            "iqr_outlier_rounds": 0,
            "stdev_outlier_rounds": 0,
            "iter_per_round": 1,
            "warmup_iters": 10,
        },
    }


class TestNormalizeUri:
    """Tests for uri normalization across working trees."""

    def test_strips_absolute_prefix(self):
        """An absolute path is truncated at the benchmarks anchor."""
        raw = "/home/x/worktrees/base/benchmarks/core/test_a.py::test_b"
        assert normalize_uri(raw) == "benchmarks/core/test_a.py::test_b"

    def test_relative_uri_unchanged(self):
        """An already-relative uri is returned untouched."""
        assert normalize_uri(_KEY) == _KEY

    def test_windows_separators_normalized(self):
        """Backslash separators are converted before anchoring."""
        raw = r"C:\repo\benchmarks\core\test_a.py::test_b"
        assert normalize_uri(raw) == "benchmarks/core/test_a.py::test_b"

    def test_missing_anchor_returns_input(self):
        """A uri without the anchor is passed through."""
        assert normalize_uri("other/test_a.py::test_b") == "other/test_a.py::test_b"

    def test_differing_prefixes_produce_equal_keys(self):
        """Two trees running the same file yield one joinable key."""
        left = normalize_uri("/a/b/benchmarks/core/test_a.py::test_b")
        right = normalize_uri("/c/benchmarks/core/test_a.py::test_b")
        assert left == right


class TestParseWalltimeResults:
    """Tests for results-document parsing."""

    def test_parses_entries(self):
        """A well-formed document yields keyed statistics."""
        parsed = parse_walltime_results(make_payload([make_entry()]))
        assert set(parsed) == {_KEY}
        assert parsed[_KEY].median_ns == 1_000_000.0
        assert parsed[_KEY].rounds == 100

    def test_rejects_non_walltime_instrument(self):
        """A simulation-mode document is rejected rather than misread."""
        payload = make_payload([make_entry()], instrument="simulation")
        with pytest.raises(ValueError, match="walltime"):
            parse_walltime_results(payload)

    def test_rejects_missing_instrument(self):
        """A document with no instrument section is rejected."""
        with pytest.raises(ValueError, match="instrument"):
            parse_walltime_results({"benchmarks": []})

    def test_rejects_unknown_entry_schema(self):
        """A missing stats key raises instead of producing zeros."""
        payload = make_payload([{"uri": _KEY, "stats": {"median_ns": 1.0}}])
        with pytest.raises(ValueError, match="schema"):
            parse_walltime_results(payload)

    def test_load_from_file(self, tmp_path):
        """Results can be read straight off disk."""
        path = tmp_path / "results_1.json"
        path.write_text(json.dumps(make_payload([make_entry()])))
        assert set(load_walltime_results(path)) == {_KEY}


class TestNewestResultsFile:
    """Tests for locating the file a run just wrote."""

    def test_excluded_files_ignored(self, tmp_path):
        """A pre-run snapshot lets the new file be identified."""
        old = tmp_path / "results_1.json"
        new = tmp_path / "results_2.json"
        old.write_text("{}")
        new.write_text("{}")
        assert newest_results_file(tmp_path, exclude=[old]) == new

    def test_raises_when_nothing_new(self, tmp_path):
        """No candidate file is an error, not a silent reuse."""
        old = tmp_path / "results_1.json"
        old.write_text("{}")
        with pytest.raises(FileNotFoundError):
            newest_results_file(tmp_path, exclude=[old])


class TestCompareBenchmarks:
    """Tests for benchmark classification."""

    def test_clean_regression(self):
        """A benchmark slower in both median and min is a regression."""
        baseline = {_KEY: make_stat()}
        head = {_KEY: make_stat(median_ns=1_500_000.0)}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert comparison.deltas[0].verdict == REGRESSED
        assert has_regression(comparison)

    def test_clean_improvement(self):
        """A benchmark faster in both statistics is an improvement."""
        baseline = {_KEY: make_stat()}
        head = {_KEY: make_stat(median_ns=500_000.0)}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert comparison.deltas[0].verdict == IMPROVED
        assert not has_regression(comparison)

    def test_median_only_move_is_unchanged(self):
        """Median and min must agree before a change is reported."""
        baseline = {_KEY: make_stat(median_ns=1_000_000.0, min_ns=950_000.0)}
        head = {_KEY: make_stat(median_ns=1_500_000.0, min_ns=960_000.0)}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert comparison.deltas[0].verdict == UNCHANGED

    def test_below_noise_floor_is_noisy(self):
        """A very fast benchmark is never called a regression."""
        baseline = {_KEY: make_stat(median_ns=1_000.0, stdev_ns=1.0)}
        head = {_KEY: make_stat(median_ns=5_000.0, stdev_ns=1.0)}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert comparison.deltas[0].verdict == NOISY
        assert not has_regression(comparison)

    def test_jittery_baseline_is_noisy(self):
        """A baseline with high relative stdev is not trusted."""
        baseline = {_KEY: make_stat(stdev_ns=500_000.0)}
        head = {_KEY: make_stat(median_ns=2_000_000.0)}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert comparison.deltas[0].verdict == NOISY

    def test_small_change_is_unchanged(self):
        """A move below the threshold is not reported."""
        baseline = {_KEY: make_stat()}
        head = {_KEY: make_stat(median_ns=1_050_000.0)}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert comparison.deltas[0].verdict == UNCHANGED

    def test_added_and_removed_keys(self):
        """Benchmarks present on only one side are listed, not compared."""
        baseline = {_KEY: make_stat()}
        head = {"benchmarks/core/test_c.py::test_d": make_stat(key="x")}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert comparison.added == ("benchmarks/core/test_c.py::test_d",)
        assert comparison.removed == (_KEY,)
        assert comparison.deltas == ()

    def test_ranked_worst_first(self):
        """Deltas are ordered by median change, worst regression first."""
        keys = [f"benchmarks/core/test_{name}.py::test_x" for name in "abc"]
        baseline = {key: make_stat(key=key) for key in keys}
        head = {
            keys[0]: make_stat(key=keys[0], median_ns=1_000_000.0),
            keys[1]: make_stat(key=keys[1], median_ns=2_000_000.0),
            keys[2]: make_stat(key=keys[2], median_ns=500_000.0),
        }
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert [delta.key for delta in comparison.deltas] == [
            keys[1],
            keys[0],
            keys[2],
        ]

    def test_round_count_divergence_noted(self):
        """A large round-count spread is surfaced as a note."""
        baseline = {_KEY: make_stat(rounds=100)}
        head = {_KEY: make_stat(median_ns=1_500_000.0, rounds=10)}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert "round counts differ" in comparison.deltas[0].note


class TestControlBenchmark:
    """Tests for the measurement-drift control."""

    def test_drifted_control_marks_untrustworthy(self):
        """A moving control invalidates every other verdict."""
        baseline = {CONTROL_KEY: make_stat(key=CONTROL_KEY), _KEY: make_stat()}
        head = {
            CONTROL_KEY: make_stat(key=CONTROL_KEY, median_ns=1_400_000.0),
            _KEY: make_stat(median_ns=1_500_000.0),
        }
        comparison = compare_benchmarks(baseline, head)
        assert comparison.trustworthy is False
        assert comparison.regressions
        assert not has_regression(comparison)
        assert any("control benchmark moved" in w for w in comparison.warnings)

    def test_stable_control_keeps_trust(self):
        """A steady control leaves regressions actionable."""
        baseline = {CONTROL_KEY: make_stat(key=CONTROL_KEY), _KEY: make_stat()}
        head = {
            CONTROL_KEY: make_stat(key=CONTROL_KEY, median_ns=1_020_000.0),
            _KEY: make_stat(median_ns=1_500_000.0),
        }
        comparison = compare_benchmarks(baseline, head)
        assert comparison.trustworthy is True
        assert has_regression(comparison)

    def test_control_excluded_from_deltas(self):
        """The control is reported separately, not as a benchmark."""
        baseline = {CONTROL_KEY: make_stat(key=CONTROL_KEY)}
        head = {CONTROL_KEY: make_stat(key=CONTROL_KEY)}
        comparison = compare_benchmarks(baseline, head)
        assert comparison.deltas == ()
        assert comparison.control is not None

    def test_missing_control_warns(self):
        """A run without the control says so."""
        comparison = compare_benchmarks({_KEY: make_stat()}, {_KEY: make_stat()})
        assert any("control benchmark missing" in w for w in comparison.warnings)


class TestCompareEnvironments:
    """Tests for dependency-drift detection."""

    def test_version_mismatch_warns(self):
        """A differing shared dependency produces a warning."""
        warnings = compare_environments({"numpy": "2.0"}, {"numpy": "2.1"})
        assert len(warnings) == 1
        assert "numpy" in warnings[0]

    def test_matching_versions_silent(self):
        """Identical environments produce no warnings."""
        assert compare_environments({"numpy": "2.0"}, {"numpy": "2.0"}) == ()

    def test_derzug_ignored(self):
        """DerZug itself is expected to differ between the two trees."""
        assert compare_environments({"derzug": "1"}, {"derzug": "2"}) == ()

    def test_unshared_packages_reported(self):
        """A package on only one side is drift; an auto-loaded plugin would be."""
        warnings = compare_environments({"numpy": "2.0"}, {"pandas": "2.0"})
        assert len(warnings) == 2


class TestFormatComparison:
    """Tests for the rendered table."""

    def test_includes_benchmark_and_summary(self):
        """The table names each benchmark and summarises the run."""
        baseline = {_KEY: make_stat()}
        head = {_KEY: make_stat(median_ns=1_500_000.0)}
        text = format_comparison(compare_benchmarks(baseline, head, control_key=None))
        assert "test_b" in text
        assert "SLOWER" in text
        assert "1 slower" in text

    def test_reports_control_drift(self):
        """A drifted control is called out in the rendered output."""
        baseline = {CONTROL_KEY: make_stat(key=CONTROL_KEY)}
        head = {CONTROL_KEY: make_stat(key=CONTROL_KEY, median_ns=1_400_000.0)}
        text = format_comparison(compare_benchmarks(baseline, head))
        assert "DRIFTED" in text


class TestInvalidTimingData:
    """Tests that unusable timings fail loudly instead of reading as a win."""

    @pytest.mark.parametrize("bad", [0.0, -1.0, float("nan"), float("inf")])
    def test_rejects_unusable_median(self, bad):
        """A zero, negative, or non-finite duration is rejected at parse time."""
        entry = make_entry()
        entry["stats"]["median_ns"] = bad
        with pytest.raises(ValueError, match="schema"):
            parse_walltime_results(make_payload([entry]))

    def test_rejects_negative_stdev(self):
        """A negative standard deviation is rejected."""
        entry = make_entry()
        entry["stats"]["stdev_ns"] = -1.0
        with pytest.raises(ValueError, match="schema"):
            parse_walltime_results(make_payload([entry]))

    def test_rejects_empty_benchmark_list(self):
        """A results file with no benchmarks is an error, not an empty pass."""
        with pytest.raises(ValueError, match="no benchmarks"):
            parse_walltime_results(make_payload([]))


class TestIncompleteComparisons:
    """Tests that a partial comparison never reads as a clean run."""

    def test_disjoint_results_untrustworthy(self):
        """Two runs sharing no benchmarks cannot report 'no regression'."""
        baseline = {_KEY: make_stat()}
        head = {"benchmarks/core/test_c.py::test_d": make_stat(key="x")}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert comparison.trustworthy is False
        assert not has_regression(comparison)

    def test_one_sided_benchmark_untrustworthy(self):
        """A benchmark present on only one side invalidates the comparison."""
        extra = "benchmarks/core/test_c.py::test_d"
        baseline = {_KEY: make_stat()}
        head = {_KEY: make_stat(), extra: make_stat(key=extra)}
        comparison = compare_benchmarks(baseline, head, control_key=None)
        assert comparison.trustworthy is False

    def test_missing_control_untrustworthy(self):
        """Without the control there is no drift detection, so no verdict."""
        comparison = compare_benchmarks({_KEY: make_stat()}, {_KEY: make_stat()})
        assert comparison.trustworthy is False


class TestCombineComparisons:
    """Tests for reducing interleaved passes."""

    def _pair(self, head_median: float):
        """Return a one-benchmark comparison with the given head median."""
        return compare_benchmarks(
            {_KEY: make_stat()},
            {_KEY: make_stat(median_ns=head_median)},
            control_key=None,
        )

    def test_single_comparison_passthrough(self):
        """One pass is returned unchanged."""
        only = self._pair(1_500_000.0)
        assert combine_comparisons([only]) is only

    def test_regression_must_reproduce_in_every_pass(self):
        """A regression seen in only one pass is not reported."""
        combined = combine_comparisons(
            [self._pair(1_500_000.0), self._pair(1_000_000.0)]
        )
        assert combined.deltas[0].verdict == UNCHANGED
        assert not has_regression(combined)

    def test_consistent_regression_survives(self):
        """A regression seen in every pass is reported."""
        combined = combine_comparisons(
            [self._pair(1_500_000.0), self._pair(1_600_000.0)]
        )
        assert combined.deltas[0].verdict == REGRESSED
        assert has_regression(combined)

    def test_untrustworthy_pass_taints_result(self):
        """One untrustworthy pass makes the combined result untrustworthy."""
        good = self._pair(1_500_000.0)
        bad = compare_benchmarks({_KEY: make_stat()}, {})
        combined = combine_comparisons([good, bad])
        assert combined.trustworthy is False

    def test_rejects_empty_input(self):
        """Combining nothing is a programming error."""
        with pytest.raises(ValueError, match="empty"):
            combine_comparisons([])


class TestOneSidedDependencies:
    """Tests for packages installed in only one environment."""

    def test_baseline_only_package_warns(self):
        """A package missing from head is drift, not something to ignore."""
        warnings = compare_environments({"pytest-xdist": "3.0"}, {})
        assert len(warnings) == 1
        assert "baseline only" in warnings[0]

    def test_head_only_package_warns(self):
        """A package missing from the baseline is drift too."""
        warnings = compare_environments({}, {"pytest-xdist": "3.0"})
        assert len(warnings) == 1
        assert "head only" in warnings[0]


class TestCombinedControlReporting:
    """Tests that the reported control agrees with the trust verdict."""

    def test_worst_control_is_reported(self):
        """A drifted pass sets the headline control, not the last pass."""
        steady = compare_benchmarks(
            {CONTROL_KEY: make_stat(key=CONTROL_KEY)},
            {CONTROL_KEY: make_stat(key=CONTROL_KEY, median_ns=1_010_000.0)},
        )
        drifted = compare_benchmarks(
            {CONTROL_KEY: make_stat(key=CONTROL_KEY)},
            {CONTROL_KEY: make_stat(key=CONTROL_KEY, median_ns=1_400_000.0)},
        )
        combined = combine_comparisons([drifted, steady])
        assert combined.trustworthy is False
        assert combined.control is not None
        assert combined.control.median_ratio == pytest.approx(0.4)
        assert "DRIFTED" in format_comparison(combined)
