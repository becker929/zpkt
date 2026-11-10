"""Images made with Gemini, and the record of every one (docs/images.md).

This is the only way this project calls an image model. Each call keeps what came back, with what it was for:

    <images_dir>/images.jsonl   one record per image, append-only: id, when, batch, context, title, the full prompt,
                                the model, the settings sent, the reference images, seconds, tokens, the model's text,
                                width and height, its files
    <images_dir>/files/<id>.png the image as it came; <id>.jpg the gallery's copy (at most 900 px wide)
    <images_dir>/errors.jsonl   calls that made no image, and why

The gallery (/studio/images/, behind the harness password) shows them all. Images live on this Mac only, never in
git. The key is the Keychain's zpkt-gemini-api-key (or HARNESS_GEMINI).

    generate(store, prompt, context=..., batch=..., ...) -> [Record]
    harness images gen "<prompt>" --context ... --batch ... [--title --model --aspect --size --input <png> ...]
    harness images batch jobs.json --context ... --batch ... [--parallel 4]   (a list of {prompt, title?, aspect?, ...})
    harness images list [--batch ...]
"""

from __future__ import annotations

import base64
import io
import json
import mimetypes
import secrets
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

API = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEFAULT_MODEL = "gemini-3-pro-image"
ASPECTS = ("1:1", "2:3", "3:2", "3:4", "4:3", "4:5", "5:4", "9:16", "16:9", "21:9")
SIZES = ("1K", "2K", "4K")
THUMB_W = 900


@dataclass
class Record:
    id: str
    created: str
    batch: str
    context: str
    title: str
    prompt: str
    model: str
    settings: dict
    inputs: list[str] = field(default_factory=list)
    seconds: float = 0.0
    tokens: dict = field(default_factory=dict)
    text: str = ""
    width: int = 0
    height: int = 0
    file: str = ""
    thumb: str = ""
    imported: bool = False          # made before this wrapper existed, and recorded afterwards

    def public(self) -> dict:
        return asdict(self)


class Store:
    """The images and their records, in one folder."""

    def __init__(self, root: Path):
        self.root = Path(root)
        self.files = self.root / "files"
        self.files.mkdir(parents=True, exist_ok=True)
        self.manifest = self.root / "images.jsonl"
        self._lock = threading.Lock()

    def add(self, rec: Record, data: bytes) -> Record:
        """Keeps the image and its gallery copy, then appends its record."""
        im = Image.open(io.BytesIO(data))
        rec.width, rec.height = im.size
        ext = {"PNG": "png", "JPEG": "jpg", "WEBP": "webp"}.get(im.format or "", "png")
        rec.file = f"{rec.id}.{ext}"
        (self.files / rec.file).write_bytes(data)
        thumb = im.convert("RGB")
        if thumb.width > THUMB_W:
            thumb = thumb.resize((THUMB_W, round(thumb.height * THUMB_W / thumb.width)), Image.LANCZOS)
        rec.thumb = f"{rec.id}.t.jpg"
        thumb.save(self.files / rec.thumb, "JPEG", quality=84, optimize=True)
        with self._lock, self.manifest.open("a") as f:
            f.write(json.dumps(rec.public()) + "\n")
        return rec

    def error(self, entry: dict) -> None:
        with self._lock, (self.root / "errors.jsonl").open("a") as f:
            f.write(json.dumps(entry) + "\n")

    def all(self) -> list[Record]:
        if not self.manifest.is_file():
            return []
        out = []
        for line in self.manifest.read_text().splitlines():
            if line.strip():
                d = json.loads(line)
                out.append(Record(**{k: v for k, v in d.items() if k in Record.__dataclass_fields__}))
        return out

    def page(self, offset: int = 0, limit: int = 60, batch: str | None = None) -> tuple[list[Record], int, list[dict]]:
        """Newest first: a page of records, how many there are, and the batches (newest first, with counts)."""
        recs = self.all()
        batches: dict[str, dict] = {}
        for r in recs:
            b = batches.setdefault(r.batch, {"batch": r.batch, "count": 0, "last": r.created, "context": r.context})
            b["count"] += 1
            b["last"] = max(b["last"], r.created)
        chosen = [r for r in recs if batch is None or r.batch == batch]
        chosen.sort(key=lambda r: (r.created, r.id), reverse=True)
        order = sorted(batches.values(), key=lambda b: b["last"], reverse=True)
        return chosen[offset:offset + max(0, limit)], len(chosen), order

    def path(self, name: str) -> Path | None:
        p = (self.files / name).resolve()
        return p if p.is_relative_to(self.files.resolve()) and p.is_file() else None


