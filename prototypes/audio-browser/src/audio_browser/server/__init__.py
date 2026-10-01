"""HTTP API over the content-addressed index.

The client never sends a filesystem path. It sends a hash; the server looks the
path up in the database. That inversion is the whole defence against path
traversal, and it holds on every route.
"""

from __future__ import annotations

from .app import create_app, run

__all__ = ["create_app", "run"]
