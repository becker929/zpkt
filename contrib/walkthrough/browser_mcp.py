"""The persona's only tools: a browser on the zpkt app, a journal, a notebook and checkpoints (Anthony, 27 Nov 2026).

A stdio MCP server with no dependency beyond Playwright (already in zpkt's dev extras). The cold agent that plays the
persona gets these tools and nothing else: no shell, no files, no Live. The browser may open only the app's own
address; every other address is refused.

Run by run.py: `python browser_mcp.py --run <run folder> --leg <n>`.
"""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import sys
import time
import traceback
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Error as PWError
from playwright.sync_api import Page, sync_playwright

APP = os.environ.get("WT_APP", "http://127.0.0.1:8985")
VIEW = {"width": 1180, "height": 800}
SHOTS_PER_LEG = int(os.environ.get("WT_SHOTS", "12"))
TEXT_CAP = 14000


def _out(msg: dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()


class Harness:
    def __init__(self, run: Path, leg: int) -> None:
        self.run, self.leg = run, leg
        (run / "shots").mkdir(parents=True, exist_ok=True)
        self.pw = sync_playwright().start()
        self.browser = self.pw.webkit.launch()
        self.ctx = self.browser.new_context(viewport=VIEW, device_scale_factor=1)
        self.page: Page = self.ctx.new_page()
        self.console: list[str] = []
        self.page.on("console", lambda m: m.type in ("error", "warning") and self.console.append(f"{m.type}: {m.text}"))
        self.page.on("pageerror", lambda e: self.console.append(f"pageerror: {e}"))
        self.page.on("dialog", lambda d: d.dismiss())
        self.shots = 0
        self.last_shot: str | None = None
        self.actions = 0

    # ---- the journal ------------------------------------------------------------------------------------------------
    def log(self, kind: str, title: str, body: str = "", shot: str | None = None, **extra: Any) -> None:
        row = {"at": time.time(), "leg": self.leg, "kind": kind, "title": title, "body": body, "shot": shot, **extra}
        with (self.run / "journal.jsonl").open("a") as f:
            f.write(json.dumps(row) + "\n")

    # ---- helpers ----------------------------------------------------------------------------------------------------
    def settle(self, ms: int = 600) -> None:
        self.page.wait_for_timeout(ms)

    def status(self) -> str:
        """What a person would notice after an action: toasts, alerts, dialogs, the address."""
        bits = []
        for sel in ('[role="alert"]', '[role="status"]', ".toast"):
            for el in self.page.locator(sel).all()[:4]:
                try:
                    t = el.inner_text(timeout=300).strip()
                except PWError:
                    continue
                if t:
                    bits.append(t[:200])
        return ("Notices on screen: " + " | ".join(dict.fromkeys(bits))) if bits else "No notice on screen."

    def frames(self) -> list[Any]:
        """The page and the app's own frames in it (the Ask chat is a frame), in that order: what a person sees."""
        app = urlparse(APP).netloc
        inner = [f for f in self.page.frames if f is not self.page.main_frame and urlparse(f.url).netloc == app]
        return [self.page.main_frame, *inner]

    def target(self, role: str | None, name: str | None, text: str | None, nth: int):
        """The element by role and name (or text), on the page or inside one of the app's frames."""
        if not role and not text:
            raise ValueError("give a role (and name) or a text")
        for exact in (True, False):  # the element whose name is exactly that first, as a person reads a label
            for frame in self.frames():
                if role:
                    loc = frame.get_by_role(role, name=name, exact=exact) if name else frame.get_by_role(role)
                else:
                    loc = frame.get_by_text(text, exact=exact)
                loc = loc.filter(visible=True)
                n = loc.count()
                if n:
                    return loc.nth(min(nth, n - 1)), n
        raise ValueError(f"nothing on the page matches {role or 'text'} {name or text!r}")

    # ---- tools ------------------------------------------------------------------------------------------------------
    def t_open_app(self, path: str = "/app/") -> str:
        url = APP + (path if path.startswith("/") else "/" + path)
        if urlparse(url).netloc != urlparse(APP).netloc:
            raise ValueError("only the zpkt app may be opened")
        self.page.goto(url, wait_until="domcontentloaded")
        self.settle(2500)
        return f"Opened {self.page.url}. {self.status()}"

    def t_look(self) -> str:
        if urlparse(self.page.url).netloc != urlparse(APP).netloc:
            return "No page is open yet: call open_app first."
        snap = self.page.locator("body").aria_snapshot()
        for frame in self.frames()[1:]:
            try:
                inner = frame.locator("body").aria_snapshot(timeout=2000)
            except PWError:
                continue
            path = urlparse(frame.url).path
            snap += f"\n\n--- inside the frame {path} (part of the page above) ---\n{inner}"
        if len(snap) > TEXT_CAP:
            snap = snap[:TEXT_CAP] + f"\n… ({len(snap) - TEXT_CAP} more characters; the page is long)"
        return f"Address: {self.page.url}\n{self.status()}\n\n{snap}"

    def t_read_text(self) -> str:
        text = "\n\n".join(f.locator("body").inner_text() for f in self.frames())
        return text[:TEXT_CAP]

    def t_click(self, role: str | None = None, name: str | None = None, text: str | None = None, nth: int = 0) -> str:
        loc, n = self.target(role, name, text, nth)
        loc.click(timeout=5000)
        self.settle()
        return f"Clicked ({n} matched, used #{nth}). {self.status()}"

    def t_type(self, name: str, text: str, submit: bool = False, role: str = "textbox") -> str:
        loc, _ = self.target(role, name, None, 0)
        loc.fill(text, timeout=5000)
        if submit:
            loc.press("Enter")
        self.settle()
        return f"Typed into {name!r}{' and pressed Enter' if submit else ''}. {self.status()}"

    def t_choose(self, name: str, option: str) -> str:
        loc, _ = self.target("combobox", name, None, 0)
        loc.select_option(label=option, timeout=5000)
        self.settle()
        return f"Chose {option!r} in {name!r}. {self.status()}"

    def t_press(self, key: str) -> str:
        self.page.keyboard.press(key)
        self.settle(300)
        return f"Pressed {key}. {self.status()}"

    def t_drag(self, role: str, name: str, dx: float = 0, dy: float = 0, nth: int = 0) -> str:
        loc, _ = self.target(role, name, None, nth)
        box = loc.bounding_box()
        if not box:
            raise ValueError("that element is not visible")
        x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
        m = self.page.mouse
        m.move(x, y)
        m.down()
        for k in range(1, 11):
            m.move(x + dx * k / 10, y + dy * k / 10)
            self.page.wait_for_timeout(30)
        m.up()
        self.settle()
        return f"Dragged {name!r} by ({dx:g}, {dy:g}) px. {self.status()}"

    def t_click_at(self, x: float, y: float) -> str:
        self.page.mouse.click(x, y)
        self.settle()
        return f"Clicked at ({x:g}, {y:g}). {self.status()}"

    def t_wait(self, seconds: float = 2) -> str:
        self.page.wait_for_timeout(max(0.2, min(float(seconds), 20)) * 1000)
        return f"Waited {seconds} s. {self.status()}"

    def t_screenshot(self, note: str = "") -> list[dict[str, Any]]:
        if self.shots >= SHOTS_PER_LEG:
            raise ValueError(f"no screenshots left in this leg (budget {SHOTS_PER_LEG}); use look instead")
        self.shots += 1
        name = f"leg{self.leg}-{int(time.time())}-{self.shots:02d}.png"
        path = self.run / "shots" / name
        self.page.screenshot(path=str(path))
        self.last_shot = name
        data = base64.b64encode(path.read_bytes()).decode()
        return [
            {"type": "text", "text": f"Screenshot {self.shots}/{SHOTS_PER_LEG} saved as {name}. {note}"},
            {"type": "image", "data": data, "mimeType": "image/png"},
        ]

    def t_console(self) -> str:
        got, self.console = self.console[-30:], []
        return "\n".join(got) or "No console errors or warnings since the last look."

    def t_journal(self, kind: str, title: str, body: str = "", attach_last_screenshot: bool = False) -> str:
        kinds = ("plan", "action", "result", "finding", "blocker", "praise", "question", "summary")
        if kind not in kinds:
            raise ValueError(f"kind is one of {', '.join(kinds)}")
        self.log(kind, title, body, self.last_shot if attach_last_screenshot else None)
        return "Written to the journal."

    def t_notes_read(self) -> str:
        f = self.run / "notes.md"
        return f.read_text() if f.exists() else "(empty: nothing written yet)"

    def t_notes_write(self, text: str) -> str:
        (self.run / "notes.md").write_text(text)
        return "Notebook saved."

    def t_checkpoint(self, label: str, summary: str) -> str:
        """Keep the song as it is saved now, with the notebook, so a later leg can start from here."""
        sets = Path(os.environ.get("WT_SETS", "~/Music/zpkt/sets")).expanduser()
        index = json.loads((sets / "songs.json").read_text())
        name = index.get("current")
        als = sets / f"{name}.als"
        if not name or not als.exists():
            raise ValueError("the app has no current song on file yet: make or save the song in the app first")
        age = time.time() - als.stat().st_mtime
        if age > 600:
            raise ValueError(
                f"the song {name} was last saved {age / 60:.0f} minutes ago: save it in the app first, then checkpoint"
            )
        cps = self.run / "checkpoints"
        cps.mkdir(exist_ok=True)
        n = len([p for p in cps.iterdir() if p.is_dir()]) + 1
        slug = "".join(c if c.isalnum() else "-" for c in label.lower()).strip("-")[:32] or "checkpoint"
        folder = cps / f"{n:02d}-{slug}"
        folder.mkdir()
        shutil.copy2(als, folder / als.name)
        notes = self.run / "notes.md"
        if notes.exists():
            shutil.copy2(notes, folder / "notes.md")
        meta = {"label": label, "summary": summary, "song": name, "leg": self.leg, "at": time.time()}
        (folder / "checkpoint.json").write_text(json.dumps(meta, indent=2))
        self.log("checkpoint", label, summary, None, checkpoint=folder.name, song=name)
        return f"Checkpoint {folder.name} kept (song {name}, saved {age:.0f} s ago)."

    def t_finish(self, summary: str) -> str:
        self.log("summary", f"End of leg {self.leg}", summary)
        return "Leg finished. Stop now: write nothing more."


S = {"type": "string"}
N = {"type": "number"}
TOOLS: list[dict[str, Any]] = [
    {
        "name": "open_app",
        "description": "Open the zpkt app in the browser (the only site you may open). path defaults to /app/.",
        "inputSchema": {"type": "object", "properties": {"path": S}},
    },
    {
        "name": "look",
        "description": "Read the page as its accessibility tree: every heading, button, slider, text box with its name. Use this to see what is there.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "read_text",
        "description": "The page's visible text, plain.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "click",
        "description": "Click an element by its role and accessible name as look shows them (e.g. role 'button', name 'Play'), or by visible text. nth picks among several matches.",
        "inputSchema": {"type": "object", "properties": {"role": S, "name": S, "text": S, "nth": N}},
    },
    {
        "name": "type",
        "description": "Fill a text box (by its accessible name) with text; submit presses Enter.",
        "inputSchema": {
            "type": "object",
            "properties": {"name": S, "text": S, "submit": {"type": "boolean"}, "role": S},
            "required": ["name", "text"],
        },
    },
    {
        "name": "choose",
        "description": "Pick an option in a drop-down list (a combobox, by its accessible name), by the option's text.",
        "inputSchema": {"type": "object", "properties": {"name": S, "option": S}, "required": ["name", "option"]},
    },
    {
        "name": "press",
        "description": "Press a key on the keyboard (e.g. Enter, Escape, ArrowUp, Space) where the focus is.",
        "inputSchema": {"type": "object", "properties": {"key": S}, "required": ["key"]},
    },
    {
        "name": "drag",
        "description": "Drag an element (a knob, fader or slider by role and name) by dx, dy pixels, like a mouse. Up is negative dy.",
        "inputSchema": {
            "type": "object",
            "properties": {"role": S, "name": S, "dx": N, "dy": N, "nth": N},
            "required": ["role", "name"],
        },
    },
    {
        "name": "click_at",
        "description": "Click at a point (x, y in CSS pixels of the 1180 x 800 window), for things look cannot name.",
        "inputSchema": {"type": "object", "properties": {"x": N, "y": N}, "required": ["x", "y"]},
    },
    {
        "name": "wait",
        "description": "Wait up to 20 seconds (for Live to answer, or for playback).",
        "inputSchema": {"type": "object", "properties": {"seconds": N}},
    },
    {
        "name": "screenshot",
        "description": f"See the page as an image. At most {SHOTS_PER_LEG} in this leg: use look first.",
        "inputSchema": {"type": "object", "properties": {"note": S}},
    },
    {
        "name": "console",
        "description": "The page's console errors and warnings since you last asked.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "journal",
        "description": "Write a journal entry, published live for the people watching. kind: plan, action, result, finding, blocker, praise, question or summary. Short title, a few plain sentences of body.",
        "inputSchema": {
            "type": "object",
            "properties": {"kind": S, "title": S, "body": S, "attach_last_screenshot": {"type": "boolean"}},
            "required": ["kind", "title"],
        },
    },
    {
        "name": "notes_read",
        "description": "Read your own notebook (what you did and what is next), kept across legs.",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "notes_write",
        "description": "Replace your notebook: the state of the song, decisions, what is next. Write it before each checkpoint.",
        "inputSchema": {"type": "object", "properties": {"text": S}, "required": ["text"]},
    },
    {
        "name": "checkpoint",
        "description": "Keep the song as last saved in the app, with your notebook, as a point a later leg can start from. Save the song in the app first.",
        "inputSchema": {"type": "object", "properties": {"label": S, "summary": S}, "required": ["label", "summary"]},
    },
    {
        "name": "finish",
        "description": "End this leg with a summary. Then stop.",
        "inputSchema": {"type": "object", "properties": {"summary": S}, "required": ["summary"]},
    },
]
PAGE_TOOLS = {"open_app", "click", "type", "choose", "press", "drag", "click_at"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--leg", required=True, type=int)
    a = ap.parse_args()
    h: Harness | None = None
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method = msg.get("id"), msg.get("method")
        if mid is None:
            continue  # a notification
        if method == "initialize":
            _out(
                {
                    "jsonrpc": "2.0",
                    "id": mid,
                    "result": {
                        "protocolVersion": msg.get("params", {}).get("protocolVersion", "2025-06-18"),
                        "capabilities": {"tools": {}},
                        "serverInfo": {"name": "wt", "version": "1"},
                    },
                }
            )
        elif method == "tools/list":
            _out({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            p = msg.get("params", {})
            name, args = p.get("name"), p.get("arguments") or {}
            try:
                if h is None:
                    h = Harness(a.run, a.leg)
                fn = getattr(h, f"t_{name}")
                got = fn(**args)
                if name in PAGE_TOOLS:
                    h.actions += 1
                    h.log("tool", name, json.dumps(args)[:300])
                content = got if isinstance(got, list) else [{"type": "text", "text": str(got)}]
                _out({"jsonrpc": "2.0", "id": mid, "result": {"content": content}})
            except Exception as exc:  # the agent sees what went wrong, as a person would see nothing happen
                if h is not None:
                    h.log("tool-error", str(name), f"{type(exc).__name__}: {exc}"[:400])
                detail = f"{type(exc).__name__}: {exc}"
                if not isinstance(exc, (ValueError, PWError)):
                    detail += "\n" + traceback.format_exc(limit=2)
                _out(
                    {
                        "jsonrpc": "2.0",
                        "id": mid,
                        "result": {"content": [{"type": "text", "text": detail[:1500]}], "isError": True},
                    }
                )
        elif method == "ping":
            _out({"jsonrpc": "2.0", "id": mid, "result": {}})
        else:
            _out({"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"no method {method}"}})


if __name__ == "__main__":
    main()
