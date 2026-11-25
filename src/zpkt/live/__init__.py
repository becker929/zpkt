"""zpkt.live: driving Ableton Live (until 24 Nov 2026 the `hands` package; `import hands` still works).

The LOM client, the GUI helpers and the operations built on them. Nothing here touches Live at import. Every
operation takes a LiveClient (or a test double), and the GUI side goes through `ui`, so tests replace both.
"""

__version__ = "0.1.0"
