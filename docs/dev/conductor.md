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

2. Start DerZug with the Conductor server:

   ```bash
   derzug --conductor
   ```

   This starts an MCP server on `http://127.0.0.1:4319/mcp` and merges a
   `derzug-conductor` entry into the `.mcp.json` in the current directory
   (other entries in an existing file are preserved; the file is gitignored).
   A port conflict or startup failure is reported immediately, and the server
   shuts down with the application.

3. From that directory, start your agent (Claude Code picks up `.mcp.json`):

   ```bash
   claude
   ```

   Or let DerZug launch it for you in a new terminal, pre-wired:

   ```bash
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

## Trust model

The server binds loopback only (`127.0.0.1`) and has no authentication: any
local process can connect, so local clients are trusted by design. The **Code**
widget — whose parameters are executable Python — is excluded from the agent
surface (hidden from the catalog; add/configure rejected) unless you opt in:

```bash
derzug --conductor --conductor-allow-code
```

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
  the dispatcher) and owns its lifecycle via `ConductorService`: the port is
  pre-bound (a conflict raises at startup), readiness is awaited before the
  client config is written or an agent launched, and the service stops on
  application teardown. Imported only when `--conductor` is used, so the core
  app never depends on `mcp`.
- `conductor/launch.py` — agent launch helpers: the per-agent connect command
  and the cross-platform "open a terminal" spawn.
