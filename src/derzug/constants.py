"""
Constants for derzug.
"""

from pathlib import Path

# The entry point name for derzug test_widgets and orange test_widgets.
WIDGETS_ENTRY = "derzug.widgets"

# The entry point name for Qt-free node specs (see derzug.nodes.registry).
NODES_ENTRY = "derzug.nodes"
# The name of orange test_widgets to explicitly keep.
ORANGE_WIDGETS_TO_LOAD = ()

# Significant figures used for programmatic UI display of floating values.
DISPLAY_SIGFIGS = 3

# The name of this package.
PKG_NAME = Path(__file__).parent.name