def new_id(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y%m%d-%H%M%S-") + secrets.token_hex(3)


def _settings(aspect: str | None, size: str | None, text: bool) -> dict:
    cfg: dict = {"responseModalities": ["TEXT", "IMAGE"] if text else ["IMAGE"]}
    image: dict = {}
    if aspect:
        if aspect not in ASPECTS:
            raise ValueError(f"aspect must be one of {', '.join(ASPECTS)}")
        image["aspectRatio"] = aspect
    if size:
        if size not in SIZES:
            raise ValueError(f"size must be one of {', '.join(SIZES)}")
        image["imageSize"] = size
    if image:
        cfg["imageConfig"] = image
    return cfg


def generate(store: Store, prompt: str, *, key: str, context: str, batch: str, title: str = "",
             model: str = DEFAULT_MODEL, aspect: str | None = "1:1", size: str | None = None,
             inputs: list[Path] | None = None, text: bool = True, timeout: float = 300,
             post=None) -> list[Record]:
    """One call to an image model; every image it returns is kept with its record. `inputs` are reference images
    sent before the prompt. `post(url, body, headers, timeout) -> dict` is the HTTP call (tests replace it)."""
    if not context.strip() or not batch.strip():
        raise ValueError("every image needs its context (why it was made) and its batch")
    settings = _settings(aspect, size, text)
    parts: list[dict] = []
    for p in inputs or []:
        mime = mimetypes.guess_type(str(p))[0] or "image/png"
        parts.append({"inlineData": {"mimeType": mime, "data": base64.b64encode(Path(p).read_bytes()).decode()}})
    parts.append({"text": prompt})
    body = {"contents": [{"parts": parts}], "generationConfig": settings}
    t0 = time.monotonic()
    try:
        d = (post or _post)(API.format(model=model), body, {"X-goog-api-key": key}, timeout)
    except Exception as e:  # noqa: BLE001 - every failure is recorded, then raised
        store.error({"created": datetime.now(timezone.utc).isoformat(), "batch": batch, "context": context, "title": title,
                     "prompt": prompt, "model": model, "settings": settings, "error": str(e)[:2000]})
        raise
    seconds = round(time.monotonic() - t0, 1)
    out, said = [], []
    cand = (d.get("candidates") or [{}])[0]
    for part in (cand.get("content") or {}).get("parts", []):
        if "text" in part:
            said.append(part["text"])
    images = [part["inlineData"] for part in (cand.get("content") or {}).get("parts", []) if "inlineData" in part]
    if not images:
        store.error({"created": datetime.now(timezone.utc).isoformat(), "batch": batch, "context": context, "title": title,
                     "prompt": prompt, "model": model, "settings": settings, "error": "no image",
                     "finish": cand.get("finishReason"), "text": "\n".join(said)[:2000]})
    for k, im in enumerate(images):
        rec = Record(id=new_id(), created=datetime.now(timezone.utc).isoformat(), batch=batch, context=context,
                     title=title + (f" ({k + 1})" if len(images) > 1 else ""), prompt=prompt, model=model,
                     settings=settings, inputs=[str(p) for p in inputs or []], seconds=seconds,
                     tokens=d.get("usageMetadata", {}), text="\n".join(said))
        out.append(store.add(rec, base64.b64decode(im["data"])))
    return out


def _post(url: str, body: dict, headers: dict, timeout: float) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), method="POST",
                                 headers={"Content-Type": "application/json", **headers})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read()[:600].decode(errors='replace')}") from None


def run_batch(store: Store, jobs: list[dict], *, key: str, context: str, batch: str, model: str = DEFAULT_MODEL,
              parallel: int = 4, post=None) -> tuple[list[Record], list[str]]:
    """Many prompts at once (each job: prompt, and optionally title, aspect, size, model, context, inputs)."""
    def one(j: dict):
        try:
            return generate(store, j["prompt"], key=key, context=j.get("context", context), batch=batch,
                            title=j.get("title", ""), model=j.get("model", model), aspect=j.get("aspect", "1:1"),
                            size=j.get("size"), inputs=[Path(p) for p in j.get("inputs", [])], post=post), None
        except Exception as e:  # noqa: BLE001
            return [], f"{j.get('title') or j['prompt'][:40]}: {e}"
    recs, errors = [], []
    with ThreadPoolExecutor(max(1, parallel)) as ex:
        for got, err in ex.map(one, jobs):
            recs += got
            if err:
                errors.append(err)
    return recs, errors


def import_image(store: Store, png: Path, *, prompt: str, model: str, context: str, batch: str, title: str = "",
                 settings: dict | None = None, seconds: float = 0, tokens: dict | None = None,
                 created: str | None = None) -> Record:
    """Records an image made before this wrapper existed (marked imported)."""
    rec = Record(id=new_id(), created=created or datetime.now(timezone.utc).isoformat(), batch=batch, context=context,
                 title=title, prompt=prompt, model=model, settings=settings or {}, seconds=seconds, tokens=tokens or {},
                 imported=True)
    return store.add(rec, Path(png).read_bytes())
