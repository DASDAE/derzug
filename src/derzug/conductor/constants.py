"""Shared defaults for the DerZug Conductor transport."""

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 4319

#: The MCP server entry name clients see (``.mcp.json`` key / Codex table name).
SERVER_NAME = "derzug-conductor"

__all__ = ("DEFAULT_HOST", "DEFAULT_PORT", "SERVER_NAME")
