# Conductor: agent control of the live canvas

The **Conductor** lets an agent observe and drive a running DerZug canvas over
[MCP](https://modelcontextprotocol.io). DerZug hosts an in-app MCP server; you
connect your own agent client (e.g. Claude Code) to it, and the canvas updates
live as the agent works. Because the agent is your own client, DerZug never
handles model credentials.

## Run the demo

1. Install the optional extra:

   ```bash
   pip install '.[conductor]'
   ```

2. Start DerZug:

   ```bash
   derzug
   ```

   Open the **Conductor** menu and choose **Start Server**. The status entry
   reports the active MCP URL (by default `http://127.0.0.1:4319/mcp`). Starting
   the server merges a `derzug-conductor` entry into the `.mcp.json` in the
   current directory; other entries are preserved and the file is gitignored.

3. Choose **Conductor → Connect Agent...** (or **Open Agent → Claude Code / Codex** directly). Launching an agent while the server is stopped starts it automatically and connects the agent once it is ready. The Connect Agent dialog also shows copy-paste setup for each client — the `claude mcp add --transport http derzug-conductor <url>` one-liner, the Codex `-c` override and `config.toml` block, and the raw MCP URL — for wiring an agent you run yourself. You can also start an agent from the directory containing `.mcp.json` (Claude Code picks it up automatically):

   ```bash
   claude
   ```

   For automation or the previous one-command workflow, the CLI flags remain
   available:

   ```bash
   derzug --conductor
   derzug --agent claude   # or: derzug --agent codex
   ```

   `--agent` implies `--conductor`. `claude` connects via the `.mcp.json`;
   `codex` connects to the HTTP server natively via a per-invocation config
   override (`codex -c mcp_servers.derzug-conductor.url=...`), so your
   `~/.codex/config.toml` is never modified.

4. Ask it to build a pipeline, e.g.:

   > Load the `example_event_1` spool, bandpass filter it 5–40 Hz, and show a
   > waterfall.

   Watch the nodes appear, wire up, and render on the canvas. Structural edits
   (added/removed/connected nodes) are on the app's undo stack — press **Ctrl+Z**
   to revert an agent action.

## Tool surface

The server exposes the `CanvasController` as MCP tools:

- **Observe** — `get_canvas_state`, `list_widget_types` (with each type's params/
  view JSON schema), `describe_node`, `compile_check`, `get_focus`.
- **Configure** — `set_params`, `set_view` (partial updates, validated against
  the widget's model, returning the prior state; no implicit re-run).
- **Author** — `add_node` (auto-placed compactly when x/y are omitted),
  `remove_node`, `connect`, `disconnect`, `run` (schedules an async execution),
  `wait_for_idle` (blocks until no node is busy; each node reports a `busy`
  flag).
- **Windows** — `show_node` (pop up / raise / focus a widget window, optionally at
  screen x/y), `move_node_window`, `hide_node`.

An agent's loop is: discover the schemas → read the graph → add/connect nodes →
configure them → run → `wait_for_idle`. `get_focus` reports what the user is
looking at and pointing to, so commands can be contextual ("filter *this*
node").

The briefing itself has one source, `conductor/rules.py`, and reaches agents three ways: the FastMCP `instructions` every client loads, the `get_derzug_rules` tool (returns the rules plus the running server's version, id, and URL — the only briefing channel Codex supports, since it ignores MCP prompts), and a `connect` prompt that Claude Code surfaces as `/mcp__derzug-conductor__connect`.

## Discovery and the agent skill

Every ready server advertises itself for discovery: it writes one JSON record (`server_id`, `pid`, `port`, `base_url`, `mcp_url`, `started_at`, `version`) into the per-user state directory — `$XDG_STATE_HOME/derzug/servers` (default `~/.local/state/derzug/servers`), `%LOCALAPPDATA%\derzug\servers` on Windows — and removes it on stop. Records left by a crash are pruned by a pid probe plus a `GET /health` check, which must answer `healthy` with a matching `server_id`. `python -m derzug.conductor.registry` prints the live servers as JSON.

Starting the server also writes a `derzug-conductor` skill into `.claude/skills/` and `.agents/skills/` next to the `.mcp.json`, teaching an agent the discovery procedure, the per-client connect commands, and the workflow shape; for the full briefing it defers to `get_derzug_rules`, so it cannot drift from the running app. A skill file is only overwritten while it still carries its generated marker — edit it (removing the marker) and DerZug leaves it alone.

## Trust model

The server binds loopback only (`127.0.0.1`) and has no authentication: any
local process can connect, so local clients are trusted by design. Requests
whose `Host` header is not a loopback name are rejected (400), so a hostile
web page cannot reach the server through DNS rebinding. The **Code**
widget — whose parameters are executable Python — is excluded from the agent
surface (hidden from the catalog; add/configure rejected) unless you opt in:

```bash
derzug --conductor --conductor-allow-code
```

You can also opt in for the current session through **Conductor → Settings...**.
The menu does not persist this permission.

## Menu controls

The **Conductor** menu remains available whether the server is running or not:

- **Connect Agent...** opens the non-modal connection dialog (status, per-client setup snippets, launch buttons). It and **Open Agent** work while the server is stopped: launching an agent starts the server automatically first.
- **Start Server**, **Stop Server**, and **Restart Server** own the service
  lifecycle. Closing DerZug also stops the service.
- **Copy MCP URL** is enabled only while the server is running.
- **Settings...** configures the port and the Code-widget permission. The port
  is remembered across launches. The arbitrary-code permission is deliberately
  session-only and defaults to off each time DerZug starts. Changes made while
  the server is running take effect after **Restart Server (Apply Settings)**.

Starts and stops are asynchronous: the menu shows the transient **Starting...**/**Stopping...** states while the GUI stays responsive, and only a port conflict or a missing dependency is reported synchronously. The host is fixed to loopback (`127.0.0.1`). Port conflicts, missing optional dependencies, and agent-launch failures are reported in the UI and leave the menu in a usable state. If a shutdown times out the server keeps its port, so the menu stays in the running state and **Restart Server** is refused rather than racing the old server for the port; **Stop Server** can be retried.

## Architecture

- `conductor/controller.py` — `CanvasController`, the main-thread surface over the
  live scheme (reuses the same primitives the app uses to read, edit, compile,
  and set widget state). Graph edits go on the document undo stack; parameter
  changes return the prior for programmatic undo.
- `conductor/dispatch.py` — `MainThreadDispatcher`, marshals off-thread calls onto
  the Qt main thread and blocks for the result, with a timeout (so a blocked
  main thread fails the call instead of hanging the client) and a stopped state
  used at shutdown.
- `conductor/mcp_server.py` — builds the FastMCP server (tools wrapped through
  the dispatcher, plus `get_derzug_rules`, the `connect` prompt, and the
  `/health` route) and owns the process-side lifecycle via `ConductorService`:
  the port is pre-bound on the calling thread (a conflict raises immediately),
  `launch` serves in a background thread, and `status`/`is_stopped` expose the
  transitions for polling. Imported only when the server is started, so the
  core app never depends on `mcp`.
- `conductor/lifecycle.py` — `ConductorLifecycle`, the GUI-side orchestrator: polls service transitions from a `QTimer` (no GUI blocking), reports outcomes through Qt signals, and runs the post-ready side effects — client config, registry record, skill files, pending agent launch.
- `conductor/registry.py` — the stdlib-only discovery registry and `/health` pruning described above.
- `conductor/rules.py` — the single source of the agent briefing.
- `conductor/client_config.py` — stdlib-only `.mcp.json` writer and the per-client connect snippets shown by the dialog.
- `conductor/skill.py` + `conductor/skill_assets/SKILL.md` — the packaged skill and its marker-aware writer.
- `conductor/launch.py` — agent launch helpers: the per-agent connect command
  and the cross-platform "open a terminal" spawn.
- `views/conductor.py` — the always-available menu, lifecycle state display,
  the settings dialog, and the Connect Agent dialog. It has no dependency on
  the optional MCP package.
