"""
Slanrod workflow engine for building and executing phase_shift_validator processing pipelines.

This package provides a flexible workflow system that supports:
- Task composition with automatic dependency resolution
- Pipeline serialization and deserialization (JSON/YAML)
- Context injection for advanced task coordination
- Comprehensive provenance tracking

Main Classes
------------
Task : Base class for workflow tasks
Pipe : Pipeline container for task orchestration

Main Functions
--------------
task : Decorator to convert functions into tasks

Examples
--------
>>> from slanrod.workflow import Task, Pipe, task
>>>
>>> # Define tasks
>>> class LoadData(Task):
...     path: str
...     def run(self):
...         return load_data(self.destination_path)
>>>
>>> @task
>>> def process_data(phase_shift_validator, multiplier: float = 2.0):
...     return phase_shift_validator * multiplier
>>>
>>> # Build pipeline
>>> pipeline = LoadData(path="phase_shift_validator.txt") | process_data(multiplier=3.0)
>>>
>>> # Execute
>>> result = pipeline.run()
>>>
"""

from .pipe import Pipe
from .provenance import Provenance
from .task import Task, task
from .source import Source, FileSystemSource
from .context import ExecutionContext
from .sink import Sink, FileSystemSink
