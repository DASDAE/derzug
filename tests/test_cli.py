"""Tests for the derzug CLI."""

from __future__ import annotations

from derzug import cli
from typer.testing import CliRunner


def test_dev_flag_enables_runner_dev_mode(monkeypatch):
    """The --dev flag should set dev_mode on the runner."""
    seen: dict[str, object] = {}

    class _FakeMain:
        def __init__(self):
            self.show_demo = False
            self.dev_mode = False
            self.startup_workflow_path = None

        def run(self, argv):
            seen["argv"] = argv
            seen["show_demo"] = self.show_demo
            seen["dev_mode"] = self.dev_mode
            seen["startup_workflow_path"] = self.startup_workflow_path
            return 0

    monkeypatch.setattr("derzug.views.orange.DerZugMain", _FakeMain)
    monkeypatch.setattr("derzug.views.orange.ensure_linux_desktop_entry", lambda: None)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["--dev"])

    assert result.exit_code == 0
    assert seen["argv"] == ["derzug"]
    assert seen["dev_mode"] is True
    assert seen["show_demo"] is False
    assert seen["startup_workflow_path"] is None


def test_workflow_argument_allows_dev_flag_after_path(monkeypatch):
    """CLI should accept `workflow.ows --dev` in addition to `--dev workflow.ows`."""
    seen: dict[str, object] = {}

    class _FakeMain:
        def __init__(self):
            self.show_demo = False
            self.dev_mode = False
            self.startup_workflow_path = None

        def run(self, argv):
            seen["argv"] = argv
            seen["show_demo"] = self.show_demo
            seen["dev_mode"] = self.dev_mode
            seen["startup_workflow_path"] = self.startup_workflow_path
            return 0

    monkeypatch.setattr("derzug.views.orange.DerZugMain", _FakeMain)
    monkeypatch.setattr("derzug.views.orange.ensure_linux_desktop_entry", lambda: None)

    runner = CliRunner()
    result = runner.invoke(cli.app, ["file_path.ows", "--dev"])

    assert result.exit_code == 0
    assert seen["argv"] == ["derzug", "file_path.ows"]
    assert seen["dev_mode"] is True
    assert seen["show_demo"] is False
    assert seen["startup_workflow_path"] == "file_path.ows"
