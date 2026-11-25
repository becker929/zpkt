"""zpkt.app: the one interface, and the only door to Live.

Adapters (the web page, later the MiniLab, the API and agents) turn what they hear into Commands. The command bus
stamps who and runs the checks. The desk and the monitor are the services behind it. They reach Live through
zpkt.live and zpkt.audio, which are given the app's connections (zpkt.app.connections) and never open their own.
README.md has the picture and how to add an adapter.

`zpkt app` runs it (`main`); `run` is the same for code and tests.
"""

from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Sequence


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="zpkt app", description="Start the one interface: the mix desk and the /app/ shell."
    )
    p.add_argument("--port", type=int, help="the HTTP port (default: MIXDESK_PORT or 8985)")
    p.add_argument("--adapters", default="web,song", help="adapters to start, comma separated (default: web,song)")
    p.add_argument("--no-supervise", action="store_true", help="do not start or watch the pager in Live")
    return p.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> None:
    """`zpkt app`: start the app and serve until interrupted."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    from zpkt.app.adapters import AppContext, create
    from zpkt.app.desk import Desk, Settings

    settings = Settings.from_env()
    if args.port is not None:
        from dataclasses import replace

        settings = replace(settings, http_port=args.port, udp_port=args.port + 1)
    desk = Desk(settings)
    adapters = create([n for n in args.adapters.split(",") if n], AppContext(desk.bus, desk, settings))
    for adapter in adapters:
        if args.no_supervise and hasattr(adapter, "supervise"):
            adapter.supervise = False
        adapter.start()
        port = getattr(adapter, "port", None)
        print(
            f"zpkt app: {adapter.name} on http://127.0.0.1:{port}/app/" if port else f"zpkt app: {adapter.name}",
            flush=True,
        )
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        for adapter in adapters:
            adapter.stop()
        sys.exit(0)
