"""derzug package."""
import os

# Explicitly use pyqt6 here. Because, newwer is better right?
os.environ.setdefault("QT_API", "pyqt6")

# Just the bit of code for debugging.
#from PyQt6.QtCore import pyqtRemoveInputHook
#pyqtRemoveInputHook()
#breakpoint()
