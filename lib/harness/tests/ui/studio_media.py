"""Generated media for the page's tests: tones, an A/B render, replays and screenshot pairs. Nothing is stored
in git; every file is made at test time."""

from __future__ import annotations

import io
import wave
from functools import lru_cache
from pathlib import Path

import numpy as np
import soundfile as sf
from PIL import Image, ImageDraw

SPEECH_RATE = 24_000          # Kokoro's rate, and the fake speaker's


def tone(freq: float, seconds: float, rate: int, amp: float = 0.3) -> np.ndarray:
    t = np.arange(int(round(seconds * rate))) / rate
    return amp * np.sin(2 * np.pi * freq * t)


def pcm16(samples: np.ndarray) -> bytes:
    """s16le, as the protocol's audio frames carry it."""
    return (np.clip(samples, -1, 1) * 32767).astype("<i2").tobytes()


def speech_pcm(seconds: float, freq: float = 220.0) -> bytes:
    return pcm16(tone(freq, seconds, SPEECH_RATE))


@lru_cache
def ab_flac(bar_seconds: float, bars: int, rate: int = 48_000) -> bytes:
    """A render that alternates two versions bar by bar: A is a low tone, B a higher one."""
    parts = [tone(330.0 if i % 2 == 0 else 495.0, bar_seconds, rate, 0.25) for i in range(bars)]
    stereo = np.stack([np.concatenate(parts)] * 2, axis=1)
    buf = io.BytesIO()
    sf.write(buf, stereo, rate, format="FLAC", subtype="PCM_16")
    return buf.getvalue()


@lru_cache
def mp3(seconds: float, freq: float = 220.0, rate: int = SPEECH_RATE) -> bytes:
    buf = io.BytesIO()
    sf.write(buf, tone(freq, seconds, rate), rate, format="MP3")
    return buf.getvalue()


@lru_cache
def mic_wav_bytes(seconds: float = 6.0, freq: float = 1000.0, rate: int = 48_000) -> bytes:
    """What the page's mic hears in the tests: a tone in short bursts, like syllables (a steady tone would be
    treated as noise and suppressed)."""
    t = np.arange(int(seconds * rate)) / rate
    bursts = (np.sin(2 * np.pi * 3.0 * t) > -0.2).astype(float)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(pcm16(0.5 * np.sin(2 * np.pi * freq * t) * bursts))
    return buf.getvalue()


def mic_wav(path: Path) -> Path:
    """The same, as a file for Chromium's fake capture device (--use-file-for-fake-audio-capture)."""
    path.write_bytes(mic_wav_bytes())
    return path


SCREEN = (1920, 1080)


@lru_cache
def shot_pair(seed: int = 0, level: str = "major", zoom_w: int = 640) -> dict:
    """A made-up Mac screen (a dark app with tracks and a device chain) and a native-pixel 4:3 zoom on one
    region, shaped like the Mac's pairs: the full image is the screen at 1920x1080 (1280x720 for firehose),
    `rect` is [x, y, w, h] in screen pixels. Returns {full, zoom, rect, full_size, zoom_size, screen}."""
    W, H = SCREEN
    im = Image.new("RGB", (W, H), (28, 30, 36))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, W, 30), fill=(44, 46, 54))                       # menu bar
    d.rectangle((40, 60, W - 40, H - 40), fill=(36, 38, 46), outline=(70, 72, 82))
    d.rectangle((40, 60, W - 40, 100), fill=(52, 54, 64))                # title bar
    for i in range(12):                                                  # tracks
        y = 124 + i * 44
        d.rectangle((60, y, 300, y + 34), fill=(60 + 10 * (i % 3), 64, 80))
        d.rectangle((320, y + 5, 320 + 160 + ((i * 97 + seed * 131) % 900), y + 29),
                    fill=((200 + i * 11) % 255, 120 + (i * 37) % 120, (90 + seed * 40) % 200))
    d.rectangle((60, H - 330, W - 60, H - 60), fill=(30, 32, 40), outline=(80, 82, 94))   # the device chain
    for i in range(7):
        x = 80 + i * 250
        d.rectangle((x, H - 310, x + 230, H - 80), fill=(46, 48, 58), outline=(96, 98, 110))
        d.ellipse((x + 75, H - 260, x + 155, H - 180), outline=(240, 180, 90), width=7)
        d.rectangle((x + 20, H - 130, x + 210, H - 106), fill=(90, 160, 240) if (i + seed) % 2 else (240, 120, 90))
        d.text((x + 20, H - 300), f"Device {i + 1}", fill=(210, 212, 220))
    rect = [80 + (seed % 5) * 250, H - 330, zoom_w, zoom_w * 3 // 4]
    x, y, w, h = rect
    y = min(y, H - h)
    rect[1] = y
    zoom = im.crop((x, y, x + w, y + h))
    full = im if level != "firehose" else im.resize((1280, 720), Image.Resampling.LANCZOS)

    def webp(img: Image.Image) -> bytes:
        out = io.BytesIO()
        img.save(out, "WEBP", quality=82)
        return out.getvalue()

    return {"full": webp(full), "zoom": webp(zoom), "rect": rect, "full_size": full.size, "zoom_size": zoom.size,
            "screen": [W, H]}
