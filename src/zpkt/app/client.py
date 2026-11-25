"""The client of the app: how a program that is not the app asks it to do something with Live.

Standard library only, and no Live code: it sends JSON to the API (zpkt.app.adapters.api) and returns what came
back. The `zpkt` command, music-bot's booth and zpkt-demo use it (docs/app-clients.md). Where the app is comes from
`ZPKT_APP_URL` (default http://127.0.0.1:8984); the token from the caller's own token file (zpkt.app.token). The
app stamps each call by the token, so a caller is who its token file says.

A coding agent in a terminal runs with `ZPKT_AGENT=1` (Ask sets it for the engines it starts). Then the `zpkt`
command is not `cli` but `agent`: it sends the agent's token, and the app holds it to the agent rule (a change to
Live needs an Option you picked). `ZPKT_OPTION=<id>` names that Option; the app checks that you picked it.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from zpkt.app import token as tokens

DEFAULT_URL = "http://127.0.0.1:8984"
API = "/api/v1"
Reply = tuple[int, dict[str, Any]]


class AppDown(OSError):
    """The app cannot be reached, or will not let this caller in. The message says what to do."""


LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")
AGENT_ENV = "ZPKT_AGENT"  # set for an agent's shell: the cli is then the agent
OPTION_ENV = "ZPKT_OPTION"  # the Option the user picked, which lets the agent's change pass


def caller(who: str = "cli") -> str:
    """Who this process is to the app. The `zpkt` command is `cli`, unless an agent is driving it (ZPKT_AGENT):
    then it is `agent`. A program that names itself (booth, demo) stays that."""
    return "agent" if who == "cli" and os.environ.get(AGENT_ENV) else who


def picked_option() -> str | None:
    """The approval an agent sends: "option:<id>" for the Option named by ZPKT_OPTION, or None."""
    option = os.environ.get(OPTION_ENV, "").strip()
    return f"option:{option}" if option else None


def app_url() -> str:
    return os.environ.get("ZPKT_APP_URL", DEFAULT_URL).rstrip("/")


class AppClient:
    """One caller of the app. `who` is cli, booth, demo or agent; it picks the token file, and the token is what
    the app stamps every change by. `cli` becomes `agent` when an agent drives the command (`caller`)."""

    def __init__(
        self,
        who: str = "cli",
        url: str | None = None,
        token: str | None = None,
        config_dir: Path | None = None,
        timeout: float = 130.0,
    ) -> None:
        """`timeout` is above the longest job (opening a set waits up to 120 s)."""
        self.who, self.url, self.timeout = caller(who), (url or app_url()).rstrip("/"), timeout
        self._token, self._config_dir = token, config_dir

    def token(self) -> str:
        found = self._token or tokens.read_token(self._config_dir, self.who)
        if not found:
            raise AppDown(f"no token at {self._token_file()}: start the app with `zpkt app`")
        return found

    def _token_file(self) -> Path:
        return tokens.token_path(self._config_dir, self.who)

    def _send(self, method: str, path: str, body: dict[str, Any] | None, auth: bool = True) -> Reply:
        headers = {"Content-Type": "application/json"}
        if auth:
            if urlparse(self.url).hostname not in LOCAL_HOSTS:
                raise AppDown(f"{self.url} is not this Mac: the token goes to localhost only. Check ZPKT_APP_URL.")
            headers["Authorization"] = f"Bearer {self.token()}"
        data = None if body is None else json.dumps(body).encode()
        req = urllib.request.Request(self.url + API + path, data=data, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                code, raw = r.status, r.read()
        except urllib.error.HTTPError as exc:
            code, raw = exc.code, exc.read()
        except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
            raise AppDown(f"cannot reach the zpkt app at {self.url} ({exc}): start it with `zpkt app`") from exc
        try:
            reply = json.loads(raw or b"{}")
        except ValueError:
            reply = {"error": f"the app sent something that is not JSON ({raw[:60]!r})"}
        if code == 401:
            raise AppDown(f"the app refused the token in {self._token_file()}; restart `zpkt app`")
        return code, reply if isinstance(reply, dict) else {"error": "the app's reply is not an object"}

    def up(self) -> bool:
        """True when an app answers /health."""
        try:
            return self._send("GET", "/health", None, auth=False)[0] == 200
        except AppDown:
            return False

    def commands(self) -> list[dict[str, Any]]:
        code, reply = self._send("GET", "/commands", None)
        return list(reply.get("commands", [])) if code == 200 else []

    def submit(
        self, kind: str, args: dict[str, Any] | None = None, *, approval: str | None = None, group: str | None = None
    ) -> Reply:
        """Any command by kind. Returns (status, reply); a refusal is a status, not an exception."""
        body: dict[str, Any] = {"kind": kind, "who": self.who, "args": args or {}}
        if approval is None and self.who == "agent":
            approval = picked_option()
        if approval:
            body["approval"] = approval
        if group:
            body["group"] = group
        return self._send("POST", "/command", body)

    # ---- the named jobs ------------------------------------------------------------------------------------------
    def run(self, code: str, **args: Any) -> Reply:
        return self.submit("live.run", {"code": code, **args})

    def open_set(self, name: str, save_current: bool = True) -> Reply:
        return self.submit("live.open_set", {"name": name, "save_current": save_current})

    def render_loop(self, out: str, **args: Any) -> Reply:
        return self.submit("live.render_loop", {"out": out, **args})

    def set_tempo(self, bpm: float, **args: Any) -> Reply:
        return self.submit("live.set_tempo", {"bpm": bpm, **args})

    def transport(self, action: str, **args: Any) -> Reply:
        return self.submit("live.transport", {"action": action, **args})

    def state_take(self, only: list[str] | None = None) -> Reply:
        return self.submit("state.take", {"only": only} if only else {})

    def state_put(self, state: dict[str, Any], only: list[str] | None = None) -> Reply:
        return self.submit("state.put", {"state": state, **({"only": only} if only else {})})

    def page_apply(self, name: str, **args: Any) -> Reply:
        return self.submit("panel.apply", {"name": name, **args})

    def describe(self, keys: list[str]) -> Reply:
        return self.submit("describe", {"keys": keys})
