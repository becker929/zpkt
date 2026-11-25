"""The Song: the arranger, mounted in the app under /app/song, and its recipe built in Live through the bus.

The arranger (contrib/arranger) is Anthony's phone page for trying arrangements of HW002 out of loops bounced from
Live. Its server stays as it is, on :8975, and this module mounts the same pages and routes (the same code, one
route table) at /app/song. The arrangement file keeps its form: a save from the arranger page keeps every key it does
not own (arrangement.py says who owns which).

- Song is the arrangement's Structure as lanes of bars. Recipe is its Structure and its Sound (arrangement.py's types).
- Reads of the arranger's files go straight to its routes. Writes (a save, a kept choice, a queued batch) are commands
  on the bus, stamped who, so history knows who made them.
- `song.build` makes the mix set in Live from the recipe (zpkt.live.recipe_build), with the app's connection, behind the
  bus's checks: the wrong-set guard for the mix set, the agent rule and the lock.

Nothing here makes sound. Mix 1 and transitions play rendered files in the browser as sketches, within the two named
exceptions of contrib/docs/sound.md; their pages are served unchanged (only their absolute links gain the prefix).
"""

from __future__ import annotations

import importlib
import importlib.util
import json
import os
import re
import sys
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, Any

from zpkt.app import effects
from zpkt.app.bus import BadRequest, Bus, Command, Reply
from zpkt.app.mounts import MountReply, ReadBody, Request
from zpkt.live import openset
from zpkt.live import recipe_build as rb
from zpkt.live.ops import LiveOps
from zpkt.live.transport import McpTransport

if TYPE_CHECKING:
    from arrangement import Sound, Structure

PREFIX = "/app/song"
SERVER_MODULE = "zpkt_arranger_server"  # contrib/arranger/server.py under a name of its own, apart from any `server`

# The links in the arranger's pages are absolute ("/api/...", "/audio/..."). Served under a prefix they gain it.
_LINK = re.compile(
    r"(?P<q>['\"`])/(?:(?=(?P=q))|(?:loops|fx)\.json|(?:api|audio|refs|fx|mix2|spectral|kickdesign|kickfuzz|transitions|mix|kick)(?=[/'\"`]))"
)


# ---- the arranger's code ---------------------------------------------------------------------------------------------


def arranger_dir() -> Path:
    """The folder of the arranger's code. ZPKT_ARRANGER_DIR names another one; the default is contrib/arranger of
    this checkout."""
    env = os.environ.get("ZPKT_ARRANGER_DIR")
    return Path(env).expanduser() if env else Path(__file__).resolve().parents[3] / "contrib" / "arranger"


@dataclass(frozen=True)
class ArrangerCode:
    """The arranger's modules the Song uses: its arrangement types, constants, route table and mix-2 devices."""

    arrangement: ModuleType
    hw002: ModuleType
    server: ModuleType
    mixset: ModuleType


def load_arranger(directory: Path | None = None) -> ArrangerCode:
    """Import the arranger's modules from its folder. They import each other by plain name, so the folder goes on
    the import path; its server is loaded under its own name so it never takes `server` from another tool."""
    folder = directory or arranger_dir()
    if not (folder / "server.py").is_file():
        raise FileNotFoundError(f"no arranger in {folder}; set ZPKT_ARRANGER_DIR to contrib/arranger")
    if str(folder) not in sys.path:
        sys.path.insert(0, str(folder))
    server = sys.modules.get(SERVER_MODULE)
    if server is None or Path(server.__file__ or "").parent != folder:
        spec = importlib.util.spec_from_file_location(SERVER_MODULE, folder / "server.py")
        if spec is None or spec.loader is None:
            raise ImportError(f"cannot load {folder / 'server.py'}")
        server = importlib.util.module_from_spec(spec)
        sys.modules[SERVER_MODULE] = server
        spec.loader.exec_module(server)
    return ArrangerCode(
        importlib.import_module("arrangement"),
        importlib.import_module("hw002"),
        server,
        importlib.import_module("mixset"),
    )


