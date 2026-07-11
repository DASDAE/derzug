"""Tests for the agent launch helpers (no ``mcp`` dependency required)."""

from __future__ import annotations

from derzug.conductor.launch import (
    _open_in_terminal,
    agent_command,
    launch_agent_in_terminal,
)

URL = "http://127.0.0.1:4319/mcp"


def test_claude_command_is_bare():
    """Claude Code needs no wiring flags; it reads the .mcp.json in its cwd."""
    assert agent_command("claude", URL) == ["claude"]


def test_codex_command_uses_native_http_override():
    """Codex gets a per-invocation -c override; no mcp-remote/npx bridge and no
    mutation of the user's ~/.codex/config.toml.
    """
    command = agent_command("codex", URL)
    assert command[0] == "codex"
    assert "-c" in command
    override = command[command.index("-c") + 1]
    assert override == f'mcp_servers.derzug-conductor.url="{URL}"'
    assert not any("mcp-remote" in part or "npx" in part for part in command)


def test_launch_agent_missing_binary_is_safe(tmp_path):
    """Launching an agent that is not on PATH fails cleanly (no spawn)."""
    assert launch_agent_in_terminal("no-such-agent-xyz", str(tmp_path), URL) is False


def test_xterm_receives_agent_arguments_separately(tmp_path, monkeypatch):
    """Xterm's -e receives an executable plus argv, not one joined shell string."""
    spawned: list[tuple[list[str], str | None]] = []
    command = agent_command("codex", URL)

    monkeypatch.setattr("derzug.conductor.launch.sys.platform", "linux")
    monkeypatch.setattr(
        "derzug.conductor.launch.shutil.which",
        lambda name: "/usr/bin/xterm" if name == "xterm" else None,
    )
    monkeypatch.setattr(
        "derzug.conductor.launch.subprocess.Popen",
        lambda argv, cwd=None: spawned.append((argv, cwd)),
    )

    assert _open_in_terminal(command, str(tmp_path)) is True
    assert spawned == [(["/usr/bin/xterm", "-e", *command], str(tmp_path))]
