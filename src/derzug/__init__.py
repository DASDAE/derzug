"""derzug package."""

def __getattr__(name: str):
    """Provide lazy access to workflow symbols expected at package top level."""
    if name in {
        "ExecutionContext",
        "FileSystemSink",
        "FileSystemSource",
        "Pipe",
        "Provenance",
        "Sink",
        "Source",
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
