# Ableton Live MCP v2 — Remote Script
#
# Control Surface that runs inside Ableton Live's Python interpreter.
# Accepts NDJSON messages over TCP, executes Python code against the
# Live Object Model on the main thread, and returns serialized results.
#
# A client may also ask it to watch parameters ({"watch": [...]}, see _watch below): their changes are pushed back
# on the same socket as {"push": "watch", ...} lines. A client that never asks sees nothing new.

from __future__ import annotations

import json
import socket
import socketserver
import threading
import time
import traceback
from typing import TYPE_CHECKING

from _Framework.ControlSurface import ControlSurface

if TYPE_CHECKING:
    from typing import Any

PORT = 16619
EXEC_TIMEOUT = 12


def create_instance(c_instance: Any) -> AbletonLiveMCP:
    return AbletonLiveMCP(c_instance)


# ---- TCP layer (stdlib socketserver) ----


class _Handler(socketserver.StreamRequestHandler):
    """Processes NDJSON messages from one MCP client at a time.

    StreamRequestHandler gives us self.rfile / self.wfile backed by the
    socket — no manual makefile() or sendall() needed.
    """

    def setup(self) -> None:
        super().setup()
        self.server.controller._active_conn = self.connection

    def finish(self) -> None:
        self.server.controller._active_conn = None
        self.server.controller._watch_clear()
        super().finish()

    def handle(self) -> None:
        ctrl = self.server.controller
        ctrl._log(f"connected: {self.client_address[0]}:{self.client_address[1]}")
        ctrl.show_message("MCP connected")
        while True:
            line = self.rfile.readline()
            if not line:
                break
            try:
                resp = ctrl._dispatch(line)
                with ctrl._write_lock:
                    self.wfile.write(json.dumps(resp, default=str).encode("utf-8") + b"\n")
                    self.wfile.flush()
            except Exception as exc:
                ctrl._log(f"handler error: {exc}")
                try:
                    err = json.dumps({"status": "error", "error": str(exc)}).encode("utf-8") + b"\n"
                    with ctrl._write_lock:
                        self.wfile.write(err)
                        self.wfile.flush()
                except Exception:
                    break
        ctrl._log(f"disconnected: {self.client_address[0]}:{self.client_address[1]}")


class _Server(socketserver.TCPServer):
    allow_reuse_address = True


# ---- Control Surface ----


