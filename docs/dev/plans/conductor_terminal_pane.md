# Conductor Terminal Pane (prototype plan)

## Summary

Give the Conductor an in-window home: a **terminal pane docked inside the DerZug
canvas** where the user runs their own agent CLI (e.g. Claude Code), already
wired to the in-app MCP server. This delivers the "chat next to the live canvas"
experience *without* DerZug taking on any model-provider, API-key, or billing
dependency — the pane is just a shell, the agent is the user's own client, and
the transport is the MCP server we already built (`derzug --conductor`).

Branch base: `main` (continuing on `feature/conductor-mcp`).

## Why this shape

- **No model/credential burden.** DerZug never talks to a model; the user's agent
  (with their own auth) runs in the terminal and drives the canvas over MCP.
- **Agent-agnostic + decoupled.** Any MCP-speaking CLI works; the agent is a
  separate process, so if it dies the canvas is unaffected.
- **Reuses what exists.** The MCP server, `MainThreadDispatcher`, and undoable
  edits are done. This prototype is purely the UX shell + connection ergonomics.

## The one real cost

Claude Code is a **rich interactive TUI** (streaming, live prompt, keybindings),
so the pane can't be a naive "run command, print stdout" box — it needs a genuine
embedded terminal emulator: a **pty** (ConPTY on Windows) plus ANSI/TUI
rendering. That is the load-bearing engineering piece.

## Approach & phasing

Phase the risk: prove the connection ergonomics first, then invest in the
emulator.

**Prototype step 1 — auto-wired external terminal (lowest risk).**
- On `derzug --conductor`, we already start the MCP server and write `.mcp.json`.
- Add a **Conductor menu/toolbar action** ("Open agent terminal") that launches
  the user's *system* terminal in the workflow directory (where `.mcp.json`
  lives) so `claude` auto-connects. No embedded rendering yet.
- Ships a usable end-to-end demo immediately; validates the "it just connects"
  ergonomics.

**Prototype step 2 — docked terminal pane (the real thing).**
- Add a `QDockWidget` (or a panel in the main window) hosting an embedded
  terminal emulator running a shell (and optionally auto-launching the agent).
- Emulator options to evaluate: a `pyte`-based renderer over a `QWidget`, or
  vendoring `qtermwidget`. Must handle a pty on POSIX and ConPTY on Windows.
- The environment/cwd is pre-set so the agent auto-connects to the MCP server.

**Prototype step 3 — polish.**
- Start/stop the shell with the pane; kill the process on close.
- Ensure DerZug global shortcuts (F, Esc, Ctrl+Q) don't fight the terminal while
  it has keyboard focus.
- Status indicator (server running / client connected) and an optional
  agent-activity log.

## Components / files

| File | Role |
|---|---|
| `src/derzug/conductor/terminal.py` | The terminal pane widget (pty + emulator + shell process lifecycle). |
| `src/derzug/views/orange.py` | Menu/toolbar action to open the pane / external terminal; dock it into the main window; gate behind `--conductor`. |
| `src/derzug/conductor/mcp_server.py` | Already writes `.mcp.json`; may add a helper to resolve the agent launch command/cwd. |
| `docs/dev/conductor.md` | Update the demo once the pane exists. |

## Open questions

1. **Embedded emulator vs. external terminal for v1** — ship step 1 (external,
   auto-wired) first, or go straight to the docked emulator? (Recommend step 1
   first.)
2. **Emulator implementation** — `pyte`+QWidget (vendor-light, more work) vs.
   `qtermwidget` (heavier dep, less work). Evaluate cross-platform + packaging.
3. **Auto-launch the agent?** — open a bare shell, or auto-run `claude` in the
   pane. (Bare shell is safer/more flexible for v1.)
4. **Windows** — ConPTY support is the main portability risk; validate early.

## Testing

- Unit: the launch-command/config helpers (cwd, `.mcp.json` presence) are pure
  and testable; the emulator/pty is integration-level and largely manual.
- Manual: `derzug --conductor`, open the pane, run `claude`, confirm it connects
  and can drive the canvas; confirm `Ctrl+Z` still reverts agent edits and global
  shortcuts behave when the terminal has focus.
- Keep any Qt/pty rendering out of the headless CI path (guard/skip), matching
  how the MCP server tests are optional.
