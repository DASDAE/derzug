# Conductor Agent Ergonomics (speed up how fast an agent works)

## Problem

An agent is slow to accomplish common tasks because the tool surface is all
primitives: to do anything it must survey every widget type (with full JSON
schemas), inspect ports, then assemble `add_node` → `connect` → `set_params`
from scratch — many round-trips per task, over a heavy discovery payload.

The fix is two layers: a **skill layer** (so it knows the common recipes without
rediscovering them) and **leaner discovery**.

## Planned changes (ranked by bang-for-buck)

### 1. Rich MCP `instructions` — the "skill"  ✅ implemented
FastMCP's `instructions` field loads into the agent's context once, up front. Make
it a real cheat-sheet: the canonical "view data" recipe, conventions (single
`Patch` in/out; omit positions; partial validated `set_params`; edits are
undoable), the discovery tools, and the common node types. Removes most flailing
because the agent follows the recipe instead of discovering the workflow.

### 4. Default `connect` ports to `"Patch"`  ✅ implemented
Reorder the `connect`/`disconnect` tools to `(source_id, sink_id,
source_port="Patch", sink_port="Patch")` so the standard case is `connect(src,
sink)` with no port inspection. (The controller keeps its explicit 4-arg form.)

### 2. High-level "recipe" tools  — pending (blocked on transactionality)
Collapse the common multi-step flows into single calls:
- `add_chain(["Spool","Filter","Waterfall"])` — add the nodes and auto-connect
  them `Patch`→`Patch`; returns the new node ids. ~6 calls → 1.
- `load_example(name)` — the hello-world: `Spool(example)` → `Waterfall`,
  connected + shown. One call to "just show me data."

**Precondition (per review):** implement each recipe as one validated
undo-stack macro (`QUndoStack.beginMacro`/`endMacro`) with rollback on partial
failure. Without that, a recipe failing halfway leaves a half-built workflow
and requires several manual undos. Deferred until the macro plumbing exists.

### 3. Split discovery so the survey is cheap  — pending
`list_widget_types` returns full schemas for every type (heavy upfront payload).
Split into a lean `list_widget_types` (name + one-line purpose + ports only) and
`describe_widget_type(name)` that returns the full param schema only for the type
about to be configured.

## Order

1 + 4 first (tiny, immediate), then 2 (`add_chain`/`load_example`), then 3 if the
payload is still heavy.

## Testing

- 1 + 4: covered by the existing conductor suite (tool registration + a connect
  round-trip with defaulted ports).
- 2: unit tests that `add_chain` builds and links a pipeline that compiles, and
  `load_example` yields a shown, error-free view.
- 3: assert the lean catalog omits schemas and `describe_widget_type` returns them.
