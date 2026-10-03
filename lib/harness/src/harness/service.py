"""The Mac end of the RPC: one outbound WebSocket to the site's RigBroker.

Nothing listens on the Mac. The service dials wss://<site>/api/rig/connect
with the rig token and keeps the socket open (reconnecting with backoff).
The browser's POST /api/rpc reaches the broker, which sends

    {"id": "...", "method": "...", "params": {...}}

down the socket and holds the HTTP request open until this end answers

    {"id": "...", "result": ...}   or   {"id": "...", "error": "..."}
"""

from __future__ import annotations

import asyncio
import json
import logging
import platform
from typing import Any

from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from . import jobs as J
from .config import Config, secret
from .notify import notify
from .rpc import Methods

log = logging.getLogger(__name__)


def _job_start(cfg: Config):
    def hook(job: J.Job) -> None:
        notify(f"Job started: {job.title}", f"Job {job.id} is running on the Mac.", f"{cfg.site}/skrng/#jobs")
    return hook


def _job_finish(cfg: Config):
    def hook(job: J.Job) -> None:
        mins = ((job.finished or 0) - (job.started or 0)) / 60
        head = "done" if job.status == "done" else "FAILED"
        body = (job.result if job.status == "done" else job.error) or ""
        notify(f"Job {head}: {job.title}", f"{body[:3000]}\n\n{mins:.0f} min, job {job.id}", f"{cfg.site}/skrng/#jobs")
    return hook


async def handle(ws: ClientConnection, methods: Methods, raw: str | bytes) -> None:
    try:
        msg = json.loads(raw)
    except ValueError:
        return
    if not isinstance(msg, dict) or "id" not in msg:
        return
    reply: dict[str, Any] = {"id": msg["id"]}
    try:
        reply["result"] = await methods.call(str(msg.get("method")), msg.get("params") or {})
    except ValueError as exc:
        reply["error"] = str(exc)
    except Exception as exc:
        log.exception("rpc %s", msg.get("method"))
        reply["error"] = f"{type(exc).__name__}: {exc}"
    try:
        await ws.send(json.dumps(reply))
    except ConnectionClosed:
        log.warning("socket closed before reply to %s", msg["id"])


async def serve(cfg: Config) -> None:
    token = secret("rig_token")
    if not token:
        raise SystemExit("no rig token: put one in the Keychain as zpkt-rig-token (see lib/harness/README.md)")
    store = J.JobStore(cfg.jobs_dir)
    runner = J.Runner(cfg, store, on_start=_job_start(cfg), on_finish=_job_finish(cfg))
    runner.recover()
    methods = Methods(cfg, runner, store)
    worker = asyncio.create_task(runner.work())
    tasks: set[asyncio.Task] = set()
    headers = {"Authorization": f"Bearer {token}"}
    while True:
        try:
            await _connected(cfg, headers, methods, tasks)
        except InvalidStatus as exc:  # 4xx: wrong token or broker not deployed; retrying fast won't help
            log.error("broker refused the socket: %s", exc)
            await asyncio.sleep(120)
        if worker.done():
            worker.result()


async def _connected(cfg: Config, headers: dict[str, str], methods: Methods, tasks: set[asyncio.Task]) -> None:
    # connect() as an iterator reconnects with backoff after network errors and 5xx.
    async for ws in connect(cfg.connect_url, additional_headers=headers, ping_interval=25, max_size=2**20,
                            open_timeout=20):
        try:
            await ws.send(json.dumps({"type": "hello", "host": platform.node()}))
            log.info("connected to %s", cfg.connect_url)
            async for raw in ws:
                t = asyncio.create_task(handle(ws, methods, raw))
                tasks.add(t)
                t.add_done_callback(tasks.discard)
        except ConnectionClosed:
            log.warning("socket closed; reconnecting")
