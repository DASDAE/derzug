"""Launch an agent CLI in a terminal, wired to the Conductor MCP server.

Pure process/config helpers with no ``mcp`` dependency: build the launch
command for a known agent, and best-effort open it in a new terminal window.
"""

from __future__ import annotations

import logging
import shlex
import shutil
import subprocess
import sys

log = logging.getLogger(__name__)

#: The MCP server entry name clients see (``.mcp.json`` key / Codex table name).
SERVER_NAME = "derzug-conductor"


def agent_command(agent: str, url: str) -> list[str]:
    """Return the command that starts ``agent`` connected to the server at ``url``.

    ``claude`` needs no arguments: Claude Code picks up the ``.mcp.json`` in the
    launch directory. ``codex`` supports streamable-HTTP MCP servers natively;
    a per-invocation ``-c`` override wires it without touching the user's
    ``~/.codex/config.toml``. Unknown agents are launched bare.
    """
    if agent == "codex":
        return ["codex", "-c", f'mcp_servers.{SERVER_NAME}.url="{url}"']
    return [agent]


def _open_in_terminal(command: list[str], cwd: str) -> bool:
    """Best-effort: open a new terminal window running ``command`` in ``cwd``."""
    joined = " ".join(shlex.quote(part) for part in command)

    def _spawn(argv: list[str], spawn_cwd: str | None = None) -> bool:
        try:
            subprocess.Popen(argv, cwd=spawn_cwd)
            return True
        except Exception:
            log.error("Failed to launch terminal: %s", argv, exc_info=True)
            return False

    if sys.platform == "darwin":
        script = (
            f'tell application "Terminal" to do script '
            f'"cd {shlex.quote(cwd)} && exec {joined}"'
        )
        return _spawn(["osascript", "-e", script])
    if sys.platform == "win32":
        if shutil.which("wt"):
            return _spawn(["wt", "-d", cwd, *command])
        return _spawn(["cmd", "/c", "start", "", "cmd", "/k", joined], spawn_cwd=cwd)
    for term in ("x-terminal-emulator", "gnome-terminal", "konsole", "xterm"):
        exe = shutil.which(term)
        if exe is None:
            continue
        if term == "gnome-terminal":
            return _spawn([exe, "--working-directory", cwd, "--", *command])
        # xterm/konsole-style launchers take the executable and each argument
        # separately after ``-e``. Passing one shell-joined string makes a
        # multi-argument command (notably Codex's ``-c`` override) look like a
        # single nonexistent executable.
        return _spawn([exe, "-e", *command], spawn_cwd=cwd)
    log.error("No terminal emulator found; run '%s' in %s yourself", joined, cwd)
    return False


def launch_agent_in_terminal(agent: str, cwd: str, url: str) -> bool:
    """Launch ``agent`` in a new terminal in ``cwd``, wired to the server at ``url``."""
    command = agent_command(agent, url)
    if shutil.which(command[0]) is None:
        log.error("Agent %r not found on PATH; run it yourself in %s", agent, cwd)
        return False
    return _open_in_terminal(command, cwd)
