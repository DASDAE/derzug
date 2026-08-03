"""Compare DerZug benchmarks between the working tree and a baseline revision.

Run this before opening a pull request that touches a hot path::

    python scripts/bench_compare.py --baseline main

The script checks out the baseline revision into a throwaway git worktree,
gives it an environment whose third-party versions match the current one, then
runs the *current* tree's benchmark files against each side's installed
DerZug. Only DerZug's own source differs between the two measurements.

See docs/dev/benchmarking.md for the full workflow.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import typer

_REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_REPO_ROOT / "src"))

from derzug.utils.benchmarking import (  # noqa: E402
    CONTROL_KEY,
    DEFAULT_CONTROL_TOLERANCE,
    DEFAULT_MAX_REL_STDEV,
    DEFAULT_NOISE_FLOOR_NS,
    DEFAULT_THRESHOLD,
    BenchStat,
    combine_comparisons,
    compare_benchmarks,
    compare_environments,
    format_comparison,
    has_regression,
    load_walltime_results,
    newest_results_file,
)

app = typer.Typer(
    add_completion=False,
    context_settings={"help_option_names": ["-h", "--help"]},
)

_BASELINE_WORKTREE = _REPO_ROOT / "worktrees" / "_bench_baseline"
_OUT_DIR = _REPO_ROOT / ".codspeed_compare"
_CODSPEED_DIR = _REPO_ROOT / ".codspeed"

_SUITE_PATHS = {
    "core": ("benchmarks/core",),
    "qt": ("benchmarks/qt",),
    "all": ("benchmarks",),
}


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
    capture: bool = True,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess:
    """Run a subprocess, raising a typer error on failure."""
    result = subprocess.run(
        command,
        cwd=cwd,
        check=False,
        text=True,
        capture_output=capture,
        env=env,
    )
    if check and result.returncode != 0:
        typer.echo(f"command failed: {' '.join(command)}", err=True)
        if capture:
            typer.echo(result.stdout, err=True)
            typer.echo(result.stderr, err=True)
        raise typer.Exit(code=1)
    return result


def _require_uv() -> str:
    """Return the path to uv, failing with a clear message when absent."""
    uv = shutil.which("uv")
    if uv is None:
        typer.echo(
            "uv is required to build the baseline environment; "
            "install it or pass --baseline-dir pointing at a prepared tree.",
            err=True,
        )
        raise typer.Exit(code=1)
    return uv


def _resolve_baseline_worktree(revision: str) -> Path:
    """Create or refresh the baseline worktree and return its path.

    The worktree is always re-pointed at ``revision`` and forcibly cleaned:
    ``worktrees/`` is gitignored, and the baseline's editable install points
    straight into this tree, so a leftover modified or untracked source file
    would silently become "the baseline".
    """
    if not _BASELINE_WORKTREE.exists():
        _BASELINE_WORKTREE.parent.mkdir(parents=True, exist_ok=True)
        _run(
            [
                "git",
                "worktree",
                "add",
                "--detach",
                str(_BASELINE_WORKTREE),
                revision,
            ],
            cwd=_REPO_ROOT,
        )
    else:
        fetched = _run(
            ["git", "fetch", "--all", "--quiet"], cwd=_REPO_ROOT, check=False
        )
        if fetched.returncode != 0:
            typer.echo(
                "warning: git fetch failed; the baseline revision may be stale",
                err=True,
            )
        checkout = ["git", "checkout", "--detach", "--quiet", revision]
        _run(checkout, cwd=_BASELINE_WORKTREE)
        # checkout alone keeps non-conflicting local edits and every untracked
        # file. Only reset+clean guarantee the tree matches the revision.
        _run(["git", "reset", "--hard", "--quiet", revision], cwd=_BASELINE_WORKTREE)
        _run(
            ["git", "clean", "-qfdx", "--exclude=.venv"],
            cwd=_BASELINE_WORKTREE,
        )
    sha = _run(
        ["git", "rev-parse", "--short", "HEAD"], cwd=_BASELINE_WORKTREE
    ).stdout.strip()
    subject = _run(
        ["git", "log", "-1", "--format=%s"], cwd=_BASELINE_WORKTREE
    ).stdout.strip()
    typer.echo(f"baseline: {revision} -> {sha} {subject}")
    return _BASELINE_WORKTREE


def _venv_python(directory: Path) -> Path:
    """Return the interpreter path inside a directory's virtualenv."""
    if os.name == "nt":  # pragma: no cover - posix development target
        return directory / ".venv" / "Scripts" / "python.exe"
    return directory / ".venv" / "bin" / "python"


