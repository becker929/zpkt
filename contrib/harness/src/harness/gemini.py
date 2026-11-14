"""Gemini chat inside zpkt (/studio/gemini/, contrib/docs/gemini.md).

A chat with Gemini's text models that knows zpkt: read-only tools over the repo's tracked files and git log, images
through harness.images (so they land on the wall with their record), and chats kept on the Mac so every device sees
the same ones. The page can hand any reply to Claude as a harness job (/api/rpc `job`); Gemini itself cannot.

    <gemini_dir>/chats/<id>.json   one chat: title, settings, and `contents` as the API takes them (keys starting with
                                   "_" are ours and stripped before sending; attachments are files, inlined at send time)
    <gemini_dir>/files/<id>/<name> a chat's attachments
    <gemini_dir>/usage.jsonl       one line per model call: when, chat, model, tokens, estimated dollars
    <gemini_dir>/settings.json     the defaults a new chat starts with

The key is the Keychain's zpkt-gemini-api-key (config.secret("gemini")), the same one harness.images uses.
"""

from __future__ import annotations

import asyncio
import base64
import json
import re
import secrets
import subprocess
import threading
import time
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import images as I

BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-pro-latest"
MAX_ROUNDS = 8                 # model calls per turn (each tool round is one)
MAX_IMAGES_PER_TURN = 4
READ_LINES, READ_BYTES = 400, 60_000
SEARCH_HITS = 150
DENY = re.compile(r"(^|/)(\.env[^/]*|.*\.pem|.*\.key|auth\.json|secrets?\.[a-z]+)$", re.IGNORECASE)

# Dollars per million tokens (input, output incl. thinking), the standard tier, for the estimate only, by family:
# flash-lite, flash, 2.5 pro, and everything else at the 3.x pro rate (so an unknown model errs high).
PRICES = (("flash-lite", 0.1, 0.4), ("flash", 0.5, 3.0), ("2.5-pro", 1.25, 10.0))
IMAGE_OUT = 120.0              # dollars per million image-output tokens (1120 a 1K/2K image: about $0.134)


def price(model: str) -> tuple[float, float]:
    for part, i, o in PRICES:
        if part in model and "image" not in model:
            return i, o
    return 2.0, 12.0


def cost(model: str, usage: dict) -> float:
    """An estimate of one call's dollars from its usageMetadata."""
    i, o = price(model)
    image = sum(d.get("tokenCount", 0) for d in usage.get("candidatesTokensDetails") or [] if d.get("modality") == "IMAGE")
    text_out = usage.get("candidatesTokenCount", 0) - image + usage.get("thoughtsTokenCount", 0)
    return (usage.get("promptTokenCount", 0) * i + text_out * o + image * IMAGE_OUT) / 1e6


def image_cost(rec: dict) -> float:
    t = rec.get("tokens") or {}
    if "candidatesTokensDetails" in t:
        return cost(rec.get("model", ""), t)
    return 0.134 if "pro" in rec.get("model", "") else 0.07          # imported records only kept a total


def now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


# --- the chats -----------------------------------------------------------------------------------------------------

