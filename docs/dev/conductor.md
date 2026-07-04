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

   This starts an MCP server on `http://127.0.0.1:4319/mcp` and writes an
   `.mcp.json` in the current directory so a client auto-connects.

3. From that directory, start your agent (Claude Code picks up `.mcp.json`):

   ```bash
   claude
   ```

   Or let DerZug launch it for you in a new terminal, pre-wired:

   ```bash
   derzug --agent claude   # or: derzug --agent codex
   ```

   `--agent` implies `--conductor`. `claude` connects via the `.mcp.json`;
   `codex` is bridged to the HTTP server through `mcp-remote` (a
   `[mcp_servers.derzug-conductor]` entry is added to `~/.codex/config.toml`,
   which needs `npx` at runtime).

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
  the widget's model, returning the prior state).
- **Author** — `add_node` (auto-placed compactly when x/y are omitted),
  `remove_node`, `connect`, `disconnect`, `run`.
- **Windows** — `show_node` (pop up / raise / focus a widget window, optionally at
  screen x/y), `move_node_window`, `hide_node`.

An agent's loop is: discover the schemas → read the graph → add/connect nodes →
configure them → run. `get_focus` reports what the user is looking at and
pointing to, so commands can be contextual ("filter *this* node").

## Architecture

- `conductor/controller.py` — `CanvasController`, the main-thread surface over the
  live scheme (reuses the same primitives the app uses to read, edit, compile,
  and set widget state). Graph edits go on the document undo stack; parameter
  changes return the prior for programmatic undo.
- `conductor/dispatch.py` — `MainThreadDispatcher`, marshals off-thread calls onto
  the Qt main thread and blocks for the result.
- `conductor/mcp_server.py` — builds the FastMCP server (tools wrapped through the
  dispatcher), serves it over streamable-http, and writes the client config.
  Imported only when `--conductor` is used, so the core app never depends on
  `mcp`.