def _python_version(python: Path) -> str:
    """Return the ``major.minor`` version of one interpreter."""
    return _run(
        [
            str(python),
            "-c",
            "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}')",
        ]
    ).stdout.strip()


def _clean_env() -> dict[str, str]:
    """Return a subprocess environment that cannot redirect the import path.

    ``PYTHONPATH`` takes precedence over a venv's editable-install finder, so
    an inherited one pointing at this checkout's ``src`` would make the
    baseline interpreter import head's source and quietly compare head
    against itself. ``PYTEST_ADDOPTS`` and friends can likewise change what
    is collected on only one side.
    """
    env = {
        key: value
        for key, value in os.environ.items()
        if key
        not in {"PYTHONPATH", "PYTEST_ADDOPTS", "PYTEST_PLUGINS", "PYTHONSTARTUP"}
    }
    env["QT_QPA_PLATFORM"] = "offscreen"
    env["MPLBACKEND"] = "Agg"
    return env


def _assert_derzug_source(python: Path, expected_root: Path, label: str) -> None:
    """Fail unless an interpreter imports DerZug from the expected tree.

    Without this the whole comparison can silently degrade into measuring one
    checkout twice.
    """
    result = _run(
        [str(python), "-c", "import derzug.workflow.pipe as m; print(m.__file__)"],
        cwd=_REPO_ROOT,
        check=False,
        env=_clean_env(),
    )
    resolved = Path(result.stdout.strip()) if result.stdout.strip() else None
    if result.returncode != 0 or resolved is None:
        typer.echo(f"{label}: could not import derzug\n{result.stderr}", err=True)
        raise typer.Exit(code=1)
    if expected_root.resolve() not in resolved.resolve().parents:
        typer.echo(
            f"{label} interpreter imports derzug from {resolved}, "
            f"which is outside {expected_root}; the comparison would be "
            "meaningless.",
            err=True,
        )
        raise typer.Exit(code=1)
    typer.echo(f"{label} derzug: {resolved}")


def _sync_baseline_env(baseline_dir: Path, head_python: Path, *, sync: bool) -> Path:
    """Ensure the baseline tree has an interpreter and return it.

    When ``sync`` is set the baseline gets exactly the head environment's
    third-party versions, so the only difference between the two runs is
    DerZug's own source. Resolving the baseline independently would let a
    different NumPy or dascore slip in and silently invalidate every number.
    """
    baseline_python = _venv_python(baseline_dir)
    if baseline_python.exists() and not sync:
        return baseline_python

    uv = _require_uv()
    version = _python_version(head_python)

    if baseline_python.exists() and _python_version(baseline_python) != version:
        # A reused venv built against an older interpreter would compare two
        # Pythons rather than two DerZugs.
        typer.echo(
            f"baseline interpreter is {_python_version(baseline_python)}, "
            f"current is {version}; rebuilding it"
        )
        shutil.rmtree(baseline_dir / ".venv")

    if not baseline_python.exists():
        typer.echo(f"creating baseline environment (python {version})...")
        _run([uv, "venv", "--python", version, str(baseline_dir / ".venv")])

    frozen = _run([uv, "pip", "freeze", "--python", str(head_python)]).stdout
    requirements = [
        line
        for line in frozen.splitlines()
        if line.strip() and "derzug" not in line.lower()
    ]
    requirements_file = _OUT_DIR / "baseline-requirements.txt"
    requirements_file.parent.mkdir(parents=True, exist_ok=True)
    requirements_file.write_text("\n".join(requirements) + "\n", encoding="utf-8")

    typer.echo("syncing baseline dependencies to match the current tree...")
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(baseline_python),
            "--quiet",
            "-r",
            str(requirements_file),
        ]
    )
    _run(
        [
            uv,
            "pip",
            "install",
            "--python",
            str(baseline_python),
            "--quiet",
            "--no-deps",
            "-e",
            str(baseline_dir),
        ]
    )
    return baseline_python