class AbletonLiveMCP(ControlSurface):
    """Bridges MCP agents to the Live Object Model via a TCP REPL."""

    def __init__(self, c_instance: Any) -> None:
        ControlSurface.__init__(self, c_instance)
        self._tcp: _Server | None = None
        self._active_conn: socket.socket | None = None
        self._write_lock = threading.Lock()  # a reply and a push never interleave on the socket
        self._watches: dict[str, Any] = {}  # id -> (remove listener, listener): the parameters being watched
        self._watch_lock = threading.Lock()
        self._watch_pending: dict[str, Any] = {}  # id -> the latest value, until the next tick sends it
        self._watch_flush_queued = False
        try:
            srv = _Server(("127.0.0.1", PORT), _Handler)
            srv.controller = self
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            self._tcp = srv
            self._log(f"listening on port {PORT}")
        except Exception as exc:
            self._log(f"failed to start: {exc}")
        self.show_message("AbletonLiveMCP v2")

    def disconnect(self) -> None:
        self._watch_clear_now()
        if self._active_conn:
            try:
                self._active_conn.close()
            except Exception:
                pass
        if self._tcp:
            self._tcp.shutdown()
            self._tcp.server_close()
        ControlSurface.disconnect(self)

    # ---- Logging ----

    def _log(self, msg: object) -> None:
        self.log_message("AbletonLiveMCP: " + str(msg))

    # ---- Message dispatch ----

    def _dispatch(self, raw: bytes) -> dict[str, Any]:
        """Parse an NDJSON line and route it."""
        try:
            msg = json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return {"status": "error", "error": "Malformed JSON"}

        if msg.get("ping"):
            return {"status": "ok", "pong": True}

        if "watch" in msg:
            return self._watch(msg["watch"])

        if msg.get("unwatch"):
            return self._unwatch()

        code = msg.get("code", "")
        if not code or not code.strip():
            return {"status": "error", "error": "No code provided"}

        return self._execute(code)

    # ---- Code execution ----

    def _execute(self, code: str) -> dict[str, Any]:
        """Run Python code on Ableton's main thread and return the result."""
        self._log(f"exec: {code[:200]}")

        try:
            scope = self._build_scope()
        except Exception as exc:
            return {
                "status": "error",
                "error": f"Scope unavailable: {exc}",
                "hint": "Ableton may still be loading.",
            }

        multiline = "\n" in code.strip()
        done = threading.Event()
        container = [None]

        def on_main_thread():
            t0 = time.time()
            try:
                # Try as an expression first — returns the value directly.
                try:
                    value = eval(code, scope)
                    container[0] = {
                        "status": "ok",
                        "result": serialize(value),
                        "elapsed": round(time.time() - t0, 3),
                    }
                    return
                except SyntaxError:
                    pass

                # Fall back to exec for statements. Read `result` if set.
                exec(code, scope)
                container[0] = {
                    "status": "ok",
                    "result": serialize(scope.get("result")),
                    "elapsed": round(time.time() - t0, 3),
                }
            except Exception as exc:
                self._log(f"error: {exc}")
                resp = {
                    "status": "error",
                    "error": str(exc),
                    "traceback": traceback.format_exc(),
                }
                if multiline:
                    resp["warning"] = (
                        "Multi-line code may have partially executed. Use song.undo() to roll back."
                    )
                container[0] = resp
            finally:
                done.set()

        try:
            self.schedule_message(0, on_main_thread)
        except (AssertionError, RuntimeError):
            on_main_thread()

        if done.wait(timeout=EXEC_TIMEOUT):
            return container[0]

        return {
            "status": "error",
            "error": f"Timed out after {EXEC_TIMEOUT}s",
            "warning": "Code may still be running on the main thread.",
        }

    # ---- Watching parameters (generic: the client says what to watch; nothing here knows what a page is) ----

    def _watch(self, items: Any) -> dict[str, Any]:
        """Watch what the client names, replacing this connection's earlier watches.

        `items` is a list of {"id": str, "code": str}. The code runs like any other code (an expression, or
        statements that set `result`) and gives a parameter (its `value` is watched) or an (object, "attribute")
        pair (for example (track, "mute")). Each change is pushed back on this socket, at most once per id per tick
        of Live's main thread, as {"push": "watch", "changes": [{"id", "value"}], "at": seconds}. The reply names
        the ids now watched and, for each that could not be, why.
        """
        if not isinstance(items, list) or not all(
            isinstance(i, dict) and isinstance(i.get("id"), str) and isinstance(i.get("code"), str) for i in items
        ):
            return {"status": "error", "error": "watch takes a list of {id, code}"}
        return self._on_main("watch", lambda: self._watch_register(items))

    def _unwatch(self) -> dict[str, Any]:
        return self._on_main("unwatch", self._watch_unregister)

    def _watch_register(self, items: list) -> dict[str, Any]:
        scope = self._build_scope()
        self._watch_clear_now()
        failed = {}
        for item in items:
            wid = item["id"]
            try:
                target = self._watch_eval(item["code"], scope)
                if isinstance(target, tuple) and len(target) == 2 and isinstance(target[1], str):
                    obj, attr = target
                else:
                    obj, attr = target, "value"
                add = getattr(obj, "add_%s_listener" % attr)
                remove = getattr(obj, "remove_%s_listener" % attr)
                listener = self._watch_listener(wid, lambda obj=obj, attr=attr: getattr(obj, attr))
                add(listener)
                self._watches[wid] = (remove, listener)
            except Exception as exc:
                failed[wid] = str(exc)
        return {"status": "ok", "watching": sorted(self._watches), "failed": failed}

    def _watch_unregister(self) -> dict[str, Any]:
        self._watch_clear_now()
        return {"status": "ok", "watching": [], "failed": {}}

    def _watch_eval(self, code: str, scope: dict) -> Any:
        try:
            return eval(code, scope)
        except SyntaxError:
            exec(code, scope)
            return scope.get("result")

    def _watch_listener(self, wid: str, read: Any) -> Any:
        def changed() -> None:
            try:
                value = read()
            except Exception:
                return
            self._watch_note(wid, value)

        return changed

    def _watch_note(self, wid: str, value: Any) -> None:
        """A watched value changed: keep the latest per id, and send what is kept on the next tick."""
        with self._watch_lock:
            self._watch_pending[wid] = value
            queue = not self._watch_flush_queued
            self._watch_flush_queued = True
        if queue:
            try:
                self.schedule_message(1, self._watch_flush)
            except (AssertionError, RuntimeError):
                self._watch_flush()

    def _watch_flush(self) -> None:
        with self._watch_lock:
            pending, self._watch_pending = self._watch_pending, {}
            self._watch_flush_queued = False
        if pending:
            changes = [{"id": wid, "value": value} for wid, value in pending.items()]
            self._push({"push": "watch", "changes": changes, "at": time.time()})

    def _push(self, message: dict[str, Any]) -> None:
        """One line to the client on the open socket (nothing if it has gone)."""
        conn = self._active_conn
        if conn is None:
            return
        data = json.dumps(message, default=str).encode("utf-8") + b"\n"
        try:
            with self._write_lock:
                conn.sendall(data)
        except Exception as exc:
            self._log(f"push failed: {exc}")

    def _watch_clear_now(self) -> None:
        """Take every listener off (on Live's main thread)."""
        watches, self._watches = self._watches, {}
        with self._watch_lock:
            self._watch_pending = {}
        for remove, listener in watches.values():
            try:
                remove(listener)
            except Exception:
                pass

    def _watch_clear(self) -> None:
        """The client has gone: take its listeners off, on the main thread (this runs on the handler's thread)."""
        if not self._watches:
            return
        try:
            self.schedule_message(0, self._watch_clear_now)
        except (AssertionError, RuntimeError):
            self._watch_clear_now()

    def _on_main(self, label: str, fn: Any) -> dict[str, Any]:
        """Run `fn` on Live's main thread and wait for its reply (a dict), as _execute does for code."""
        done = threading.Event()
        box = [None]

        def on_main_thread():
            try:
                box[0] = fn()
            except Exception as exc:
                self._log(f"{label} error: {exc}")
                box[0] = {"status": "error", "error": str(exc), "traceback": traceback.format_exc()}
            finally:
                done.set()

        try:
            self.schedule_message(0, on_main_thread)
        except (AssertionError, RuntimeError):
            on_main_thread()
        if done.wait(timeout=EXEC_TIMEOUT):
            return box[0]
        return {"status": "error", "error": f"Timed out after {EXEC_TIMEOUT}s"}

    def _build_scope(self) -> dict[str, Any]:
        """Assemble the namespace available to executed code."""
        import Live

        song = self.song()
        app = self.application()
        bro = app.browser if app else None

        def find_track(name):
            """Find a track by name (case-insensitive). Returns the Track or None."""
            q = name.lower()
            for t in song.tracks:
                if t.name.lower() == q:
                    return t
            return None

        def load_to(track, parent, query):
            """Find a browser item and load it onto a track.
            Returns the BrowserItem. Raises ValueError if not found."""
            item = find_item(parent, query)
            if item is None:
                self._log(f"load_to: no match for {query!r} in {parent.name}")
                raise ValueError(f"No loadable item matching {query!r}")
            self._log(f"load_to: {query!r} → '{item.name}' → track '{track.name}'")
            song.view.selected_track = track
            bro.load_item(item)
            return item

        return {
            "song": song,
            "app": app,
            "tracks": song.tracks,
            "returns": song.return_tracks,
            "master": song.master_track,
            "browser": bro,
            "Live": Live,
            "MidiNoteSpecification": Live.Clip.MidiNoteSpecification,
            "find_item": find_item,
            "find_items": find_items,
            "find_track": find_track,
            "load_to": load_to,
            "log": self.log_message,
            "json": json,
            "time": time,
        }