@dataclass(frozen=True)
class SongSettings:
    """Where the Song's data is and what it builds. `from_env` is the running app's; tests make their own."""

    data: Path  # the arranger's data folder: loops, renders, arrangements/<id>.json
    mix_set: str  # the Live set the recipe is built into
    tempo_bpm: float
    canonical: str  # the arrangement the pages open
    start_worker: Callable[[], None] | None = None  # starts mix 2's renders; None is the arranger's own worker
    worker_running: Callable[[], bool | None] | None = None

    @classmethod
    def from_env(cls, code: ArrangerCode | None = None) -> SongSettings:
        a = (code or load_arranger()).hw002
        return cls(Path(a.DATA), str(a.MIX_SET), float(a.TEMPO_BPM), str(a.CANONICAL))


# ---- the pages: pure -------------------------------------------------------------------------------------------------


def mount_html(html: str, prefix: str = PREFIX) -> str:
    """The arranger's page with every absolute link under `prefix`. Nothing else in the page changes."""
    return _LINK.sub(lambda m: _prefixed(m, prefix), html)


def _prefixed(m: re.Match[str], prefix: str) -> str:
    text = m.group(0)  # quote + "/" + the first word of the path
    return f"{text[0]}{prefix}{text[1:]}"


def song_view(
    arrangement_id: str, a: Mapping[str, Any], lane_titles: Mapping[str, str] | None = None
) -> dict[str, Any]:
    """The Song: the arrangement's Structure as lanes of bars, each lane's regions by start bar, and its transitions."""
    titles = lane_titles or {}
    order = [*titles, *(r["lane"] for r in a.get("regions", []) if r["lane"] not in titles)]
    lanes = []
    for lane in dict.fromkeys(order):
        regions = sorted((r for r in a.get("regions", []) if r["lane"] == lane), key=lambda r: r["start"])
        if regions:
            lanes.append({"lane": lane, "title": titles.get(lane, lane), "regions": regions})
    return {
        "id": arrangement_id,
        "name": a.get("name", arrangement_id),
        "bars": a.get("bars"),
        "mutes": a.get("mutes", []),
        "lanes": lanes,
        "transitions": a.get("transitions", []),
    }


# ---- the service -----------------------------------------------------------------------------------------------------

WRITES: dict[str, tuple[str, str]] = {  # command kind -> (method, path of the arranger's route)
    "song.save": ("PUT", "/api/arrangements/{id}"),
    "song.keep": ("PUT", "/api/arrangements/{id}/{key}"),
    "song.delete": ("DELETE", "/api/arrangements/{id}"),
    "song.transitions": ("PUT", "/api/transitions"),
    "song.queue": ("POST", "/api/mix2/requests"),
}


