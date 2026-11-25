"""The Web adapter: the phone and the desktop, over HTTP and server-sent events (zpkt.app.web has the server)."""

from __future__ import annotations

import threading

from zpkt.app import web
from zpkt.app.adapters import AdapterSpec, AppContext


class WebAdapter:
    """Serves the old desk page at /, the new shell at /app/ and the API, on the settings' HTTP port."""

    name = "web"

    def __init__(self, context: AppContext, supervise: bool = True) -> None:
        self.context = context
        self.supervise = supervise
        self.server: web.DeskHTTPServer | None = None
        self.thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        if self.server is None:
            raise RuntimeError("the web adapter has not started")
        return int(self.server.server_address[1])

    def start(self) -> None:
        self.server = web.start(self.context.desk, supervise=self.supervise)
        self.thread = web.serve_in_thread(self.server)

    def stop(self) -> None:
        if self.server is not None:
            self.server.shutdown()
            self.server.server_close()
            self.server = None


def make(context: AppContext) -> WebAdapter:
    return WebAdapter(context)


ADAPTER = AdapterSpec("web", make)
