"""The artist agent's store (docs/artist-agent.md): Anthony's thumbs and his answers, the plates the gallery keeps,
and the repertoire of works the page chooses from.

    <root>/artist.sqlite3   feedback, questions, answers, plates, repertoire versions

A press is stored the moment it arrives, before any question is asked: the vote counts whether or not he answers.
Works are descriptions over the page's primitives (PRIMITIVES, the same ranges as map/works.js); a repertoire that
strays outside them is refused, so the artist can compose and tune but never invent a primitive (new ones come by
reviewed PR). Everything runs on the event loop's thread; the writes are tiny.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
import sqlite3
import time
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

from .narrator import HaikuLines
from .store import new_id

log = logging.getLogger(__name__)

SEED = Path(__file__).parent / "static" / "checklist" / "map" / "works.json"     # the first repertoire

SCHEMA = """
CREATE TABLE IF NOT EXISTS feedback (
    id TEXT PRIMARY KEY, at REAL NOT NULL, vote TEXT NOT NULL, view TEXT NOT NULL, context TEXT NOT NULL,
    client_ts REAL);
CREATE TABLE IF NOT EXISTS questions (
    feedback TEXT PRIMARY KEY, at REAL NOT NULL, question TEXT NOT NULL, choices TEXT NOT NULL, by TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT, feedback TEXT NOT NULL, at REAL NOT NULL, text TEXT NOT NULL,
    choice TEXT);
