"""/skrng from the Mac, for the owner's devices only.

    phone (Tailscale on) --https--> tailscale serve (tailnet only) --> 127.0.0.1:8787 (this)

This server listens on loopback only; `tailscale serve` puts it on the tailnet
with an HTTPS certificate (the mic needs a secure page). Nothing reaches it
from the public internet. On top of that it asks for a password once per
browser: the first visit sets it (the tailnet is already private), later
visits sign in with it. Only scrypt hashes of the password and of each
browser's session are stored (auth.json, mode 600), so nobody else, the
agent included, ever sees the password.

Routes, all behind the password except /login:
    /skrng/..., /style.css    the public site's pages, fetched from it (they are public anyway)
    /audio/...                redirect to the public site's audio
    /api/skrng/feedback       the voice review's answers, kept on the Mac (feedback.jsonl)
    /api/rpc                  the harness methods (rpc.Methods), called in-process
The pages see they are on a .ts.net host and drop their key: the cookie is the key here.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from pathlib import Path
from typing import Any

from aiohttp import ClientSession, ClientTimeout, web

from .config import Config
from .rpc import Methods

log = logging.getLogger(__name__)

COOKIE = "skrng_session"
SESSION_DAYS = 400
MAX_BODY = 64 * 1024
RPC_TIMEOUT = {"ask": 125.0}
DEFAULT_RPC_TIMEOUT = 20.0
PROXIED = ("/skrng/", "/style.css", "/favicon.ico", "/favicon.svg")


def _scrypt(text: str, salt: bytes) -> str:
    return hashlib.scrypt(text.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32).hex()


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Auth:
    """The password (scrypt) and the signed-in browsers (sha256 of each session token)."""

    def __init__(self, path: Path):
        self.path = path
        self.data: dict[str, Any] = json.loads(path.read_text()) if path.exists() else {"sessions": {}}

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data))
        os.chmod(tmp, 0o600)
        tmp.replace(self.path)

    @property
    def has_password(self) -> bool:
        return "password" in self.data

    def set_password(self, pw: str) -> None:
        salt = secrets.token_bytes(16)
        self.data["password"] = {"salt": salt.hex(), "hash": _scrypt(pw, salt)}
        self.data["sessions"] = {}  # a new password signs every browser out
        self._save()

    def check_password(self, pw: str) -> bool:
        p = self.data.get("password")
        return bool(p) and hmac.compare_digest(_scrypt(pw, bytes.fromhex(p["salt"])), p["hash"])

    def new_session(self) -> str:
        token = secrets.token_urlsafe(32)
        self.data["sessions"][_sha(token)] = time.time() + SESSION_DAYS * 86400
        self._save()
        return token

    def valid(self, token: str | None) -> bool:
        if not token:
            return False
        until = self.data["sessions"].get(_sha(token))
        return bool(until) and until > time.time()


LOGIN = """<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta name="robots" content="noindex">
<title>skrng sign in</title><style>
{css}
</style></head><body>
<h1>skrng</h1><p>{lede}</p><p class="err">{error}</p>
<form method="post" action="/login"><input type="hidden" name="next" value="{next}">
<input type="password" name="password" placeholder="Password" autocomplete="{ac}" autofocus required minlength="8">
{confirm}<button>{button}</button></form></body></html>"""


CSS = (":root{color-scheme:light dark}body{font:17px/1.4 -apple-system,system-ui,sans-serif;max-width:26rem;"
       "margin:15vh auto;padding:0 16px}input,button{font:inherit;width:100%;box-sizing:border-box;padding:.7rem;"
       "margin:.35rem 0;border-radius:6px;border:1px solid #888}button{font-weight:600}.err{color:#c33}")


def redirect(location: str) -> web.Response:
    return web.Response(status=302, headers={"Location": location})


def login_page(auth: Auth, next_: str, error: str = "") -> web.Response:
    first = not auth.has_password
    html = LOGIN.format(
        css=CSS,
        lede="Choose a password for this Mac's skrng. Only you will know it." if first else "Sign in.",
        error=error, next=_safe_next(next_).replace('"', ""), ac="new-password" if first else "current-password",
        confirm='<input type="password" name="confirm" placeholder="The same again" autocomplete="new-password" required>' if first else "",
        button="Set password" if first else "Sign in")
    return web.Response(text=html, content_type="text/html", status=401 if error else 200)


def _safe_next(n: str | None) -> str:
    return n if n and n.startswith("/") and not n.startswith("//") else "/skrng/"


class App:
    def __init__(self, cfg: Config, methods: Methods, data_dir: Path, secure_cookie: bool = True):
        self.cfg, self.methods, self.secure_cookie = cfg, methods, secure_cookie
        self.auth = Auth(data_dir / "auth.json")
        self.feedback_path = data_dir / "feedback.jsonl"
        self.http: ClientSession | None = None
        self.cache: dict[str, tuple[float, bytes, str]] = {}

    def build(self) -> web.Application:
        app = web.Application(middlewares=[self.gate], client_max_size=MAX_BODY)
        app.router.add_get("/login", self.login_get)
        app.router.add_post("/login", self.login_post)
        app.router.add_get("/", self.home)
        app.router.add_route("*", "/api/skrng/feedback", self.feedback)
        app.router.add_post("/api/rpc", self.rpc)
        app.router.add_get("/audio/{tail:.*}", self.audio)
        app.router.add_get("/{tail:.*}", self.proxy)
        app.on_cleanup.append(self._close)
        return app

    async def home(self, _request: web.Request) -> web.Response:
        return redirect("/skrng/")

    async def audio(self, request: web.Request) -> web.Response:
        return redirect(self.cfg.site + request.path_qs)   # the audio is public; the browser fetches it there

    async def _close(self, _app: web.Application) -> None:
        if self.http:
            await self.http.close()

    @web.middleware
    async def gate(self, request: web.Request, handler):
        if request.path == "/login" or self.auth.valid(request.cookies.get(COOKIE)):
            return await handler(request)
        if request.path.startswith("/api/"):
            return web.json_response({"error": "Sign in first."}, status=401)
        return redirect("/login?next=" + request.path_qs)

    async def login_get(self, request: web.Request) -> web.Response:
        return login_page(self.auth, request.query.get("next", "/skrng/"))

    async def login_post(self, request: web.Request) -> web.StreamResponse:
        form = await request.post()
        pw, next_ = str(form.get("password", "")), str(form.get("next", "/skrng/"))
        if not self.auth.has_password:
            if len(pw) < 8:
                return login_page(self.auth, next_, "At least 8 characters.")
            if pw != str(form.get("confirm", "")):
                return login_page(self.auth, next_, "The two didn't match.")
            self.auth.set_password(pw)
            log.info("skrng password set")
        elif not self.auth.check_password(pw):
            await asyncio.sleep(1.5)  # slow down guessing
            return login_page(self.auth, next_, "Wrong password.")
        resp = redirect(_safe_next(next_))
        resp.set_cookie(COOKIE, self.auth.new_session(), max_age=SESSION_DAYS * 86400, secure=self.secure_cookie,
                        httponly=True, samesite="Lax", path="/")
        return resp

    # --- the voice review's answers ------------------------------------------
    async def feedback(self, request: web.Request) -> web.Response:
        if request.method == "POST":
            try:
                body = await request.json()
            except ValueError:
                return web.json_response({"error": "Invalid JSON body."}, status=400)
            if not isinstance(body, dict) or not isinstance(body.get("batch"), (int, float)):
                return web.json_response({"error": "A record needs a batch number."}, status=400)
            body["server_time"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            self.feedback_path.parent.mkdir(parents=True, exist_ok=True)
            with self.feedback_path.open("a") as f:
                f.write(json.dumps(body) + "\n")
            return web.json_response({"ok": True})
        if request.method == "GET":
            batch = request.query.get("batch")
            rows = read_feedback(self.feedback_path, float(batch) if batch not in (None, "") else None)
            return web.json_response(rows, headers={"Cache-Control": "no-store"})
        raise web.HTTPMethodNotAllowed(request.method, ["GET", "POST"])

    # --- the harness, in-process ---------------------------------------------
    async def rpc(self, request: web.Request) -> web.Response:
        try:
            body = await request.json()
        except ValueError:
            return web.json_response({"error": "Body must be JSON."}, status=400)
        method = str(body.get("method"))
        timeout = RPC_TIMEOUT.get(method, DEFAULT_RPC_TIMEOUT)
        try:
            result = await asyncio.wait_for(self.methods.call(method, body.get("params") or {}), timeout)
        except asyncio.TimeoutError:
            return web.json_response({"error": f"The Mac did not answer {method} within {timeout:.0f} s."}, status=504)
        except ValueError as exc:
            return web.json_response({"error": str(exc)}, status=400)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the server
            log.exception("rpc %s", method)
            return web.json_response({"error": f"{type(exc).__name__}: {exc}"}, status=500)
        return web.json_response(result)

    # --- the pages, from the public site --------------------------------------
    async def proxy(self, request: web.Request) -> web.Response:
        path = request.path
        if not path.startswith(PROXIED):
            raise web.HTTPNotFound()
        hit = self.cache.get(request.path_qs)
        if hit and hit[0] > time.time():
            return web.Response(body=hit[1], content_type=hit[2])
        if self.http is None:
            self.http = ClientSession(timeout=ClientTimeout(total=20))
        async with self.http.get(self.cfg.site + request.path_qs) as r:
            body = await r.read()
            ctype = r.content_type
            if r.status != 200:
                return web.Response(status=r.status, body=body, content_type=ctype)
        self.cache[request.path_qs] = (time.time() + 30, body, ctype)
        return web.Response(body=body, content_type=ctype)


def read_feedback(path: Path, batch: float | None = None) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text().splitlines():
        try:
            r = json.loads(line)
        except ValueError:
            continue
        if batch is None or r.get("batch") == batch:
            rows.append(r)
    return rows


async def run(cfg: Config, methods: Methods) -> None:
    app = App(cfg, methods, cfg.skrng_dir).build()
    runner = web.AppRunner(app, access_log=None)
    await runner.setup()
    await web.TCPSite(runner, "127.0.0.1", cfg.web_port).start()
    log.info("skrng on http://127.0.0.1:%d (tailscale serve puts it on the tailnet)", cfg.web_port)
    await asyncio.Event().wait()