class Chats:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.dir = self.root / "chats"
        self.files = self.root / "files"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.files.mkdir(parents=True, exist_ok=True)
        self.usage_path = self.root / "usage.jsonl"
        self._lock = threading.Lock()

    @staticmethod
    def valid_id(cid: str) -> bool:
        return bool(re.fullmatch(r"[0-9a-z-]{6,40}", cid or ""))

    def _path(self, cid: str) -> Path:
        if not self.valid_id(cid):
            raise KeyError(cid)
        return self.dir / f"{cid}.json"

    def settings(self) -> dict:
        p = self.root / "settings.json"
        base = {"model": DEFAULT_MODEL, "system": "", "temperature": 1.0, "zpkt": True}
        if p.is_file():
            base.update(json.loads(p.read_text()))
        return base

    def set_settings(self, s: dict) -> dict:
        merged = {**self.settings(), **clean_settings(s)}
        (self.root / "settings.json").write_text(json.dumps(merged))
        return merged

    def new(self, settings: dict | None = None) -> dict:
        cid = datetime.now(UTC).strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)
        return {"id": cid, "title": "New chat", "created": now(), "updated": now(),
                "settings": {**self.settings(), **clean_settings(settings or {})}, "contents": []}

    def get(self, cid: str) -> dict:
        p = self._path(cid)
        if not p.is_file():
            raise KeyError(cid)
        return json.loads(p.read_text())

    def save(self, chat: dict) -> None:
        chat["updated"] = now()
        p = self._path(chat["id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(chat))
        tmp.replace(p)

    def delete(self, cid: str) -> None:
        self._path(cid).unlink(missing_ok=True)
        d = self.files / cid
        if d.is_dir():
            for f in d.iterdir():
                f.unlink()
            d.rmdir()

    def list(self) -> list[dict]:
        spent = self.spent_by_chat()
        out = []
        for p in self.dir.glob("*.json"):
            try:
                c = json.loads(p.read_text())
            except ValueError:
                continue
            out.append({"id": c["id"], "title": c.get("title", ""), "updated": c.get("updated", ""),
                        "dollars": round(spent.get(c["id"], 0.0), 4)})
        return sorted(out, key=lambda c: c["updated"], reverse=True)

    def attach(self, cid: str, mime: str, data_b64: str) -> str:
        ext = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp", "image/gif": "gif"}.get(mime)
        if not ext:
            raise ValueError("Attachments are images (JPEG, PNG, WebP or GIF).")
        raw = base64.b64decode(data_b64, validate=True)
        d = self.files / cid
        d.mkdir(parents=True, exist_ok=True)
        name = f"{secrets.token_hex(6)}.{ext}"
        (d / name).write_bytes(raw)
        return name

    def file(self, cid: str, name: str) -> Path | None:
        if not self.valid_id(cid) or not re.fullmatch(r"[0-9a-f]{12}\.[a-z]{3,4}", name):
            return None
        p = self.files / cid / name
        return p if p.is_file() else None

    def log_usage(self, cid: str, model: str, usage: dict) -> dict:
        row = {"at": now(), "chat": cid, "model": model, "prompt": usage.get("promptTokenCount", 0),
               "output": usage.get("candidatesTokenCount", 0), "thoughts": usage.get("thoughtsTokenCount", 0),
               "dollars": round(cost(model, usage), 6)}
        with self._lock, self.usage_path.open("a") as f:
            f.write(json.dumps(row) + "\n")
        return row

    def usage_rows(self) -> list[dict]:
        if not self.usage_path.is_file():
            return []
        rows = []
        for line in self.usage_path.read_text().splitlines():
            try:
                rows.append(json.loads(line))
            except ValueError:
                pass
        return rows

    def spent_by_chat(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for r in self.usage_rows():
            out[r["chat"]] = out.get(r["chat"], 0.0) + r.get("dollars", 0.0)
        return out


def clean_settings(s: dict) -> dict:
    out: dict = {}
    if isinstance(s.get("model"), str) and re.fullmatch(r"[\w.\-]{3,80}", s["model"]):
        out["model"] = s["model"]
    if isinstance(s.get("system"), str):
        out["system"] = s["system"][:8000]
    if isinstance(s.get("temperature"), (int, float)) and 0 <= s["temperature"] <= 2:
        out["temperature"] = float(s["temperature"])
    if isinstance(s.get("zpkt"), bool):
        out["zpkt"] = s["zpkt"]
    return out


def month_usage(chats: Chats, images_manifest: Path, month: str | None = None) -> dict:
    """This month's estimated dollars: the chat's calls, and every image made through harness.images."""
    month = month or datetime.now(UTC).strftime("%Y-%m")
    chat = sum(r.get("dollars", 0.0) for r in chats.usage_rows() if r.get("at", "").startswith(month))
    img, n = 0.0, 0
    if images_manifest.is_file():
        for line in images_manifest.read_text().splitlines():
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("created", "").startswith(month):
                img += image_cost(r)
                n += 1
    return {"month": month, "chat": round(chat, 4), "images": round(img, 4), "image_count": n}


# --- the repo, read-only --------------------------------------------------------------------------------------------

class Repo:
    """zpkt's tracked files only (git ls-files): untracked and ignored files, secrets among them, are invisible."""

    def __init__(self, root: Path):
        self.root = Path(root).resolve()
        self._files: tuple[float, list[str]] = (0.0, [])

    def git(self, *args: str) -> str:
        out = subprocess.run(["git", "-C", str(self.root), *args], check=False, capture_output=True, text=True, timeout=15)
        if out.returncode:
            raise RuntimeError(out.stderr.strip()[:300] or "git failed")
        return out.stdout

    def files(self) -> list[str]:
        if time.monotonic() - self._files[0] > 30:
            names = [n for n in self.git("ls-files", "-z").split("\0") if n and not DENY.search(n)]
            self._files = (time.monotonic(), names)
        return self._files[1]

    def branch(self) -> str:
        try:
            return self.git("rev-parse", "--abbrev-ref", "HEAD").strip()
        except (RuntimeError, OSError, subprocess.TimeoutExpired):
            return "?"

    @staticmethod
    def _norm(path: str) -> str:
        p = (path or "").strip().strip("/")
        if p in (".", ""):
            return ""
        if ".." in p.split("/"):
            raise ValueError("paths stay inside the repo")
        return p

    def list(self, path: str = "") -> dict:
        base = self._norm(path)
        prefix = base + "/" if base else ""
        entries: dict[str, str] = {}
        for f in self.files():
            if f.startswith(prefix):
                rest = f[len(prefix):]
                head, _, tail = rest.partition("/")
                entries[head + ("/" if tail else "")] = ""
        if not entries:
            raise ValueError(f"no tracked files under {path!r}")
        names = sorted(entries, key=lambda n: (not n.endswith("/"), n))
        return {"path": base or ".", "entries": names[:500], "more": max(0, len(names) - 500)}

    def read(self, path: str, offset: int = 1, limit: int = READ_LINES) -> dict:
        rel = self._norm(path)
        if rel not in set(self.files()):
            raise ValueError(f"{path!r} is not a tracked file (zpkt_list shows what is)")
        raw = (self.root / rel).read_bytes()
        if b"\0" in raw[:4096]:
            raise ValueError(f"{path} is binary")
        lines = raw.decode("utf-8", errors="replace").splitlines()
        offset, limit = max(1, int(offset)), max(1, min(READ_LINES, int(limit)))
        chunk, size = [], 0
        for n in range(offset, min(len(lines), offset + limit - 1) + 1):
            line = f"{n}\t{lines[n - 1]}"
            size += len(line) + 1
            if size > READ_BYTES:
                break
            chunk.append(line)
        last = offset + len(chunk) - 1
        return {"path": rel, "lines": f"{offset}-{last} of {len(lines)}", "text": "\n".join(chunk)}

    def search(self, pattern: str, path: str = "", glob: str = "") -> dict:
        try:
            rx = re.compile(pattern, re.IGNORECASE)
        except re.error as e:
            raise ValueError(f"bad pattern: {e}") from None
        base = self._norm(path)
        gl = re.compile(_glob_rx(glob)) if glob else None
        hits, files_hit = [], 0
        for f in self.files():
            if base and not (f == base or f.startswith(base + "/")):
                continue
            if gl and not gl.search(f):
                continue
            p = self.root / f
            try:
                if p.stat().st_size > 2_000_000:
                    continue
                text = p.read_text(errors="strict")
            except (OSError, UnicodeDecodeError):
                continue
            got = False
            for n, line in enumerate(text.splitlines(), 1):
                if rx.search(line):
                    hits.append(f"{f}:{n}: {line.strip()[:240]}")
                    got = True
                    if len(hits) >= SEARCH_HITS:
                        return {"hits": hits, "truncated": True}
            files_hit += got
        return {"hits": hits, "files": files_hit, "truncated": False}

    def log(self, n: int = 15, path: str = "") -> dict:
        args = ["log", f"-{max(1, min(50, int(n)))}", "--date=short", "--format=%h %ad %s"]
        if path:
            args += ["--", self._norm(path)]
        return {"branch": self.branch(), "commits": self.git(*args).splitlines()}


def _glob_rx(glob: str) -> str:
    out = ""
    for ch in glob:
        out += {"*": "[^/]*", "?": "[^/]", ".": r"\."}.get(ch, re.escape(ch))
    return out.replace("[^/]*[^/]*", ".*") + "$"


# --- the tools Gemini may call --------------------------------------------------------------------------------------

def _fn(name: str, desc: str, props: dict, required: list[str]) -> dict:
    return {"name": name, "description": desc,
            "parameters": {"type": "object", "properties": props, "required": required}}


S, N = {"type": "string"}, {"type": "integer"}
TOOLS = [{"functionDeclarations": [
    _fn("zpkt_list", "List a folder of the zpkt repo (tracked files only). Folders end with /.",
        {"path": {**S, "description": "Folder relative to the repo root; empty for the root."}}, []),
    _fn("zpkt_read", "Read a tracked text file of the zpkt repo, with line numbers, up to 400 lines at a time.",
        {"path": S, "offset": {**N, "description": "First line, from 1."}, "limit": N}, ["path"]),
    _fn("zpkt_search", "Search the repo's tracked text files with a case-insensitive regular expression. "
        "Returns file:line: text, at most 150 hits.",
        {"pattern": S, "path": {**S, "description": "Limit to this folder or file."},
         "glob": {**S, "description": "Limit to file names like *.py or docs/*.md."}}, ["pattern"]),
    _fn("zpkt_log", "The recent git commits of the checkout (optionally of one path).", {"n": N, "path": S}, []),
    _fn("list_images", "The newest images made for zpkt (all go through harness images and are on the wall).",
        {"batch": S, "limit": N}, []),
    _fn("make_image", "Make an image with Gemini's image model through harness images; it is kept with its record "
        "and shown on the wall at /studio/images/. Costs about $0.13 (1K/2K) or $0.24 (4K): only when asked.",
        {"prompt": {**S, "description": "The full prompt."}, "title": {**S, "description": "A word or two."},
         "aspect": {"type": "string", "enum": list(I.ASPECTS)}, "size": {"type": "string", "enum": list(I.SIZES)}},
        ["prompt"]),
]}]


def preamble(repo: Repo, chat: dict) -> str:
    return (
        "You are Gemini, talking with Anthony in the Gemini chat of his studio app (zpkt's harness, on his tailnet).\n"
        "zpkt is his music production setup, driven by code: hands/ drives Ableton Live, ears/ measures renders, "
        "agent/ holds the skills for driving Live, lib/ the rig, contrib/ his own apps (harness: this studio app; "
        "booth, bot, arranger, skrng) and contrib/docs/ his workflow, design notes and dated journal.\n"
        f"You have read-only tools over the checkout at {repo.root} (branch {repo.branch()}): use them instead of "
        "guessing, and name the paths you read. You cannot change files, run code or drive Live. When something needs "
        "doing, say what and suggest he sends your reply to Claude (a button under each reply starts a Claude Code "
        "job in zpkt).\n"
        "make_image goes through harness images: every image is kept on the wall with its prompt. Make images only "
        "when he asks for them.\n"
        "Write plainly: short sentences, no filler.\n"
        f"This chat: {chat['title']!r}, id {chat['id']}."
    )


class Toolbox:
    def __init__(self, repo: Repo, images: I.Store, key: str, chat: dict, image_post=None):
        self.repo, self.images, self.key, self.chat, self.image_post = repo, images, key, chat, image_post
        self.made = 0

    async def run(self, name: str, args: dict) -> tuple[dict, dict | None]:
        """The result for the model, and an event for the page (or None)."""
        try:
            if name == "zpkt_list":
                return self.repo.list(args.get("path", "")), None
            if name == "zpkt_read":
                return self.repo.read(args["path"], args.get("offset", 1), args.get("limit", READ_LINES)), None
            if name == "zpkt_search":
                return await asyncio.to_thread(self.repo.search, args["pattern"], args.get("path", ""),
                                               args.get("glob", "")), None
            if name == "zpkt_log":
                return self.repo.log(args.get("n", 15), args.get("path", "")), None
            if name == "list_images":
                recs, total, _ = self.images.page(0, max(1, min(30, int(args.get("limit", 10)))),
                                                  args.get("batch") or None)
                return {"total": total, "images": [{"id": r.id, "batch": r.batch, "title": r.title,
                                                    "prompt": r.prompt[:400], "created": r.created} for r in recs]}, None
            if name == "make_image":
                return await self._image(args)
            return {"error": f"no tool {name}"}, None
        except (ValueError, KeyError, RuntimeError, OSError, subprocess.TimeoutExpired) as e:
            return {"error": str(e)[:500]}, None

    async def _image(self, args: dict) -> tuple[dict, dict | None]:
        if self.made >= MAX_IMAGES_PER_TURN:
            return {"error": f"at most {MAX_IMAGES_PER_TURN} images a turn"}, None
        self.made += 1
        last_user = next((p.get("text", "") for c in reversed(self.chat["contents"]) if c["role"] == "user"
                          for p in c["parts"] if p.get("text")), "")
        context = f"Asked for in the Gemini chat {self.chat['title']!r}: {last_user[:300]}"
        recs = await asyncio.to_thread(
            I.generate, self.images, args["prompt"], key=self.key, context=context, batch=f"gemini-{self.chat['id']}",
            title=args.get("title", "")[:60], aspect=args.get("aspect") or "1:1", size=args.get("size"),
            post=self.image_post)
        if not recs:
            return {"error": "the image model returned no image (recorded in errors.jsonl)"}, None
        shown = [{"id": r.id, "thumb": r.thumb, "file": r.file, "width": r.width, "height": r.height} for r in recs]
        return ({"made": [{"id": r.id, "width": r.width, "height": r.height} for r in recs],
                 "wall": f"/studio/images/?batch=gemini-{self.chat['id']}"},
                {"type": "images", "images": shown})


# --- one turn -------------------------------------------------------------------------------------------------------

Stream = Callable[[str, dict, dict], AsyncIterator[dict]]


def api_contents(chat: dict, chats: Chats) -> list[dict]:
    """The stored contents as the API takes them: our keys dropped, attachment files inlined."""
    out = []
    for c in chat["contents"]:
        parts = []
        for p in c["parts"]:
            if "file" in p:
                f = chats.file(chat["id"], p["file"])
                if f:
                    parts.append({"inlineData": {"mimeType": p["mime"], "data": base64.b64encode(f.read_bytes()).decode()}})
            else:
                parts.append({k: v for k, v in p.items() if not k.startswith("_")})
        if parts:
            out.append({"role": c["role"], "parts": parts})
    return out


async def turn(chat: dict, chats: Chats, *, key: str, repo: Repo, images: I.Store, stream: Stream,
               emit: Callable[[dict], Awaitable[None]], image_post=None) -> None:
    """Runs the model (and its tools) until it answers, appending to chat["contents"] and saving as it goes."""
    s = chat["settings"]
    tools = Toolbox(repo, images, key, chat, image_post)
    system = (preamble(repo, chat) + ("\n\n" + s["system"] if s.get("system") else "")) if s.get("zpkt") else s.get("system", "")
    for _ in range(MAX_ROUNDS):
        body: dict[str, Any] = {"contents": api_contents(chat, chats),
                                "generationConfig": {"temperature": s.get("temperature", 1.0)}}
        if system.strip():
            body["systemInstruction"] = {"parts": [{"text": system}]}
        if s.get("zpkt"):
            body["tools"] = TOOLS
        parts: list[dict] = []
        usage: dict = {}
        finish = None
        async for ev in stream(f"{BASE}/models/{s['model']}:streamGenerateContent?alt=sse", body, {"x-goog-api-key": key}):
            if ev.get("error"):
                raise RuntimeError(ev["error"].get("message", "stream error"))
            if (ev.get("promptFeedback") or {}).get("blockReason"):
                raise RuntimeError("Blocked: " + ev["promptFeedback"]["blockReason"])
            cand = (ev.get("candidates") or [{}])[0]
            for p in (cand.get("content") or {}).get("parts", []):
                parts.append(p)
                if p.get("text") and not p.get("thought"):
                    await emit({"type": "text", "text": p["text"]})
            finish = cand.get("finishReason") or finish
            usage = ev.get("usageMetadata") or usage
        row = chats.log_usage(chat["id"], s["model"], usage) if usage else None
        calls = [p["functionCall"] for p in parts if "functionCall" in p]
        if parts:
            chat["contents"].append({"role": "model", "parts": parts, "_meta": {"model": s["model"], "usage": row}})
        chats.save(chat)
        if row:
            await emit({"type": "usage", **row})
        if not calls:
            if not any(p.get("text") for p in parts):
                raise RuntimeError(f"No answer (finish: {finish or 'unknown'}).")
            return
        responses = []
        for call in calls:
            name, args = call.get("name", ""), call.get("args") or {}
            await emit({"type": "tool", "name": name, "args": args})
            result, extra = await tools.run(name, args)
            if extra:
                await emit(extra)
            part: dict = {"functionResponse": {"name": name, "response": result}}
            if call.get("id"):
                part["functionResponse"]["id"] = call["id"]
            if extra and extra.get("type") == "images":
                part["_images"] = extra["images"]
            responses.append(part)
        chat["contents"].append({"role": "user", "parts": responses})
        chats.save(chat)
    raise RuntimeError(f"Stopped after {MAX_ROUNDS} rounds of tools.")


def title_from(text: str) -> str:
    t = " ".join(text.split())
    return (t[:48] + "…") if len(t) > 48 else (t or "Image")


def truncate_to_last_user(chat: dict) -> str | None:
    """For a retry: drop everything after the last message he typed. Returns its text, or None if there is none."""
    for i in range(len(chat["contents"]) - 1, -1, -1):
        c = chat["contents"][i]
        if c["role"] == "user" and not any("functionResponse" in p for p in c["parts"]):
            del chat["contents"][i + 1:]
            return next((p["text"] for p in c["parts"] if "text" in p), "")
    return None
