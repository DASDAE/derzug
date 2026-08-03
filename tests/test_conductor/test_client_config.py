"""Tests for client-side connection config helpers (no ``mcp`` dependency)."""

from __future__ import annotations

import json

from derzug.conductor.client_config import (
    claude_add_command,
    codex_cli_command,
    codex_config_toml,
    write_mcp_config,
)


def test_write_mcp_config(tmp_path):
    """The generated MCP config points a client at the server's endpoint."""
    path = tmp_path / ".mcp.json"
    url = write_mcp_config(path, port=4321)
    config = json.loads(path.read_text())
    assert url == "http://127.0.0.1:4321/mcp"
    assert config["mcpServers"]["derzug-conductor"]["url"] == url
    assert config["mcpServers"]["derzug-conductor"]["type"] == "http"


def test_write_mcp_config_merges_existing_entries(tmp_path):
    """An existing .mcp.json keeps its other servers; only ours is replaced."""
    path = tmp_path / ".mcp.json"
    path.write_text(
        json.dumps(
            {
                "mcpServers": {
                    "other": {"type": "stdio", "command": "other-server"},
                    "derzug-conductor": {"type": "http", "url": "http://stale"},
                }
            }
        )
    )
    url = write_mcp_config(path, port=4321)
    config = json.loads(path.read_text())
    assert config["mcpServers"]["other"]["command"] == "other-server"
    assert config["mcpServers"]["derzug-conductor"]["url"] == url


def test_write_mcp_config_leaves_invalid_json_untouched(tmp_path):
    """A hand-edited config that fails to parse is never clobbered."""
    path = tmp_path / ".mcp.json"
    path.write_text("{not json")
    write_mcp_config(path, port=4321)
    assert path.read_text() == "{not json"


def test_connect_snippets_name_the_server_entry():
    """Every per-client snippet registers the same server entry and URL."""
    url = "http://127.0.0.1:4321/mcp"
    assert claude_add_command(url) == (
        "claude mcp add --transport http derzug-conductor http://127.0.0.1:4321/mcp"
    )
    assert codex_cli_command(url) == (
        'codex -c mcp_servers.derzug-conductor.url="http://127.0.0.1:4321/mcp"'
    )
    toml = codex_config_toml(url)
    assert toml.startswith("[mcp_servers.derzug-conductor]")
    assert f'url = "{url}"' in toml
