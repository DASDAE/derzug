"""
DerZug test_widgets.

Deliberately empty of imports: importing a widget module must not drag
``derzug.views`` (and the whole canvas) along with it. Signal summaries are
registered by ``derzug.views.orange``, which owns the canvas that displays
them.
"""
