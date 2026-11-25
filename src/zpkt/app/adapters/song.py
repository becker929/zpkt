"""The Song adapter: the arranger's pages and routes under /app/song, and the commands that save and build the recipe.

It mounts the arranger on the web server's mount table and puts the `song.*` commands on the bus. It is an adapter
because it is one more way in: the old arranger server on :8975 stays as it is. Like every adapter it asks Live for
nothing itself: `song.build` goes through the bus, which holds the lock and runs the checks.
"""

from __future__ import annotations

from zpkt.app import song
from zpkt.app.adapters import AdapterSpec, AppContext


class SongAdapter:
    """Mounts the arranger at /app/song and registers the Song's commands."""

    name = "song"

    def __init__(self, context: AppContext, settings: song.SongSettings | None = None) -> None:
        self.context = context
        self.settings = settings
        self.service: song.Song | None = None

    def start(self) -> None:
        settings = self.settings or song.SongSettings.from_env()
        self.service = song.Song(settings)
        song.register(self.context.bus, self.service, self.context.desk.conn)
        self.context.desk.mounts.add(song.PREFIX, song.SongMount(self.service, self.context.bus))

    def stop(self) -> None:
        self.context.desk.mounts.remove(song.PREFIX)


def make(context: AppContext) -> SongAdapter:
    return SongAdapter(context)


ADAPTER = AdapterSpec("song", make)
