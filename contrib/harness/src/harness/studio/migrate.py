"""Repairs to the chat's stored data: `harness studio-music-mp3 [--dry-run]`.

Music used to be stored as FLAC, which iPhone Safari's Web Audio cannot decode. Each music message whose audio is
FLAC gets a V0 MP3 of it (audio.to_mp3, as new music gets) as new content-addressed media; the message points at the
MP3 and keeps the FLAC's reference as `original`. The FLAC file itself stays. Running it again changes nothing, and
it is safe while the server runs (pages that have the old bubble pick up the MP3 when they next load the chat).
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass

from . import audio
from .model import Kind
from .store import MEDIA_URL, MIME, Store


@dataclass
class Converted:
    seq: int
    status: str                  # converted | would convert | missing | failed
    source: str                  # the FLAC's url
    mp3: str = ""                # the MP3's url, once converted
    error: str = ""


async def music_to_mp3(store: Store, dry_run: bool = False) -> list[Converted]:
    """Convert every FLAC music message to MP3; what was done to each, oldest first."""
    out: list[Converted] = []
    for msg in store.of_kind(Kind.MUSIC):
        ref = msg.data.get("audio") or {}
        if ref.get("type") != MIME["flac"]:
            continue
        url = str(ref.get("url", ""))
        path = store.media_file(url.removeprefix(MEDIA_URL))
        if path is None:
            out.append(Converted(msg.seq, "missing", url))
            continue
        if dry_run:
            out.append(Converted(msg.seq, "would convert", url))
            continue
        try:
            data, _ = await audio.to_mp3(path)
        except audio.AudioError as exc:
            out.append(Converted(msg.seq, "failed", url, error=str(exc)))
            continue
        mp3 = await asyncio.to_thread(store.put_media, data, "mp3")
        msg.data.update(audio=mp3.wire(), original=ref)
        store.update(msg)
        out.append(Converted(msg.seq, "converted", url, mp3.url))
    return out
