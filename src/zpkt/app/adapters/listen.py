"""The Listen adapter: Live's own output, streamed to the browser, under /app/listen.

It mounts the status, the stream and the page's script. Starting it does nothing else: a capture is started only when
a page asks, and a Mac that cannot capture just answers "unavailable" with the reason. It sends no Command: it only
hears what Live plays.

The sound comes from the "zpkt listen" device on Live's Main when it is there, and from the screen capture
otherwise. ZPKT_LISTEN_SOURCE chooses: "auto" (the default: the device, then the screen capture), "device" or
"screen".
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from zpkt.app.adapters import AdapterError, AdapterSpec, AppContext
from zpkt.app.listen import PREFIX, SOURCES
from zpkt.app.listen.capture import Chain, Source, SwiftCapture
from zpkt.app.listen.device import DeviceCapture
from zpkt.app.listen.hub import Hub
from zpkt.app.listen.routes import ListenMount


def source_from(env: Mapping[str, str] = os.environ) -> Source:
    """The capture ZPKT_LISTEN_SOURCE names. Making it opens nothing."""
    choice = env.get("ZPKT_LISTEN_SOURCE", "").strip().lower() or "auto"
    if choice == "device":
        return DeviceCapture()
    if choice == "screen":
        return SwiftCapture()
    if choice == "auto":
        return Chain([DeviceCapture(), SwiftCapture()])
    raise AdapterError(f"ZPKT_LISTEN_SOURCE is {choice!r}; it can be {', '.join(SOURCES)}")


class ListenAdapter:
    name = "listen"

    def __init__(self, context: AppContext, source: Source | None = None, linger: float = 5.0) -> None:
        self.context = context
        self.hub = Hub(source or source_from(), linger=linger)

    def start(self) -> None:
        self.context.desk.mounts.add(PREFIX, ListenMount(self.hub))

    def stop(self) -> None:
        self.context.desk.mounts.remove(PREFIX)
        self.hub.stop()


def make(context: AppContext) -> ListenAdapter:
    return ListenAdapter(context)


ADAPTER = AdapterSpec("listen", make)
