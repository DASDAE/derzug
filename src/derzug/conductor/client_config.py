"""Client-side connection setup for the Conductor MCP server.

Stdlib-only helpers with no ``mcp`` dependency: write the ``.mcp.json`` entry
Claude Code discovers in its launch directory, and build the copy-paste
connect snippets the UI shows for each supported client.
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any

from derzug.conductor.constants import DEFAULT_HOST, DEFAULT_PORT, SERVER_NAME

log = logging.getLogger(__name__)


def mcp_url(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> str:
    """Return the MCP endpoint URL of a server bound to ``host``:``port``."""
    return f"http://{host}:{port}/mcp"


def write_mcp_config(
    path: str | Path,
    *,
    host: str = DEFAULT_HOST,
    port: int = DEFAULT_PORT,
    name: str = SERVER_NAME,
) -> str:
    """Merge our server entry into the MCP client config at ``path``; return URL.

    The file is an ``.mcp.json`` a client such as Claude Code picks up. An
    existing config keeps its other entries — only ``mcpServers[name]`` is
    replaced — and the file is written atomically (temp file + rename). An
    existing file that is not valid JSON is left untouched (logged), so a
    user's hand-edited config is never clobbered.
    """
    url = mcp_url(host, port)
    path = Path(path)
    config: dict[str, Any] = {}
    if path.exists():
        try:
            config = json.loads(path.read_text())
        except ValueError:
            log.error(
                "Existing %s is not valid JSON; leaving it untouched. "
                "Add the server yourself: %s",
                path,
                url,
            )
            return url
        if not isinstance(config, dict):
            config = {}
    servers = config.setdefault("mcpServers", {})
    servers[name] = {"type": "http", "url": url}
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(config, indent=2))
    os.replace(tmp, path)
    return url


def claude_add_command(url: str) -> str:
    """Return the one-line Claude Code command that registers the server."""
    return f"claude mcp add --transport http {SERVER_NAME} {url}"


def codex_cli_command(url: str) -> str:
    """Return the Codex invocation wiring the server for one session only."""
    return f'codex -c mcp_servers.{SERVER_NAME}.url="{url}"'


def codex_config_toml(url: str) -> str:
    """Return the ``~/.codex/config.toml`` block that registers the server."""
    return f'[mcp_servers.{SERVER_NAME}]\nurl = "{url}"'


__all__ = (
    "claude_add_command",
    "codex_cli_command",
    "codex_config_toml",
    "mcp_url",
    "write_mcp_config",
)
