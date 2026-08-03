# The node layer

`derzug.nodes` is the Qt-free node library. It answers "what is this node, and
how does it run?" without importing Qt, Orange, or `derzug.widgets`, so a
headless host — a server, a notebook, eventually a browser — can introspect a
node type and execute its task with no display attached.

## Layering

```
models  ->  workflow  ->  nodes  ->  { core, widgets, views, conductor }
                                      ^ Qt lives only here
```

`derzug.workflow` is the execution engine (tasks, graphs, the streaming
executor). `derzug.nodes` is the node library built on top of it. Everything to
the right of `nodes` may import everything to its left; nothing to the left may
import anything to its right. `tests/test_nodes/test_import_layering.py`
enforces this in fresh subprocesses — the suite's own `QApplication` would make
an in-process check meaningless.

## What a node module owns

One node is one module under `src/derzug/nodes/`:

- its `Task` subclass(es), which is where serialized pipes resolve their
  `module:qualname` code paths;
- its pydantic parameter model (and view model, for visual nodes);
- a factory mapping params onto the workflow object the node runs;
- a module-level `NODE_SPEC` (or `NODE_SPECS`) tying those together.

```python
NODE_SPEC = NodeSpec(
    name="Taper",
    widget_qualified_name="derzug.widgets.taper.Taper",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=TaperParams,
    task_factory=taper_task_from_params,
    category="Processing",
    ...
)
```

`PortSpec.name` is the workflow port name (and the widget attribute holding the
Orange signal); `display_name` is what the canvas shows. `context_only=True`
marks a port that configures the widget but takes no part in the compiled
graph.

A factory takes a params instance *or* `None`, which means "the node's
defaults". Each factory owns its own default handling, because a discriminated
union — Filter's `kind` — has no single default member a generic helper could
construct. View-only nodes leave `task_factory=None`; `build_task()` then
raises rather than returning `None`.

## Discovery

Node modules advertise themselves through the `derzug.nodes` entry-point group,
mirroring the `derzug.widgets` group Orange's canvas uses:

```toml
[project.entry-points."derzug.nodes"]
Filter = "derzug.nodes.filter"
Taper = "derzug.nodes.taper"
```

`load_node_specs()` loads them DerZug-first (external providers keep working),
validates each, and rejects duplicate names or widget qualified names. Adding
an entry point needs a re-install (`uv pip install -e .`) before
`importlib.metadata` can see it.

## How the widget consumes it

A migrated widget sets `node_spec = NODE_SPEC` and stops declaring the fields
the spec already carries; `ZugWidget.__init_subclass__` copies `params_model`,
`view_model`, and `is_source` across unless the widget overrides them itself.
The widget keeps its Orange `Inputs`/`Outputs` classes and handlers — zero
canvas churn — and `TestWidgetDefaults.test_node_spec_consistency` asserts the
two halves stay in step.

`get_task()` on a migrated widget coerces its controls and then delegates:

```python
params = self.get_params()
return self.node_spec.build_task(params)
```

Widgets with no `node_spec` yet keep their existing path unchanged.

## Writing a new node

1. Write `src/derzug/nodes/<name>.py`: task, params model, factory, `NODE_SPEC`.
2. Register it under `[project.entry-points."derzug.nodes"]` and re-install.
3. Point the widget at it: `node_spec = NODE_SPEC`, delete the duplicated
   `params_model` / task assembly.
4. `pytest tests/test_nodes tests/test_widgets/test_<name>.py`.

The node module must import nothing from `derzug.widgets`, `derzug.core`,
`derzug.views`, or `derzug.conductor`. If a task needs behavior that currently
lives on a widget, move that behavior down into the node module as a free
function and have the widget call it — that direction is the whole point.