# ---- Built-in helpers (injected into every execution scope) ----


def find_items(parent: Any, query: str, max_depth: int = 5, limit: int = 20) -> list:
    """Search a browser tree breadth-first for loadable items matching query
    (case-insensitive substring). Returns a ranked list of BrowserItems:
    exact name matches first, then starts-with, then substring."""
    q = query.lower()
    exact, prefix, substring = [], [], []

    # BFS — items closer to the root are found first within each rank
    queue = [(parent, 0)]
    while queue:
        node, depth = queue.pop(0)
        if depth > max_depth:
            continue
        try:
            for child in node.children:
                if child.is_loadable:
                    name = child.name.lower()
                    # Strip file extension for matching
                    bare = name.rsplit(".", 1)[0] if "." in name else name
                    if bare == q:
                        exact.append(child)
                    elif bare.startswith(q):
                        prefix.append(child)
                    elif q in name:
                        substring.append(child)
                if hasattr(child, "children") and child.children:
                    queue.append((child, depth + 1))
        except (AttributeError, RuntimeError):
            # Live API may raise AttributeError on stale refs or
            # RuntimeError on objects that vanish mid-iteration.
            pass

    results = exact + prefix + substring
    return results[:limit]


def find_item(parent: Any, query: str, max_depth: int = 5) -> Any:
    """Search a browser tree for the best-matching loadable item.
    Returns a BrowserItem or None. Prefers exact matches over substrings,
    and shallow results over deep ones (breadth-first)."""
    results = find_items(parent, query, max_depth=max_depth, limit=1)
    return results[0] if results else None