CREATE INDEX IF NOT EXISTS answers_by_feedback ON answers (feedback, id);
CREATE TABLE IF NOT EXISTS plates (
    id TEXT PRIMARY KEY, n INTEGER NOT NULL, at REAL NOT NULL, track TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS plates_by_track ON plates (track, n);
CREATE TABLE IF NOT EXISTS repertoire (
    version INTEGER PRIMARY KEY, at REAL NOT NULL, parent INTEGER, notes TEXT NOT NULL, works TEXT NOT NULL);
"""

VOTES = ("up", "down")
CONTEXT_MAX = 8 * 1024          # bytes of context JSON kept with a press
TEXT_MAX = 2000                 # an answer's text
PLATE_MAX = 64 * 1024           # a plate's JSON

# The page's vocabulary (map/works.js): every work's params use exactly these, in these ranges.
PRIMITIVES: dict[str, Any] = {
    "seal": ("check", "wax"),
    "particles": {"power": (0.3, 2.0), "palette": ("white", "gold", "ember", "ink")},
    "shake": (0.0, 1.6),
    "hitstop": (30, 220),
    "lift": (90, 150),
    "lamp": bool,
    "sky": ("none", "stars"),
    "pace": (0.75, 1.35),
}
WORK_KEYS = {"id", "title", "about", "weight", "rarity", "when", "params"}
WORK_ID = re.compile(r"[a-z0-9-]{2,32}")


class Invalid(ValueError):
    """A repertoire or a work that the page could not perform."""


def _check(value: Any, spec: Any, where: str) -> None:
    if spec is bool:
        if not isinstance(value, bool):
            raise Invalid(f"{where}: expected true or false")
    elif isinstance(spec, dict):
        if not isinstance(value, dict):
            raise Invalid(f"{where}: expected an object")
        if extra := set(value) - set(spec):
            raise Invalid(f"{where}: unknown {sorted(extra)}")
        if missing := set(spec) - set(value):
            raise Invalid(f"{where}: missing {sorted(missing)}")
        for k, sub in spec.items():
            _check(value[k], sub, f"{where}.{k}")
    elif isinstance(spec, tuple) and all(isinstance(s, str) for s in spec):
        if value not in spec:
            raise Invalid(f"{where}: {value!r} is not one of {list(spec)}")
    else:
        lo, hi = spec
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not lo <= value <= hi:
            raise Invalid(f"{where}: {value!r} is outside {lo}..{hi}")


def validate(works: Any) -> list[dict]:
    """The works if the page can perform every one of them; else Invalid naming the first problem."""
    if not isinstance(works, list) or not works:
        raise Invalid("works: expected a non-empty list")
    seen: set[str] = set()
    for i, w in enumerate(works):
        where = f"works[{i}]"
        if not isinstance(w, dict):
            raise Invalid(f"{where}: expected an object")
        if extra := set(w) - WORK_KEYS:
            raise Invalid(f"{where}: unknown {sorted(extra)}")
        wid = w.get("id")
        if not isinstance(wid, str) or not WORK_ID.fullmatch(wid):
            raise Invalid(f"{where}.id: {wid!r} is not [a-z0-9-]{{2,32}}")
        if wid in seen:
            raise Invalid(f"{where}.id: {wid!r} twice")
        seen.add(wid)
        where = f"works[{wid}]"
        if not isinstance(w.get("title"), str) or not 0 < len(w["title"]) <= 40:
            raise Invalid(f"{where}.title: 1 to 40 characters")
        if not isinstance(w.get("about"), str) or len(w["about"]) > 140:
            raise Invalid(f"{where}.about: at most 140 characters")
        _check(w.get("weight"), (0, 10), f"{where}.weight")
        _check(w.get("rarity"), (0.02, 1), f"{where}.rarity")
        if "when" in w:
            _check(w["when"], {"night": bool}, f"{where}.when")
        _check(w.get("params"), PRIMITIVES, f"{where}.params")
    return works


class Artist:
    def __init__(self, root: Path, seed: Path):
        self.root, self.seed = root, seed
        root.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(root / "artist.sqlite3", isolation_level=None, check_same_thread=False)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=NORMAL")
        self.db.executescript(SCHEMA)

    def close(self) -> None:
        self.db.close()

    # --- thumbs, questions, answers ------------------------------------------------------------------------------
    def add_feedback(self, vote: str, view: str, context: Any, client_ts: float | None = None) -> dict[str, Any]:
        if vote not in VOTES:
            raise ValueError(f"vote is one of {VOTES}")
        ctx = json.dumps(context if context is not None else {}, separators=(",", ":"))
        if len(ctx.encode()) > CONTEXT_MAX:
            ctx = json.dumps({"truncated": ctx[:CONTEXT_MAX - 64]})
        fid, at = new_id("fb_"), time.time()
        self.db.execute("INSERT INTO feedback (id, at, vote, view, context, client_ts) VALUES (?, ?, ?, ?, ?, ?)",
                        (fid, at, vote, str(view)[:64], ctx, client_ts))
        return {"id": fid, "at": at}

    def event(self, fid: str) -> dict[str, Any] | None:
        row = self.db.execute("SELECT id, at, vote, view, context, client_ts FROM feedback WHERE id = ?",
                              (fid,)).fetchone()
        return _feedback(row) if row else None

    def set_question(self, fid: str, question: str, choices: list[str], by: str) -> None:
        self.db.execute("INSERT OR REPLACE INTO questions (feedback, at, question, choices, by) VALUES (?, ?, ?, ?, ?)",
                        (fid, time.time(), question, json.dumps(choices), by))

    def add_answer(self, fid: str, text: str, choice: str | None = None) -> None:
        if self.event(fid) is None:
            raise KeyError(fid)
        self.db.execute("INSERT INTO answers (feedback, at, text, choice) VALUES (?, ?, ?, ?)",
                        (fid, time.time(), str(text or "")[:TEXT_MAX], None if choice is None else str(choice)[:200]))

    def feedback(self, limit: int = 50) -> list[dict[str, Any]]:
        """The newest presses first, each with its question and answers."""
        limit = max(1, min(limit, 1000))
        rows = self.db.execute("SELECT id, at, vote, view, context, client_ts FROM feedback ORDER BY at DESC, rowid DESC "
                               "LIMIT ?", (limit,)).fetchall()
        out = []
        for row in rows:
            fb = _feedback(row)
            q = self.db.execute("SELECT question, choices, by FROM questions WHERE feedback = ?", (fb["id"],)).fetchone()
            fb["question"] = {"question": q[0], "choices": json.loads(q[1]), "by": q[2]} if q else None
            fb["answers"] = [{"at": a, "text": t, "choice": c} for a, t, c in self.db.execute(
                "SELECT at, text, choice FROM answers WHERE feedback = ? ORDER BY id", (fb["id"],))]
            out.append(fb)
        return out

    # --- plates --------------------------------------------------------------------------------------------------
    def add_plate(self, plate: dict[str, Any]) -> tuple[str, int, float]:
        """Keep a plate; returns its id, its number in the whole gallery (1, 2, ...) and when it was kept."""
        if not isinstance(plate, dict) or not isinstance(plate.get("track"), str) or not plate["track"]:
            raise ValueError("a plate needs its track")
        data = json.dumps(plate, separators=(",", ":"))
        if len(data.encode()) > PLATE_MAX:
            raise ValueError("plate too large")
        pid, at = new_id("pl_"), time.time()
        n = (self.db.execute("SELECT COALESCE(MAX(n), 0) FROM plates").fetchone()[0] or 0) + 1
        self.db.execute("INSERT INTO plates (id, n, at, track, data) VALUES (?, ?, ?, ?, ?)",
                        (pid, n, at, plate["track"], data))
        return pid, n, at

    def plates(self, track: str | None = None) -> list[dict[str, Any]]:
        q = "SELECT id, n, at, track, data FROM plates" + (" WHERE track = ?" if track else "") + " ORDER BY n"
        rows = self.db.execute(q, (track,) if track else ()).fetchall()
        return [{**json.loads(d), "id": pid, "n": n, "at": at, "track": tr} for pid, n, at, tr, d in rows]

    # --- the repertoire ------------------------------------------------------------------------------------------
    def repertoire(self) -> dict[str, Any]:
        """The newest version; the first time, the seed (map/works.json) as version 1."""
        row = self.db.execute("SELECT version, at, parent, notes, works FROM repertoire ORDER BY version DESC "
                              "LIMIT 1").fetchone()
        if row is None:
            seed = json.loads(self.seed.read_text())
            works = validate(seed["works"])
            self.db.execute("INSERT INTO repertoire (version, at, parent, notes, works) VALUES (1, ?, NULL, ?, ?)",
                            (time.time(), seed.get("notes", "The seed."), json.dumps(works)))
            return self.repertoire()
        version, at, parent, notes, works = row
        return {"version": version, "at": at, "parent": parent, "notes": notes, "works": json.loads(works)}

    def set_repertoire(self, works: list[dict], notes: str) -> int:
        works = validate(works)
        current = self.repertoire()
        version = current["version"] + 1
        self.db.execute("INSERT INTO repertoire (version, at, parent, notes, works) VALUES (?, ?, ?, ?, ?)",
                        (version, time.time(), current["version"], str(notes)[:2000], json.dumps(works)))
        return version


def _feedback(row: tuple) -> dict[str, Any]:
    fid, at, vote, view, context, client_ts = row
    return {"id": fid, "at": at, "vote": vote, "view": view, "context": json.loads(context), "client_ts": client_ts}


# --- the quick question ----------------------------------------------------------------------------------------
ModelFn = Callable[[str], Awaitable[str]]
ASK_TIMEOUT_S = 6.0

ASK_PROMPT = """Anthony just pressed thumbs {vote} in his music-production app ({view} view). What was on screen \
and had just played:
{context}

Ask him ONE short question (at most 14 words) to learn what exactly he {verb}, so the app's juice (animations, \
sounds, the map) can be tuned to him. Offer 2 to 4 short answer choices (each at most 4 words) naming things that \
were actually on screen. Reply with JSON only: {{"question": "...", "choices": ["...", "..."]}}"""


def rules_question(event: dict[str, Any]) -> dict[str, Any]:
    """A question from the context alone, when there is no model or it fails."""
    ctx = event.get("context") or {}
    up = event.get("vote") == "up"
    view = str(event.get("view") or "")
    params = ((ctx.get("work") or {}).get("params") or {}) if isinstance(ctx, dict) else {}
    recent = isinstance(ctx, dict) and ctx.get("work") and (ctx.get("work_ago_ms") is None or ctx["work_ago_ms"] < 20000)
    choices: list[str] = []
    if recent or view in ("splash", "ledger"):
        choices += ["The sound", "The shake"]
        if params.get("seal") == "wax":
            choices.append("The wax seal")
        elif params.get("lamp"):
            choices.append("The lamp light")
        else:
            choices.append("The stamp")
        choices.append("The map's camera")
    elif view in ("explore", "card"):
        choices += ["The map", "The finds", "The words"]
    elif view == "widget":
        choices += ["The controls", "The measures", "The player"]
    elif view == "gallery":
        choices += ["The plates", "The renders", "The layout"]
    else:
        choices += ["The look", "The timing"]
    choices = choices[:3] + ["Something else"]
    return {"question": "What landed?" if up else "What was off?", "choices": choices, "by": "rules"}


def _parse(text: str) -> dict[str, Any] | None:
    m = re.search(r"\{.*\}", text or "", re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
    except ValueError:
        return None
    q, choices = data.get("question"), data.get("choices")
    if not isinstance(q, str) or not q.strip() or len(q.split()) > 18:
        return None
    if not isinstance(choices, list) or not 2 <= len(choices) <= 4 or not all(isinstance(c, str) and c for c in choices):
        return None
    return {"question": q.strip(), "choices": [c.strip()[:40] for c in choices], "by": "model"}


class QuestionLines(HaikuLines):
    """The quick question's model: the narrator's long-lived small-model CLI, with its own instructions."""

    SYSTEM = "You ask one short, friendly question and reply with JSON only."


async def ask(event: dict[str, Any], model_fn: ModelFn | None = None) -> dict[str, Any]:
    """The quick question after a press: from the small model if there is one and it answers in time, else from
    the rules. Never raises."""
    if model_fn is not None:
        up = event.get("vote") == "up"
        prompt = ASK_PROMPT.format(vote="up" if up else "down", view=event.get("view", ""),
                                   verb="liked" if up else "disliked",
                                   context=json.dumps(event.get("context") or {}, indent=1)[:3000])
        try:
            got = _parse(await asyncio.wait_for(model_fn(prompt), ASK_TIMEOUT_S))
            if got:
                return got
        except Exception:  # noqa: BLE001 - a slow or failed model falls back to the rules
            log.info("artist question: the model failed, asking by the rules", exc_info=True)
    return rules_question(event)


# --- the offline artist: a new repertoire from what he did and said --------------------------------------------
PRESS_WINDOW_S = 20.0           # a press this soon after a plate is taken as about that plate's work

PROPOSE_PROMPT = """You are the artist agent of zpkt's studio app (docs/artist-agent.md). Your job is to make the \
app more rewarding to use for Anthony, a music producer, by choosing and tuning the "works" the page plays when he \
checks off a production task: a stamp, particles, a shake, a freeze on contact, the map's camera, a lamp in the \
settled room, stars at night, a rare wax seal.

Rules:
- Compose ONLY from these primitives and ranges (new primitives come by reviewed pull request, never from you):
{primitives}
- Each work: {{"id": "[a-z0-9-]{{2,32}}", "title": "<=40 chars", "about": "<=140 chars, what he will notice", \
"weight": 0-10, "rarity": 0.02-1, "when": {{"night": true}} (optional), "params": {{...every primitive...}}}}.
- Keep every existing work (you may change its weight, rarity and params; set weight 0 to rest one he dislikes).
- Add at most 3 new works. Most of what is offered should sit near what he liked; about one in ten deliberately \
outside it, since a delight is partly surprise. Novelty wears off: rotate, keep rare things rare.
- Rewards follow work only: nothing that nags, counts down or punishes stopping.

The current repertoire (version {version}):
{works}

What happened since (plates are commits and the work that played; presses within {window:.0f} s of a plate are \
attributed to it; answers are his words):
{brief}

Reply with JSON only: {{"notes": "two or three sentences: what you changed and why", "works": [...the whole new \
repertoire...]}}"""


def brief(store: Artist, limit: int = 200) -> dict[str, Any]:
    """What the artist reads: per work, how often it played and the presses that followed it; and his words."""
    plates = store.plates()[-limit:]
    presses = list(reversed(store.feedback(limit)))
    works: dict[str, dict[str, Any]] = {}
    for p in plates:
        w = _work_id(p) or "?"
        works.setdefault(w, {"played": 0, "up": 0, "down": 0})["played"] += 1
    for fb in presses:
        before = [p for p in plates if 0 <= fb["at"] - p["at"] <= PRESS_WINDOW_S]
        w = (_work_id(before[-1]) if before else None) or _work_id(fb.get("context"))
        if w:
            works.setdefault(w, {"played": 0, "up": 0, "down": 0})[fb["vote"]] += 1
    said = [{"vote": fb["vote"], "view": fb["view"], "question": (fb.get("question") or {}).get("question"),
             "answers": [a["choice"] or a["text"] for a in fb["answers"]]} for fb in presses if fb["answers"]]
    return {"plates": len(plates), "presses": len(presses), "works": works, "said": said[-40:],
            "views": {v: sum(1 for fb in presses if fb["view"] == v) for v in {fb["view"] for fb in presses}}}


def show(store: Artist) -> str:
    """A plain report: counts, the last presses with answers, plates per track, the repertoire."""
    rep = store.repertoire()
    fb = store.feedback(20)
    plates = store.plates()
    tracks: dict[str, int] = {}
    for p in plates:
        tracks[p["track"]] = tracks.get(p["track"], 0) + 1
    lines = [f"repertoire v{rep['version']} (parent {rep['parent']}): " + ", ".join(
        f"{w['id']} w{w['weight']} r{w['rarity']}" for w in rep["works"]), f"  {rep['notes']}",
        f"plates: {len(plates)} " + (", ".join(f"{t} {n}" for t, n in tracks.items()) if tracks else ""),
        f"last {len(fb)} presses:"]
    for f in fb:
        when = time.strftime("%m-%d %H:%M", time.localtime(f["at"]))
        work = _work_id(f["context"])
        q = f["question"]["question"] if f["question"] else ""
        a = "; ".join(x["choice"] or x["text"] for x in f["answers"])
        lines.append(f"  {when} {f['vote']:4} {f['view']:8} {work or '-':10} {q} {('-> ' + a) if a else ''}".rstrip())
    return "\n".join(lines)


async def propose(store: Artist, model: str | None, cli_path: str | None, env: dict[str, str],
                  dry_run: bool = False) -> dict[str, Any]:
    """Ask Claude for the next repertoire; validate it; keep it as the next version unless dry_run."""
    from claude_agent_sdk import AssistantMessage, ClaudeAgentOptions, TextBlock, query

    rep = store.repertoire()
    prompt = PROPOSE_PROMPT.format(primitives=json.dumps({k: _spec(v) for k, v in PRIMITIVES.items()}, indent=1),
                                   version=rep["version"], works=json.dumps(rep["works"], indent=1),
                                   window=PRESS_WINDOW_S, brief=json.dumps(brief(store), indent=1))
    options = ClaudeAgentOptions(model=model, cli_path=cli_path, tools=[], setting_sources=[], max_turns=1,
                                 system_prompt="You are a careful game-feel artist. Reply with JSON only.",
                                 extra_args={"no-session-persistence": None},
                                 env={**env, "ENABLE_CLAUDEAI_MCP_SERVERS": "false"})
    parts: list[str] = []
    async for msg in query(prompt=prompt, options=options):
        if isinstance(msg, AssistantMessage):
            parts += [b.text for b in msg.content if isinstance(b, TextBlock)]
    text = " ".join(parts)
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        raise Invalid("the artist did not reply with JSON")
    data = json.loads(m.group(0))
    works = validate(data.get("works"))
    kept = {w["id"] for w in rep["works"]}
    if missing := kept - {w["id"] for w in works}:
        raise Invalid(f"the artist dropped works {sorted(missing)} (rest them with weight 0 instead)")
    if len({w["id"] for w in works} - kept) > 3:
        raise Invalid("the artist added more than 3 works")
    notes = str(data.get("notes") or "")
    out = {"notes": notes, "works": works, "version": None}
    if not dry_run:
        out["version"] = store.set_repertoire(works, notes)
    return out


def _work_id(d: Any) -> str | None:
    """The id of the work a plate or a press's context names, if any."""
    w = d.get("work") if isinstance(d, dict) else None
    return w.get("id") if isinstance(w, dict) else (w if isinstance(w, str) else None)


def _spec(v: Any) -> Any:
    if v is bool:
        return "true or false"
    if isinstance(v, dict):
        return {k: _spec(x) for k, x in v.items()}
    if all(isinstance(x, str) for x in v):
        return " | ".join(v)
    return f"{v[0]} to {v[1]}"
