"""One user of Live at a time, and a note of what to put back if that user dies.

Two things made a weird Live state possible however careful each command was (2026-11-20):

- Nothing stopped two commands driving Live at once (an agent that runs two `hands` calls in parallel, a
  reset during a render). Each records through the same Render track and moves the same playhead.
- A render changes Live for a while (a Render track, record mode, the tempo, a grid's fader values) and
  puts it back in a `finally`. A command that is killed (the web app's time limit, a crash, a restart)
  never reaches it.

So every command that changes Live runs inside `using_live`: an exclusive lock on <data_dir>/live.lock
(flock: a dead holder lets go by itself). And before a command changes something it means to put back,
it writes the Live code that puts it back to <data_dir>/live-undo.json (`undo`, `note`); the entry goes
when that code has run. Whoever takes the lock next (any command, or `hands rig reset`) finds what is
left there and runs it first (`replay`). SIGTERM is turned into an ordinary exit while the lock is held,
so `finally` blocks run and most kills leave nothing to replay.
"""

from __future__ import annotations

import contextlib
import fcntl
import json
import os
import signal
import threading
import time
import uuid
from collections.abc import Iterator
from pathlib import Path

from hands import config
from hands.live.transport import LOST, UNREACHABLE, LiveError, McpTransport

LOCK, UNDO = "live.lock", "live-undo.json"
STALE_S = 24 * 3600.0  # an undo note this old is for a set that has moved on: dropped, with a word


class Busy(RuntimeError):
    """Another hands command is using Live."""

    def __init__(self, holder: dict, waited: float) -> None:
        self.holder = holder
        what = holder.get("what") or "another hands command"
        age = f", for {time.time() - holder['at']:.0f} s" if isinstance(holder.get("at"), (int, float)) else ""
        super().__init__(
            f"Live is busy with `{what}` (waited {waited:.0f} s{age}). Run one hands command at a time: "
            "wait for that one to finish, then run this again."
        )


def _dir() -> Path:
    d = config.rig().data_dir
    d.mkdir(parents=True, exist_ok=True)
    return d


def holder() -> dict:
    """Which other command holds Live now, as it wrote itself: {pid, what, at}. {} when nobody does, or
    when this process is the one holding it."""
    if _depth:
        return {}
    try:
        with open(_dir() / LOCK, "a+") as f:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                f.seek(0)
                try:
                    h = json.loads(f.read() or "{}")
                except ValueError:
                    h = {}
                return h if isinstance(h, dict) and h else {"what": "another hands command"}
            fcntl.flock(f, fcntl.LOCK_UN)
    except OSError:
        pass
    return {}


_depth = 0


@contextlib.contextmanager
def using_live(what: str, *, wait_s: float = 300.0, client: McpTransport | None = None) -> Iterator[list[str]]:
    """Hold Live for one command. Waits for another command to finish (Busy after wait_s). With a client,
    first puts back what an interrupted command left; yields what that did, one line each."""
    global _depth
    if _depth:  # a command inside a command (a reset that renders): already held
        _depth += 1
        try:
            yield []
        finally:
            _depth -= 1
        return
    f = open(_dir() / LOCK, "a+")
    t0 = time.monotonic()
    try:
        while True:
            try:
                fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except OSError:
                waited = time.monotonic() - t0
                if waited >= wait_s:
                    f.seek(0)
                    try:
                        h = json.loads(f.read() or "{}")
                    except ValueError:
                        h = {}
                    raise Busy(h if isinstance(h, dict) else {}, waited) from None
                time.sleep(0.5)
        f.seek(0)
        f.truncate()
        f.write(json.dumps({"pid": os.getpid(), "what": what, "at": time.time()}))
        f.flush()
        main = threading.current_thread() is threading.main_thread()
        old = signal.signal(signal.SIGTERM, _terminate) if main else None
        _depth = 1
        try:
            yield replay(client) if client is not None else []
        finally:
            _depth = 0
            if main:
                signal.signal(signal.SIGTERM, old)
            with contextlib.suppress(OSError):
                f.seek(0)
                f.truncate()
    finally:
        f.close()  # closing lets the lock go