# ---- Serialization (module-level for testability) ----


def serialize(obj: Any, _depth: int = 0) -> Any:
    """Convert Live API objects into JSON-serializable Python types.

    Max depth of 4 prevents runaway recursion on circular refs.
    """
    if _depth > 4:
        return str(obj)

    d = _depth + 1

    # Primitives
    if obj is None or isinstance(obj, (bool, int, float)):
        return obj
    if isinstance(obj, str):
        return obj
    if isinstance(obj, bytes):
        return obj.decode("utf-8", errors="replace")

    # Standard collections
    if isinstance(obj, dict):
        return {str(k): serialize(v, d) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [serialize(x, d) for x in obj]
    if isinstance(obj, (set, frozenset)):
        return [serialize(x, d) for x in sorted(obj, key=str)]

    # MIDI notes (duck-typed by pitch + start_time)
    if hasattr(obj, "pitch") and hasattr(obj, "start_time"):
        try:
            return {
                "pitch": obj.pitch,
                "start_time": obj.start_time,
                "duration": obj.duration,
                "velocity": obj.velocity,
                "mute": getattr(obj, "mute", False),
            }
        except Exception:
            return str(obj)

    # Named Live API objects (Track, Device, Scene, etc.)
    if hasattr(obj, "name"):
        try:
            out = {"name": obj.name}
            for attr in (
                "value",
                "min",
                "max",
                "is_enabled",
                "is_active",
                "is_quantized",
            ):
                if hasattr(obj, attr):
                    try:
                        out[attr] = serialize(getattr(obj, attr), d)
                    except Exception:
                        pass
            return out
        except Exception:
            return str(obj)

    # Generic iterables (Live API vectors, etc.)
    try:
        return [serialize(x, d) for x in obj]
    except (TypeError, RuntimeError):
        return str(obj)
