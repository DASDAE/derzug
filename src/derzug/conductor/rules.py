"""Single source of truth for the agent-facing Conductor briefing.

The same text reaches agents three ways: as the FastMCP ``instructions``
handed to every connecting client, through the ``get_derzug_rules`` tool
(the one briefing channel every MCP client supports), and by reference from
the generated skill file — which deliberately points at the tool instead of
duplicating this text, so the briefing can never drift from the running app.
"""

from __future__ import annotations

AGENT_RULES = (
    "Drive a live DerZug DAS (distributed acoustic sensing) workflow "
    "canvas of connected widget nodes.\n\n"
    "COMMON RECIPE (view data): add_node('Spool') -> "
    "set_params(spool_id, {'spool_input': 'example_event_1'}) -> "
    "add_node('Waterfall') -> connect(spool_id, waterfall_id) -> "
    "run(spool_id) -> wait_for_idle().\n\n"
    "CONVENTIONS:\n"
    "- Almost every node has one input port 'Patch' and one output port "
    "'Patch'; connect(source_id, sink_id) defaults to them, so you rarely "
    "need port names.\n"
    "- Omit x/y on add_node; nodes auto-place in a tidy left-to-right "
    "row.\n"
    "- set_params/set_view take PARTIAL updates, are validated against the "
    "node's schema, and return the prior value. They do NOT re-run the "
    "node by default: assemble and configure the graph first, then call "
    "run(source_id) once and wait_for_idle().\n"
    "- run() only schedules execution; wait_for_idle() blocks until no "
    "node is busy (each node also reports a 'busy' flag).\n"
    "- Structural edits (add/remove/connect) are undoable in the app "
    "(Ctrl+Z).\n"
    "- show_node pops up a node's widget window to display results.\n"
    "- The running app is the source of truth: never edit its workflow "
    "files behind its back; drive changes through these tools.\n\n"
    "DISCOVERY: list_widget_types = the catalog with each type's "
    "params/view schema; get_canvas_state = the current graph; "
    "describe_node = one node's detail incl. its output patch shape.\n\n"
    "COMMON NODE TYPES: Spool (source; loads data/examples), Filter "
    "(bandpass etc.), Waterfall (2D image view), Wiggle (trace view), "
    "Detrend, Taper, Resample, Select, Aggregate. See list_widget_types "
    "for the full set and parameters."
)

__all__ = ("AGENT_RULES",)
