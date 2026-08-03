"""Headless execution: build and run node tasks with no display available.

These run in a fresh interpreter so the assertion that Qt never loaded is
meaningful despite the suite-wide ``QApplication`` in ``tests/conftest.py``.
"""

from __future__ import annotations

from .test_import_layering import run_isolated


class TestHeadlessExecution:
    """A node's task runs on a real patch without Qt."""

    def test_filter_task_runs_headless(self):
        """The Filter node filters an example patch outside the canvas."""
        result = run_isolated(
            """
            import dascore as dc
            from derzug.nodes.registry import spec_by_name
            from pydantic import TypeAdapter

            spec = spec_by_name("Filter")
            params = TypeAdapter(spec.params_model).validate_python(
                {
                    "kind": "pass_filter",
                    "dim": "time",
                    "low_bound": "10",
                    "high_bound": "100",
                }
            )
            patch = dc.get_example_patch()
            out = spec.build_task(params).run(patch)
            assert isinstance(out, dc.Patch), type(out)
            assert out.shape == patch.shape
            """
        )
        assert result.returncode == 0, result.stderr

    def test_taper_task_runs_headless(self):
        """The Taper node tapers an example patch outside the canvas."""
        result = run_isolated(
            """
            import dascore as dc
            from derzug.nodes.registry import spec_by_name
            from pydantic import TypeAdapter

            spec = spec_by_name("Taper")
            patch = dc.get_example_patch()
            out = spec.build_task(spec.params_model(dim="time", p=0.1)).run(patch)
            assert isinstance(out, dc.Patch), type(out)
            assert out.shape == patch.shape
            """
        )
        assert result.returncode == 0, result.stderr

    def test_two_node_pipe_runs_headless(self):
        """A Taper -> Filter pipe compiles, validates, and runs without Qt."""
        result = run_isolated(
            """
            import dascore as dc
            from derzug.nodes.registry import spec_by_name
            from pydantic import TypeAdapter
            from derzug.workflow import PipeBuilder

            taper = spec_by_name("Taper")
            filt = spec_by_name("Filter")
            filter_params = TypeAdapter(filt.params_model).validate_python(
                {
                    "kind": "pass_filter",
                    "dim": "time",
                    "low_bound": "10",
                    "high_bound": "100",
                }
            )

            builder = PipeBuilder()
            first = builder.add(taper.build_task(taper.params_model(dim="time")))
            second = builder.add(filt.build_task(filter_params))
            builder.connect(first, second)
            pipe = builder.build()
            pipe.validate()

            results = pipe.run(patch=dc.get_example_patch())
            assert results.ok, results.errors
            assert isinstance(results[second], dc.Patch), type(results[second])
            """
        )
        assert result.returncode == 0, result.stderr

    def test_serialized_pipe_round_trips_without_qt(self):
        """Node task code paths deserialize in a fresh, Qt-free interpreter."""
        result = run_isolated(
            """
            import tempfile
            from pathlib import Path

            import dascore as dc
            from derzug.nodes.registry import spec_by_name
            from pydantic import TypeAdapter
            from derzug.workflow import Pipe, PipeBuilder

            spec = spec_by_name("Filter")
            params = TypeAdapter(spec.params_model).validate_python(
                {
                    "kind": "pass_filter",
                    "dim": "time",
                    "low_bound": "10",
                    "high_bound": "100",
                }
            )
            builder = PipeBuilder()
            handle = builder.add(spec.build_task(params))

            with tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "pipe.yaml"
                builder.build().to_yaml(path)
                payload = path.read_text(encoding="utf-8")
                assert "derzug.nodes.filter:FilterTask" in payload, payload
                restored = Pipe.from_yaml(path)

            restored.validate()
            results = restored.run(patch=dc.get_example_patch())
            assert results.ok, results.errors
            assert isinstance(results[handle], dc.Patch), type(results[handle])
            """
        )
        assert result.returncode == 0, result.stderr