def _terminate(signum, frame) -> None:
    raise SystemExit(143)  # unwinds through every `finally`, so Live is put back


# ---------------------------------------------------------------- what to put back


def pending() -> list[dict]:
    try:
        entries = json.loads((_dir() / UNDO).read_text())
    except (OSError, ValueError):
        return []
    return (
        [e for e in entries if isinstance(e, dict) and isinstance(e.get("code"), str)]
        if isinstance(entries, list)
        else []
    )


def _write(entries: list[dict]) -> None:
    f = _dir() / UNDO
    if not entries:
        f.unlink(missing_ok=True)
        return
    tmp = f.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps(entries))
    os.replace(tmp, f)


_set = ""  # the file of the set the running command works on (P._state tells us)
SET_PATH = "result = str(getattr(song, 'file_path', '') or '')"


def on_set(path: str | None) -> None:
    """The open set's file, so notes say which set they are for: one is never run against another set."""
    global _set
    _set = str(path or "")


def note(what: str, code: str) -> str:
    """Write down Live code that puts back what the caller is about to change. Returns the note's id."""
    entry = {
        "id": uuid.uuid4().hex[:12],
        "what": what,
        "code": code,
        "pid": os.getpid(),
        "at": time.time(),
        "set": _set,
    }
    try:
        _write([*pending(), entry])
    except OSError:
        pass  # a full disk must not stop the command; it only loses the safety net
    return entry["id"]


def forget(note_id: str) -> None:
    try:
        _write([e for e in pending() if e.get("id") != note_id])
    except OSError:
        pass


@contextlib.contextmanager
def undo(client: McpTransport, what: str, code: str) -> Iterator[None]:
    """Run the body, then `code` in Live whatever happened. The code is on disk while the body runs, so a
    killed process leaves it for the next command. If Live will not take it now, it stays there."""
    note_id = note(what, code)
    failed = True
    try:
        yield
        failed = False
    finally:
        try:
            client.run(code)
            forget(note_id)
        except LiveError as exc:
            if not _unreachable(exc):
                forget(note_id)  # Live answered and refused: trying again later would refuse again
            if not failed:
                raise


def settle(client: McpTransport, note_id: str) -> None:
    """Run a note's code now (the caller failed and is cleaning up). Never raises: the caller's own error is the
    one to show. The note stays if Live did not answer."""
    entry = next((e for e in pending() if e.get("id") == note_id), None)
    if entry is None:
        return
    try:
        client.run(entry["code"])
    except LiveError as exc:
        if _unreachable(exc):
            return
    except Exception:
        pass
    forget(note_id)


def _unreachable(exc: LiveError) -> bool:
    return UNREACHABLE in str(exc) or LOST in str(exc) or "Timed out" in str(exc)


def replay(client: McpTransport) -> list[str]:
    """Run what interrupted commands left to put back, newest first. One line per note: what was done."""
    entries = pending()
    if not entries:
        return []
    done: list[str] = []
    left: list[dict] = []
    try:
        open_set = str(client.run(SET_PATH) or "")
    except LiveError as exc:
        if _unreachable(exc):
            return []  # Live is not answering: every note waits
        open_set = ""
    for e in reversed(entries):
        what = str(e.get("what") or "an interrupted command")
        if time.time() - float(e.get("at") or 0) > STALE_S:
            done.append(f"dropped an old note to put back {what} (over a day old)")
            continue
        if e.get("set") and open_set and e["set"] != open_set:
            done.append(
                f"dropped a note to put back {what}: it was for {Path(e['set']).stem}, and {Path(open_set).stem} is open now"
            )
            continue
        try:
            client.run(e["code"])
            done.append(f"put back {what}, left by an interrupted command")
        except LiveError as exc:
            if _unreachable(exc):
                left.insert(0, e)  # Live is not answering: keep it for the reset
            else:
                done.append(f"could not put back {what} ({str(exc)[:120]})")
    with contextlib.suppress(OSError):
        _write(left)
    return done


def save_json(path: Path, data) -> None:
    """Write a panel's or a song's file whole or not at all (a cut-short file reads as no panel)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(json.dumps(data))
    os.replace(tmp, path)
