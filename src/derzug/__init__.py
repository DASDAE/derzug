"""derzug package."""

def __getattr__(name: str):
    """Provide lazy access to workflow symbols expected at package top level."""
    if name in {
        "CompiledWorkflow",
        "compile_workflow",
        "FileSystemSource",
        "Pipe",
        "PipeBuilder",
        "Provenance",
        "Results",
        "Source",
        "STREAM_END",
        "Task",
        "task",
    }:
        from derzug import workflow as _workflow

        return getattr(_workflow, name)
    raise AttributeError(name)

# Just the bit of code for debugging.
#from PyQt6.QtCore import pyqtRemoveInputHook
#pyqtRemoveInputHook()
#breakpoint()
