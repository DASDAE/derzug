# Add `--dev` Hot Reload Mode to DerZug

## Summary

Add a dedicated development mode enabled by `derzug --dev`. In dev mode only,
DerZug shows a right-aligned `Dev` menu and a matching toolbar action for
`Hot Reload`, bound to `Ctrl+Shift+R`. Triggering hot reload performs a full
process restart, preserving dev mode and reopening the current workflow when
possible.

## Key Changes

- Extend `derzug.cli` with a `--dev` flag.
  - Pass this through to `DerZugMain` as an explicit `dev_mode` boolean.
  - Ensure restart always relaunches with `--dev` when the current session is in
    dev mode.
- Teach `DerZugMain` and `DerZugMainWindow` about dev mode.
  - Store `dev_mode` on the runner and window.
  - Only install dev controls, menu, and shortcut when `dev_mode` is true.
  - In non-dev mode, there is no visible Dev menu, no toolbar action, and
    `Ctrl+Shift+R` does nothing.
- Add a dedicated `Dev` menu to the far right of the main menu bar.
  - Use `QMenuBar.setCornerWidget(...)` with a small menu button anchored in the
    top-right corner.
  - The Dev menu contains `Hot Reload`.
  - Also add the same action to the canvas toolbar for easy access during
    development.
- Bind `Ctrl+Shift+R` to `Hot Reload` only in dev mode.
  - Implement this as a main-window action with the shortcut attached.
- Implement hot reload as a full restart.
  - Do not attempt in-process module reload.
  - Build the restart command from `sys.executable -m derzug.cli`.
  - Include the current workflow path if one is open from disk.
  - Include `--demo` only if the session started in demo mode and there is no
    workflow file to reopen.
  - Always include `--dev` for a dev-mode restart.
- Handle unsaved workflows safely before restart.
  - If the current workflow is modified, prompt save, discard, or cancel.
  - On save, use existing `save_scheme` and `save_scheme_as` flow and continue
    only if the save succeeded and produced a real workflow path.
  - On discard, restart without saving.
  - On cancel, abort hot reload.
  - Do not write temporary workflow snapshots in v1.
- If restart spawning fails:
  - keep the current app running
  - show a visible error or warning
  - do not close any windows

## Public / UI Interface Changes

- New CLI flag: `derzug --dev`
- New dev-only UI:
  - right-aligned `Dev` menu
  - `Hot Reload` action inside that menu
  - toolbar button for `Hot Reload`
- New dev-only shortcut:
  - `Ctrl+Shift+R`

## Test Plan

Add coverage for:

- CLI:
  - `--dev` is accepted and sets runner dev mode.
- Main window UI:
  - Dev menu and toolbar action are absent in normal mode.
  - Dev menu and toolbar action appear in dev mode.
  - Dev menu is attached via the menu bar's right-side corner widget path.
  - hot reload action has shortcut `Ctrl+Shift+R`.
- Behavior:
  - shortcut and action do nothing in non-dev mode.
  - dev-mode reload restarts with `--dev`.
  - reload preserves current workflow path when one exists.
  - modified workflow prompts save, discard, or cancel.
  - save path restarts with saved workflow path.
  - discard path restarts without saving.
  - cancel path aborts restart.
  - spawn failure leaves app open and reports the failure.

## Assumptions

- Dev mode is enabled only by `--dev`.
- "Far right" means implemented using the menu bar corner-widget area rather
  than relying on platform-dependent action ordering.
- Full restart is the only supported reload behavior in v1.
