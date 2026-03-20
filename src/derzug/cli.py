"""Command-line interface for derzug."""

from __future__ import annotations

from pathlib import Path

import typer

app = typer.Typer(
    context_settings={"help_option_names": ["-h", "--help"]},
)


@app.command()
def main(
    workflow: Path | None = typer.Argument(
        None, help="Workflow file (.ows) to load on startup."
    ),
    demo: bool = typer.Option(
        False, "--demo", help="Open the example workflow browser on startup."
    ),
    dev: bool = typer.Option(
        False, "--dev", help="Enable development UI features such as hot reload."
    ),
    open_widgets: str = typer.Option(
        "",
        "--open-widgets",
        help="Comma-separated node indices to reopen on startup (used by hot reload).",
        hidden=True,
    ),
) -> None:
    """Run the derzug command-line interface."""
    from derzug.views.orange import DerZugMain, ensure_linux_desktop_entry

    argv = ["derzug"]
    if workflow is not None:
        argv.append(str(workflow))
    ensure_linux_desktop_entry()
    runner = DerZugMain()
    runner.show_demo = demo
    runner.dev_mode = dev
    runner.startup_workflow_path = None if workflow is None else str(workflow)
    runner.startup_open_widget_ids = [
        int(x) for x in open_widgets.split(",") if x.strip().isdigit()
    ]
    raise SystemExit(runner.run(argv))


if __name__ == "__main__":
    app()
