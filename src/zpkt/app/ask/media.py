"""Files the page may play or show (audio an agent rendered, images), and the images a person attaches."""

from __future__ import annotations

import base64
import binascii
import re
import time
from dataclasses import dataclass
from pathlib import Path

from zpkt.app.ask.store import Refused

MEDIA = {
    ".wav": "audio/wav", ".wave": "audio/wav", ".mp3": "audio/mpeg", ".flac": "audio/flac", ".ogg": "audio/ogg",
    ".oga": "audio/ogg", ".opus": "audio/ogg", ".m4a": "audio/mp4", ".aac": "audio/aac", ".aif": "audio/aiff",
    ".aiff": "audio/aiff", ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
    ".gif": "image/gif",
}  # fmt: skip
MAX_IMAGE = 10 * 1024 * 1024
DATA_URL = re.compile(r"^data:(image/(png|jpeg|webp|gif));base64,([A-Za-z0-9+/=]+)$")


@dataclass(frozen=True)
class MediaFile:
    path: Path
    type: str
    size: int


def resolve_media(p: object, cwd: Path, home: Path) -> MediaFile:
    """A path an agent wrote (relative to the session folder, or absolute or ~ inside home) as a media file."""
    if not isinstance(p, str) or not p.strip() or len(p) > 2000:
        raise Refused("Path required")
    text = p.strip()
    abs_path = Path(str(home) + text[1:]) if text == "~" or text.startswith("~/") else Path(text)
    if not abs_path.is_absolute():
        abs_path = cwd / abs_path
    try:
        real = abs_path.resolve(strict=True)
    except OSError:
        raise Refused("No such file", 404) from None
    home = home.resolve()
    if home not in real.parents:
        raise Refused("Only files inside the home folder", 403)
    if any(part.startswith(".") and part != ".zpkt" for part in real.parts):
        raise Refused("Hidden folders are not served", 403)
    kind = MEDIA.get(real.suffix.lower())
    if kind is None:
        raise Refused("Only audio and image files are served", 415)
    if not real.is_file():
        raise Refused("Not a file", 404)
    return MediaFile(real, kind, real.stat().st_size)


def byte_range(header: str, size: int) -> tuple[int, int] | None:
    """(start, end) of a `Range: bytes=a-b` header; None for no range. Refused when the range is empty."""
    m = re.fullmatch(r"bytes=(\d*)-(\d*)", header or "")
    if not m or not (m.group(1) or m.group(2)):
        return None
    if m.group(1):
        start, end = int(m.group(1)), int(m.group(2)) if m.group(2) else size - 1
    else:
        start, end = size - int(m.group(2)), size - 1
    start, end = max(0, start), min(size - 1, end)
    if start > end:
        raise Refused("That part of the file does not exist", 416)
    return start, end


def save_attachment(folder: Path, data_url: object, name: object = "") -> tuple[str, int]:
    """Save a PNG, JPEG, WebP or GIF data URL; returns (file name, size)."""
    m = DATA_URL.match(str(data_url or ""))
    if not m:
        raise Refused("Expected a PNG, JPEG, WebP or GIF data URL")
    try:
        raw = base64.b64decode(m.group(3), validate=True)
    except binascii.Error:
        raise Refused("The image is not valid base64") from None
    if len(raw) > MAX_IMAGE:
        raise Refused("Image too large", 413)
    ext = "jpg" if m.group(2) == "jpeg" else m.group(2)
    base = re.sub(r"[^\w\-]+", "-", re.sub(r"\.[a-z0-9]+$", "", str(name or "image"), flags=re.I))[:40] or "image"
    file = f"{time.strftime('%Y-%m-%dT%H-%M-%S')}-{base}.{ext}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / file).write_bytes(raw)
    return file, len(raw)
