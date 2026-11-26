"""The Listen adapter: Live's own output, streamed to the browser, under /app/listen.

It mounts the status, the stream and the page's script. Starting it does nothing else: the capture tool is built and
run only when a page asks, and a Mac that cannot capture just answers "unavailable" with the reason. It sends no
Command and never reaches Live: it only hears what Live plays.
"""

from __future__ import annotations

from zpkt.app.adapters import AdapterSpec, AppContext
from zpkt.app.listen import PREFIX
from zpkt.app.listen.capture import Source, SwiftCapture
from zpkt.app.listen.hub import Hub
from zpkt.app.listen.routes import ListenMount


class ListenAdapter:
    name = "listen"

    def __init__(self, context: AppContext, source: Source | None = None, linger: float = 5.0) -> None:
        self.context = context
        self.hub = Hub(source or SwiftCapture(), linger=linger)

    def start(self) -> None:
        self.context.desk.mounts.add(PREFIX, ListenMount(self.hub))

    def stop(self) -> None:
        self.context.desk.mounts.remove(PREFIX)
        self.hub.stop()


def make(context: AppContext) -> ListenAdapter:
    return ListenAdapter(context)


ADAPTER = AdapterSpec("listen", make)