def _installed_versions(python: Path) -> dict[str, str]:
    """Return a name-to-version map for one environment."""
    uv = shutil.which("uv")
    if uv is None:
        return {}
    result = _run(
        [uv, "pip", "list", "--python", str(python), "--format", "json"],
        check=False,
    )
    if result.returncode != 0:
        return {}
    try:
        entries = json.loads(result.stdout)
    except json.JSONDecodeError:
        return {}
    return {entry["name"]: entry["version"] for entry in entries}


def _run_benchmarks(
    python: Path,
    label: str,
    suite: str,
    keyword: str | None,
    max_time: float,
) -> dict[str, BenchStat]:
    """Run one benchmark pass and return its parsed statistics.

    Both passes execute the *current* tree's benchmark files with the current
    tree as the pytest rootdir; only the interpreter differs, so ``import
    derzug`` resolves to each side's own editable install.
    """
    before = set(_CODSPEED_DIR.glob("results_*.json"))
    command = [
        str(python),
        "-m",
        "pytest",
        *_SUITE_PATHS[suite],
        "--codspeed",
        "--codspeed-mode=walltime",
        f"--codspeed-max-time={max_time}",
        "-q",
        "--no-header",
    ]
    if keyword:
        command.extend(["-k", keyword])

    typer.echo(f"running {label} benchmarks ({suite})...")
    result = subprocess.run(
        command, cwd=_REPO_ROOT, check=False, text=True, env=_clean_env()
    )
    if result.returncode != 0:
        typer.echo(f"{label} benchmark run failed (exit {result.returncode})", err=True)
        raise typer.Exit(code=1)

    fresh = set(_CODSPEED_DIR.glob("results_*.json")) - before
    if len(fresh) > 1:
        # Another benchmark process wrote to the same directory; picking by
        # mtime could hand us its numbers.
        typer.echo(
            f"warning: {len(fresh)} new results files appeared during the "
            f"{label} run; another benchmark process may be running",
            err=True,
        )
    results_path = newest_results_file(_CODSPEED_DIR, exclude=before)
    _OUT_DIR.mkdir(parents=True, exist_ok=True)
    saved = _OUT_DIR / f"{label}.json"
    shutil.copy2(results_path, saved)
    return load_walltime_results(saved)


def _report(
    pairs: list[tuple[dict[str, BenchStat], dict[str, BenchStat]]],
    *,
    threshold: float,
    noise_floor_ns: float,
    max_rel_stdev: float,
    control_tolerance: float,
    env_warnings: tuple[str, ...],
    fail_on_regression: bool,
) -> None:
    """Format and emit a comparison, then exit with the right status.

    Each element of ``pairs`` is one interleaved baseline/head pass. They are
    compared pass by pass and reduced conservatively, so a regression must
    reproduce in every pass to be reported.
    """
    comparison = combine_comparisons(
        [
            compare_benchmarks(
                baseline_stats,
                head_stats,
                threshold=threshold,
                noise_floor_ns=noise_floor_ns,
                max_rel_stdev=max_rel_stdev,
                control_key=CONTROL_KEY,
                control_tolerance=control_tolerance,
            )
            for baseline_stats, head_stats in pairs
        ]
    )
    typer.echo("")
    typer.echo(format_comparison(comparison, threshold=threshold))
    for warning in env_warnings:
        typer.echo(f"warning: {warning}")

    if has_regression(comparison):
        typer.echo("")
        typer.echo(
            f"{len(comparison.regressions)} benchmark(s) regressed past "
            f"{threshold:.0%}; investigate before opening the PR."
        )
        if fail_on_regression:
            raise typer.Exit(code=1)
    elif not comparison.trustworthy:
        # A comparison that could not be trusted must never read as a pass.
        typer.echo("")
        typer.echo(
            "this comparison is not trustworthy (see warnings above); "
            "re-run on an idle machine before drawing a conclusion."
        )
        if fail_on_regression:
            raise typer.Exit(code=1)


