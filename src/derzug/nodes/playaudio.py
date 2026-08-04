"""The PlayAudio node: audition a 1D time patch, passing it through unchanged.

Playback is a display concern, so the parameters here describe the audition
only; the compiled workflow just forwards the patch.
"""

from __future__ import annotations

import dascore as dc
from pydantic import BaseModel

from derzug.nodes.spec import NodeSpec, PortSpec
from derzug.workflow.widget_tasks import PatchPassThroughTask


class PlayAudioParams(BaseModel):
    """Parameters for the PlayAudio node."""

    time_scale: float = 1.0
    volume_percent: int = 100


def playaudio_task_from_params(
    params: PlayAudioParams | None = None,
) -> PatchPassThroughTask:
    """Build the pass-through task the player contributes to a workflow."""
    return PatchPassThroughTask()


NODE_SPEC = NodeSpec(
    name="PlayAudio",
    widget_qualified_name="derzug.widgets.playaudio.PlayAudio",
    inputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    outputs=(PortSpec(name="patch", display_name="Patch", type=dc.Patch),),
    params_model=PlayAudioParams,
    task_factory=playaudio_task_from_params,
    category="Visualize",
    description="Play a 1D time patch as audio",
    keywords=("audio", "sound", "time", "patch"),
    icon="icons/PlayAudio.svg",
    priority=23,
)
