"""Tests for the Conductor MCP server (requires the optional ``mcp`` extra)."""

from __future__ import annotations

import asyncio
import json

import pytest

pytest.importorskip("mcp")

from derzug.conductor import CanvasController, MainThreadDispatcher  # noqa: E402
from derzug.conductor.mcp_server import (  # noqa: E402
    build_conductor_mcp,
    write_mcp_config,
)

_EXPECTED_TOOLS = {
    "get_canvas_state",
    "list_widget_types",
    "describe_node",
    "compile_check",
    "get_focus",
    "set_params",
    "set_view",
    "add_node",
    "remove_node",
    "connect",
    "disconnect",
    "run",
    "show_node",
    "move_node_window",
    "hide_node",
}


def _server(window):
    controller = CanvasController(window)
    mcp = build_conductor_mcp(controller, MainThreadDispatcher())
    return mcp, controller


def test_tools_are_registered(blank_canvas):
    """The server exposes the full observe/configure/author tool surface."""
    window, _ = blank_canvas
    mcp, _ = _server(window)
    names = {tool.name for tool in asyncio.run(mcp.list_tools())}
    assert _EXPECTED_TOOLS <= names


def test_add_node_tool_drives_the_controller(blank_canvas):
    """Calling the add_node tool authors a node on the live canvas."""
    window, _ = blank_canvas
    mcp, controller = _server(window)
    asyncio.run(mcp.call_tool("add_node", {"widget_type": "Detrend", "title": "dt"}))
    titles = [node.title for node in controller.get_canvas_state().nodes]
    assert "dt" in titles


def test_write_mcp_config(tmp_path):
    """The generated MCP config points a client at the server's endpoint."""
    path = tmp_path / ".mcp.json"
    url = write_mcp_config(path, port=4321)
    config = json.loads(path.read_text())
    assert url == "http://127.0.0.1:4321/mcp"
    assert config["mcpServers"]["derzug-conductor"]["url"] == url
    assert config["mcpServers"]["derzug-conductor"]["type"] == "http"


def test_write_codex_config_is_idempotent(tmp_path, monkeypatch):
    """The Codex MCP bridge is written once, under ~/.codex/config.toml."""
    from derzug.conductor.mcp_server import _write_codex_config

    monkeypatch.setenv("HOME", str(tmp_path))
    _write_codex_config("127.0.0.1", 4319)
    config = (tmp_path / ".codex" / "config.toml").read_text()
    assert "[mcp_servers.derzug-conductor]" in config
    assert "mcp-remote" in config
    assert "http://127.0.0.1:4319/mcp" in config

    _write_codex_config("127.0.0.1", 4319)  # again -> no duplicate section
    again = (tmp_path / ".codex" / "config.toml").read_text()
    assert again.count("[mcp_servers.derzug-conductor]") == 1


def test_launch_agent_missing_binary_is_safe(tmp_path):
    """Launching an agent that is not on PATH fails cleanly (no spawn)."""
    from derzug.conductor.mcp_server import launch_agent_in_terminal

    assert launch_agent_in_terminal("no-such-agent-xyz", str(tmp_path)) is False