@app.command()
def main(
    baseline: str = typer.Option("main", help="Git revision to compare against."),
    baseline_dir: Path | None = typer.Option(
        None,
        help="Use a prepared directory as the baseline instead of a worktree.",
    ),
    suite: str = typer.Option(
        "core", help="Which benchmark tree to run: core, qt, or all."
    ),
    keyword: str | None = typer.Option(
        None, "-k", help="Pytest -k expression to compare a subset."
    ),
    threshold: float = typer.Option(
        DEFAULT_THRESHOLD, help="Fractional change counted as a regression."
    ),
    repeat: int = typer.Option(
        1, help="Interleaved passes per side. Use 2 before quoting a number."
    ),
    max_time: float = typer.Option(
        3.0,
        help="Seconds per benchmark. Lower is faster but noisier.",
    ),
    noise_floor_ns: float = typer.Option(
        DEFAULT_NOISE_FLOOR_NS, help="Ignore benchmarks faster than this."
    ),
    max_rel_stdev: float = typer.Option(
        DEFAULT_MAX_REL_STDEV, help="Mark jitterier baselines as noisy."
    ),
    control_tolerance: float = typer.Option(
        DEFAULT_CONTROL_TOLERANCE,
        help="Control-benchmark drift that invalidates the comparison.",
    ),
    sync_env: bool = typer.Option(
        True, help="Pin baseline dependencies to the current environment."
    ),
    strict_env: bool = typer.Option(
        False, help="Fail instead of warning when dependencies differ."
    ),
    fail_on_regression: bool = typer.Option(
        False, help="Exit non-zero when a benchmark regresses."
    ),
    from_json: tuple[Path, Path] = typer.Option(
        (None, None),
        help="Re-render a comparison from saved baseline and head results.",
    ),
) -> None:
    """Compare benchmark results between this tree and a baseline revision."""
    if suite not in _SUITE_PATHS:
        typer.echo(f"unknown suite {suite!r}; pick core, qt, or all", err=True)
        raise typer.Exit(code=1)

    if from_json[0] is not None and from_json[1] is not None:
        _report(
            [
                (
                    load_walltime_results(from_json[0]),
                    load_walltime_results(from_json[1]),
                )
            ],
            threshold=threshold,
            noise_floor_ns=noise_floor_ns,
            max_rel_stdev=max_rel_stdev,
            control_tolerance=control_tolerance,
            env_warnings=(),
            fail_on_regression=fail_on_regression,
        )
        return

    head_python = _venv_python(_REPO_ROOT)
    if not head_python.exists():
        head_python = Path(sys.executable)

    if baseline_dir is not None:
        baseline_root = baseline_dir.resolve()
        baseline_python = _venv_python(baseline_root)
        if not baseline_python.exists():
            typer.echo(f"no virtualenv found at {baseline_root / '.venv'}", err=True)
            raise typer.Exit(code=1)
    else:
        baseline_root = _resolve_baseline_worktree(baseline)
        baseline_python = _sync_baseline_env(baseline_root, head_python, sync=sync_env)

    # The whole comparison is worthless if either interpreter resolves DerZug
    # to the wrong tree, so prove it before spending minutes measuring.
    _assert_derzug_source(baseline_python, baseline_root, "baseline")
    _assert_derzug_source(head_python, _REPO_ROOT, "head")

    env_warnings = compare_environments(
        _installed_versions(baseline_python), _installed_versions(head_python)
    )
    if env_warnings and strict_env:
        for warning in env_warnings:
            typer.echo(f"error: {warning}", err=True)
        raise typer.Exit(code=1)

    pairs: list[tuple[dict[str, BenchStat], dict[str, BenchStat]]] = []
    for index in range(max(1, repeat)):
        # Interleave the passes so machine drift hits both sides of each pair
        # alike; the pair is the unit that later gets compared.
        suffix = "" if repeat == 1 else f"-{index + 1}"
        baseline_stats = _run_benchmarks(
            baseline_python, f"baseline{suffix}", suite, keyword, max_time
        )
        head_stats = _run_benchmarks(
            head_python, f"head{suffix}", suite, keyword, max_time
        )
        pairs.append((baseline_stats, head_stats))

    _report(
        pairs,
        threshold=threshold,
        noise_floor_ns=noise_floor_ns,
        max_rel_stdev=max_rel_stdev,
        control_tolerance=control_tolerance,
        env_warnings=env_warnings,
        fail_on_regression=fail_on_regression,
    )


if __name__ == "__main__":
    app()
