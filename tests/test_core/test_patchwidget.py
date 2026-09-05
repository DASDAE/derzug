"""Behavioral tests for shared patch-widget execution."""

from __future__ import annotations

from threading import get_ident

import dascore as dc
import pytest
from derzug.core.patchwidget import PatchWidget
from derzug.utils.testing import capture_output, wait_for_widget_idle, widget_context
from derzug.workflow import Task
from derzug.workflow.widget_tasks import PatchPassThroughTask
from Orange.widgets.utils.signals import Output


class _PatchHarness(PatchWidget):
    """Minimal patch processor without dimension controls."""

    name = "Patch Harness"

    class Outputs:
        """Output signal definitions."""

        patch = Output("Patch", dc.Patch)

    def get_task(self) -> Task:
        """Return a task that forwards the patch unchanged."""
        return PatchPassThroughTask()


@pytest.fixture(params=[False, True], ids=["sync", "async"])
def async_execution(request):
    """Select default worker execution or an explicit synchronous override."""
    return request.param


@pytest.fixture
def patch_widget(async_execution, qapp, monkeypatch):
    """Exercise the same public run contract with either execution mode."""
    with widget_context(_PatchHarness) as widget:
        if not async_execution:
            monkeypatch.setattr(widget, "_supports_async_execution", lambda: False)
        yield widget


class TestPatchWidget:
    """Shared execution preserves outputs at input and validation boundaries."""

    def test_run_forwards_patch(self, patch_widget, async_execution, monkeypatch):
        """Deliver the patch, using a worker thread unless sync is requested."""
        execution_threads = []
        run = PatchPassThroughTask.run

        def record_thread(task, patch):
            """Observe where the task executes without changing its output."""
            execution_threads.append(get_ident())
            return run(task, patch)

        monkeypatch.setattr(PatchPassThroughTask, "run", record_thread)
        patch = dc.get_example_patch()
        patch_widget._patch = patch
        received = capture_output(patch_widget.Outputs.patch, monkeypatch)

        patch_widget.run()
        wait_for_widget_idle(patch_widget)

        assert len(received) == 1
        assert received[0] is patch
        assert len(execution_threads) == 1
        assert (execution_threads[0] != get_ident()) == async_execution

    def test_missing_input_skips_task(self, patch_widget, monkeypatch):
        """Clearing input emits None without validating incomplete settings."""
        received = capture_output(patch_widget.Outputs.patch, monkeypatch)

        def unexpected_task():
            """Fail if task construction is attempted without an input."""
            pytest.fail("task construction requires a patch")

        monkeypatch.setattr(patch_widget, "get_task", unexpected_task)
        patch_widget.run()
        wait_for_widget_idle(patch_widget)

        assert received == [None]

    def test_preflight_can_suppress_execution(self, patch_widget, monkeypatch):
        """Widget-specific preflight can decline execution and clear output."""
        patch_widget._patch = dc.get_example_patch()
        received = capture_output(patch_widget.Outputs.patch, monkeypatch)
        monkeypatch.setattr(patch_widget, "_validated_task", lambda: None)

        patch_widget.run()
        wait_for_widget_idle(patch_widget)

        assert received == [None]