class Song:
    """The Song service: the arranger's route table over its data folder, and the build in Live."""

    def __init__(self, settings: SongSettings, code: ArrangerCode | None = None) -> None:
        self.settings = settings
        self.code = code or load_arranger()
        server = self.code.server
        start, running = settings.start_worker, settings.worker_running
        if start is None:
            worker = server.Mix2Worker(settings.data)
            start, running = worker.start, running or worker.running
        self.app = server.Arranger(settings.data, start, worker_running=running or server._not_known)
        self.write_routes = self._write_routes()

    # ---- the arranger's routes, as they are -------------------------------------------------------------------------
    def route(self, method: str, path: str, read_body: ReadBody) -> MountReply:
        """The arranger's answer for a request (its own dispatch), with its pages' links under the prefix."""
        reply = self.code.server.dispatch(self.app, method, path, read_body)
        body = reply.body
        if reply.ctype.startswith("text/html"):
            body = mount_html(body.decode()).encode()
        return MountReply(reply.code, body, reply.ctype, reply.cache)

    def _write_routes(self) -> list[tuple[str, re.Pattern[str], str]]:
        keys = "|".join(self.code.arrangement.LATER_KEYS)
        return [
            ("PUT", re.compile(rf"/api/arrangements/([^/]+)/({keys})"), "song.keep"),
            ("PUT", re.compile(r"/api/transitions"), "song.transitions"),
            ("PUT", re.compile(r"/api/arrangements/([^/]+)"), "song.save"),
            ("POST", re.compile(r"/api/mix2/requests"), "song.queue"),
            ("DELETE", re.compile(r"/api/arrangements/([^/]+)"), "song.delete"),
        ]

    def write_command(self, method: str, path: str) -> tuple[str, dict[str, str]] | None:
        """The command kind (and its id and key) that a write to one of the arranger's routes is, or None."""
        for verb, pattern, kind in self.write_routes:
            if verb == method and (m := pattern.fullmatch(path)):
                names = ("id", "key")[: len(m.groups())]
                return kind, dict(zip(names, m.groups(), strict=False))
        return None

    # ---- commands ---------------------------------------------------------------------------------------------------
    def write(self, cmd: Command) -> Reply:
        """A write to the arranger's data: the route the kind names, run by the arranger's own code."""
        method, template = WRITES[cmd.kind]
        a = self.code.arrangement
        aid, key = str(cmd.args.get("id", "")), str(cmd.args.get("key", ""))
        if "{id}" in template and (not aid or "/" in aid or "?" in aid):
            raise BadRequest(f"the command needs 'id', an arrangement id like {self.settings.canonical}")
        if "{key}" in template and key not in a.LATER_KEYS:
            raise BadRequest(f"'key' is one of {', '.join(a.LATER_KEYS)}")
        read_body = cmd.args.get("read_body") or _body_reader(cmd.args.get("body"))
        reply = self.code.server.dispatch(self.app, method, template.format(id=aid, key=key), read_body)
        return reply.code, json.loads(reply.body)

    def _arrangement(self, arrangement_id: str) -> dict[str, Any]:
        if not self.code.arrangement.ID.match(arrangement_id):
            raise BadRequest(f"'id' must be an arrangement id like {self.settings.canonical}")
        f = self.app.arrangements / f"{arrangement_id}.json"
        try:
            found = json.loads(f.read_text())
        except FileNotFoundError:
            raise BadRequest(f"there is no arrangement {arrangement_id!r}") from None
        except ValueError:
            raise BadRequest(f"the arrangement {arrangement_id!r} is not valid JSON") from None
        if not isinstance(found, dict):
            raise BadRequest(f"the arrangement {arrangement_id!r} is not an object")
        return found

    def listing(self, cmd: Command) -> Reply:
        reply = self.code.server.dispatch(self.app, "GET", "/api/arrangements", lambda limit: None)
        return 200, {"arrangements": json.loads(reply.body), "canonical": self.settings.canonical}

    def show(self, cmd: Command) -> Reply:
        """The Song: the arrangement's Structure as lanes (read)."""
        aid = str(cmd.args.get("id") or self.settings.canonical)
        return 200, song_view(aid, self.structure(aid), self._lane_titles())

    def recipe(self, cmd: Command) -> Reply:
        """The Recipe: the arrangement's Structure and its Sound, apart (read)."""
        aid = str(cmd.args.get("id") or self.settings.canonical)
        a = self._arrangement(aid)
        return 200, {
            "id": aid,
            "saved": a.get("saved"),
            "structure": self.structure(aid, a),
            "sound": self.sound(aid, a),
        }

    def structure(self, arrangement_id: str, a: dict[str, Any] | None = None) -> Structure:
        return self.code.arrangement.structure(a if a is not None else self._arrangement(arrangement_id))

    def sound(self, arrangement_id: str, a: dict[str, Any] | None = None) -> Sound:
        return self.code.arrangement.sound(a if a is not None else self._arrangement(arrangement_id))

    def _lane_titles(self) -> dict[str, str]:
        try:
            loops = json.loads((self.settings.data / "loops.json").read_text())
            return {lane["id"]: lane["title"] for lane in loops["lanes"]}
        except (OSError, ValueError, KeyError, TypeError):
            return {}  # no loops index yet (mine.py makes it): lanes show by id

    # ---- building Live ----------------------------------------------------------------------------------------------
    def build(self, live: McpTransport, cmd: Command) -> Reply:
        """Make the mix set in front from the recipe, through `live` (the app's connection, already held). It empties
        the set, so it only runs on the mix set itself, named by Live, never on an unsaved one."""
        aid = str(cmd.args.get("id") or self.settings.canonical)
        found = openset.open_set_name(live)
        if found != self.settings.mix_set:
            shown = found or "a set Live does not name"
            return 409, {
                "error": f"The recipe is built into {self.settings.mix_set}. Live has {shown} open; open that set first."
            }
        arr = self._arrangement(aid)
        loops = self._data_file("loops.json", "mine.py")
        fx = self._data_file("fx/fx.json", "fxset.py")
        ops = LiveOps(live)
        try:
            built = rb.build(ops, loops, fx, arr, self.settings.data, self.settings.tempo_bpm)
            rb.apply_mix(ops, arr, rb.channels(loops, arr), self.settings.data, self.code.mixset.DEVICES)
        except rb.Stopped as exc:
            return 409, {"error": f"The build stopped: {exc}"}
        return 200, {"ok": True, "id": aid, "channels": built.channels, "buses": built.buses, "clips": built.clips}

    def _data_file(self, relative: str, made_by: str) -> dict[str, Any]:
        f = self.settings.data / relative
        try:
            found = json.loads(f.read_text())
        except FileNotFoundError:
            raise BadRequest(f"there is no {relative} in {self.settings.data}; run {made_by} first") from None
        except ValueError:
            raise BadRequest(f"{f} is not valid JSON") from None
        if not isinstance(found, dict):
            raise BadRequest(f"{f} is not an object")
        return found


