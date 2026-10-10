"""Driving Ableton Live: the LOM client, the GUI helpers and the operations built on them.

Nothing here touches Live at import. Every operation takes a LiveClient (or a test double), and
the GUI side goes through `ui`, so tests replace both.
"""
