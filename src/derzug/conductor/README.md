# DerZug Conductor

The Conductor is a programmatic, agent-facing view of a **live** DerZug canvas.
It lets an external agent (or any code) observe a running workflow: the node and
link graph, the placeable widget types, per-node detail, and what the user is
currently looking at and pointing to.

> **Status: Phase 1 — read-only.** Mutations (add / connect / configure / run)
> and the MCP transport that will expose these tools to an agent are planned;
> see the roadmap below. This package currently adds no runtime dependencies.

## Usage

```python
from derzug.conductor import CanvasController

controller = CanvasController(main_window)   # a live DerZugMainWindow
state = controller.get_canvas_state()
print(state.model_dump())                    # agent-ready JSON
```

Every method returns a pydantic model (or a plain dict) whose `.model_dump()`
yields JSON — no Qt or Orange objects leak through, so the output is safe to
hand straight to an agent.

## Observation API

| Method | Returns | Purpose |
|---|---|---|
| `get_canvas_state()` | `CanvasState` | Whole-graph snapshot: nodes (id, type, title, category, position, typed `params` + `view` state, typed ports, `is_source`, `is_active_source`, error) + links (source/sink id + port, enabled) + the active-source id. |
| `list_widget_types()` | `list[WidgetTypeInfo]` | The placeable widget catalog from the window's registry (name, qualified name, category, description, keywords, typed ports, and JSON `params_schema` / `view_schema` for discovering valid parameters up front). |
| `describe_node(node_id)` | `NodeDetail` | One node's full state plus a best-effort input-patch summary (`{"shape": [...], "dims": [...]}`). |
| `compile_check()` | `dict` | Whether the current canvas compiles (`compile_workflow`), as `{ok, error, task_count, edge_count}`. |
| `get_focused_node()` | `str \| None` | Id of the node whose widget window is focused, or `None` on the canvas. |
| `get_focus()` | `FocusState` | Shared user/agent context: focused node + window title, and the pointer (`screen_xy`, `over_node_id`, `data_position`). |

## Write API (configure existing nodes)

| Method | Returns | Purpose |
|---|---|---|
| `set_params(node_id, params, run=True)` | `dict` | Apply typed parameters (a `params_model` or its dict) to one node, validated against the model. Returns the prior params so the change can be undone by re-applying them. |
| `set_view(node_id, view, run=False)` | `dict` | Same, for a visual widget's `view_model` (colormap, view range, ...). Returns the prior view state. |

Graph authoring (`add_node` / `remove_node` / `connect` / `run`) and undo-stack
integration land next; see the roadmap below.

Node ids prefer the persisted DerZug node id (`__derzug_node_id`) when present
and otherwise fall back to a session-stable object id.

## Widget extension point: `conductor_cursor_readout()`

`get_focus()` reports a **data-space** pointer position (`cursor.data_position`)
for the widget under the cursor — e.g. `{"time": ..., "distance": ..., "value":
...}` — so an agent knows exactly what the user is pointing at, not just screen
coordinates.

A widget opts in by implementing:

```python
def conductor_cursor_readout(self) -> dict | None:
    """Return the coordinate/value under the pointer, or None when unavailable."""
```

Until a widget implements it, `data_position` is `None`. Failures in the hook
are swallowed (they yield `None`), so a broken readout never breaks observation.
The plotting widgets (Waterfall, Wiggle) already compute this for their on-plot
cursor label; wiring that value through this hook is a planned follow-up.

## Threading

Phase 1 is read-only and expected to be called on the **Qt main thread** — it
reads live scheme and widget state directly. When an off-thread transport (the
MCP server) is added, calls will be marshalled onto the main thread; no scheme
access ever happens off-thread.

## Roadmap

1. **(done) Observe** — the read-only surface above.
2. **Author** — `add_node` / `remove_node` / `connect` / `set_params` / `run`,
   each an Orange undo-stack transaction (revertible with Ctrl+Z), with
   destructive / Code-widget operations gated.
3. **Transport** — an in-app MCP server exposing these as tools over localhost,
   plus a main-thread dispatch layer; an external agent client drives the canvas.
4. **Richer observation** — real per-node output summaries, live cursor readouts
   via the hook above, and focus/pointer change events.