def _body_reader(body: Any) -> ReadBody:
    """`read_body` for a command's JSON `body`: its bytes if their length is within the limit, else None."""
    raw = json.dumps(body).encode() if body is not None else b""

    def read(limit: int) -> bytes | None:
        return raw if 0 < len(raw) < limit else None

    return read


# ---- the mount and the commands --------------------------------------------------------------------------------------


class SongMount:
    """The arranger's routes under /app/song. Reads are the arranger's own; writes are commands on the bus."""

    def __init__(self, song: Song, bus: Bus) -> None:
        self.song, self.bus = song, bus

    def handle(self, request: Request) -> MountReply:
        method, path, read_body = request.method, request.rest, request.read_body
        if path == "/index.html":
            path = "/"
        if method in ("GET", "HEAD"):
            return self.song.route(method, path, read_body)
        found = self.song.write_command(method, path)
        if found is None:
            return self.song.route(method, path, read_body)  # the arranger's own answer for a path it has no route for
        kind, args = found
        code, obj = self.bus.submit(Command(kind, "you", {**args, "read_body": read_body}))
        return MountReply(code, json.dumps(obj).encode())


def register(bus: Bus, song: Song, live: McpTransport) -> None:
    """Put the Song's commands on the bus: reads, the writes to the arranger's data, and the build. `live` is the
    app's connection; the build gets it, and holds Live while it runs."""
    effects.register(bus, "song.list", song.listing)
    effects.register(bus, "song.show", song.show)
    effects.register(bus, "song.recipe", song.recipe)
    for kind in WRITES:
        effects.register(bus, kind, song.write)
    effects.register(
        bus, "song.build", lambda cmd: song.build(live, cmd), touches_live=True, for_set=song.settings.mix_set
    )
