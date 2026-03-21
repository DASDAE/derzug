import sys

from setuptools import setup

# Only install Linux freedesktop.org integration files on Linux.
# On Windows/macOS these paths are meaningless; runtime installation is
# handled by ensure_linux_desktop_entry() in derzug.views.orange.
_data_files = []
if sys.platform.startswith("linux"):
    _data_files = [
        ("share/applications", ["resources/linux/derzug.desktop"]),
        (
            "share/icons/hicolor/64x64/apps",
            ["resources/linux/icons/hicolor/64x64/apps/derzug.png"],
        ),
        (
            "share/icons/hicolor/128x128/apps",
            ["resources/linux/icons/hicolor/128x128/apps/derzug.png"],
        ),
        (
            "share/icons/hicolor/256x256/apps",
            ["resources/linux/icons/hicolor/256x256/apps/derzug.png"],
        ),
        (
            "share/icons/hicolor/512x512/apps",
            ["resources/linux/icons/hicolor/512x512/apps/derzug.png"],
        ),
    ]

setup(data_files=_data_files)
