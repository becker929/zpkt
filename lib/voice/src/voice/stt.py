"""Speech to text for one turn, with the stop word: Parakeet TDT 0.6B v3 (NVIDIA) on MLX, gated by Silero VAD.

Chosen and tuned by benchmark (docs/voice-benchmark.md): 240 files, 6 noise conditions, 11 engine configurations.

A turn ends ONLY when the transcript's last word is the stop word ("tomato"); pauses alone never end it.

  * Silero gives a speech probability per 32 ms frame; a causal level gate (frames more than GATE_DB under the
    talker's running level count as silence, so a radio or a passenger does not hold the turn open) feeds a
    hysteresis (on 0.5, off 0.35).
  * close: after speech, CLOSE_MS of silence -> transcribe the whole turn so far -> if it ends with the stop word,
    that is the final (its text minus the stop word; no second pass).
  * partial: while speech is open, every PARTIAL_MS of audio -> transcribe -> a caption.
  * stable tail (noise keeps the VAD open): two transcripts >= STABLE_GAP_S apart that both end with the stop word
    and are otherwise the same -> final.
  * recheck: if the close-time check missed, look once more after RECHECK_MS of silence, over the whole turn.
  * The model's input is gated too: audio that is not the main talker is attenuated 40 dB, and 0.3 s of digital
    silence is appended (right context for the last word at no waiting cost).
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np

from .tts import models_dir

log = logging.getLogger("voice.stt")

SR = 16_000
FRAME = 512                      # one Silero frame: 32 ms
FD = FRAME / SR

DEFAULT_MODEL = "mlx-community/parakeet-tdt-0.6b-v3"
SILERO_URL = "https://github.com/snakers4/silero-vad/raw/v6.0/src/silero_vad/data/silero_vad.onnx"

# Tuned on the benchmark (docs/voice-benchmark.md, "Tuned parameters").
CLOSE_MS = 150                   # silence after speech before the stop-word check
PARTIAL_MS = 600                 # caption cadence while speech is open
STABLE_GAP_S = 0.5
RECHECK_MS = 1000
GATE_DB = 12.0
TAIL_PAD_S = 0.3
VAD_ON, VAD_OFF = 0.5, 0.35
WINDOW_S = 45.0                  # captions and stop checks look at the last WINDOW_S of long turns


# --- the stop word ---------------------------------------------------------------------------------------------------

_NEVER = {"potato", "potatoes", "tomatillo", "tomatillos", "tornado", "tomorrow", "automatic"}


def _lev(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, x in enumerate(a, 1):
        cur = [i] + [0] * len(b)
        for j, y in enumerate(b, 1):
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (x != y))
        prev = cur
    return prev[-1]


def _skeleton(w: str) -> str:
    """Consonants only, d as t, th as t, h dropped, runs collapsed: 'tomedo' -> 'tmt'."""
    w = w.replace("th", "t").replace("h", "")
    out: list[str] = []
    for c in w:
        if c in "aeiouy":
            continue
        c = "t" if c == "d" else c
        if not out or out[-1] != c:
            out.append(c)
    return "".join(out)


def is_stop(w: str, stop_word: str = "tomato") -> bool:
    """One token, or 2-3 trailing tokens joined ('to mato' -> 'tomato')."""
    stop_word = stop_word.lower()
    if w in _NEVER or len(w) > len(stop_word) + 3:
        return False
    forms = {stop_word, stop_word + "s", stop_word + "es", stop_word + "e"}
    if w in forms or (len(w) >= 5 and _lev(w, stop_word) <= 1):
        return True
    if stop_word != "tomato":
        return False
    # Phonetic: a t-m-t(s) skeleton starting 'to'/'ta' with a, e or o after the m ('to motto', 'tomedo'); rejects
    # 'to make' (tmk), 'to mute' (u), 'to my toe' (y), 'potato', 'tomorrow', 'tomatillo'.
    if _skeleton(w) in ("tmt", "tmts") and w[:2] in ("to", "ta") and _lev(w, stop_word) <= 2:
        i = w.find("m")
        return w[i + 1:i + 2] in ("a", "e", "o")
    return False


def _norm_tokens(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9 ]+", " ", re.sub(r"[’']", "", text.lower())).split()


def split_stop(text: str, stop_word: str = "tomato") -> tuple[bool, str]:
    """(the transcript ends with the stop word, the transcript without it and its trailing punctuation)."""
    words = _norm_tokens(text)
    k = 0
    if words and is_stop(words[-1], stop_word):
        k = 1
    elif len(words) >= 2 and is_stop(words[-2] + words[-1], stop_word):
        k = 2
    elif len(words) >= 3 and is_stop("".join(words[-3:]), stop_word):
        k = 3
    if not k:
        return False, text.strip()
    toks = text.split()
    while toks and len(_norm_tokens(" ".join(toks))) > len(words) - k:
        toks.pop()
    return True, " ".join(toks).rstrip(" ,;:-.")


def resample(x: np.ndarray, rate: int) -> np.ndarray:
    if rate == SR or not len(x):
        return x
    n = int(round(len(x) * SR / rate))
    return np.interp(np.linspace(0, len(x) - 1, n), np.arange(len(x)), x).astype(np.float32)


# --- the models ------------------------------------------------------------------------------------------------------

def fetch_silero(into: Path) -> Path:
    path = into / "silero_vad_v6.onnx"
    if not path.is_file():
        into.mkdir(parents=True, exist_ok=True)
        log.info("downloading Silero VAD")
        part = path.with_suffix(".part")
        urllib.request.urlretrieve(SILERO_URL, part)
        part.rename(path)
    return path


class _Silero:
    def __init__(self, session: Any):
        self.sess, self.sr = session, np.array(SR, dtype=np.int64)
        self.reset()

    def reset(self) -> None:
        self.state = np.zeros((2, 1, 128), np.float32)
        self.ctx = np.zeros((1, 64), np.float32)

    def __call__(self, frame: np.ndarray) -> float:
        x = np.concatenate([self.ctx, frame.reshape(1, -1)], axis=1)
        out, self.state = self.sess.run(None, {"input": x, "state": self.state, "sr": self.sr})
        self.ctx = x[:, -64:]
        return float(out[0, 0])


class Parakeet:
    name = "parakeet"

    def __init__(self, model: str | None = None, cache_limit_mb: int = 512):
        import mlx.core as mx                            # heavy: only when the engine is chosen
        import onnxruntime as ort
        from parakeet_mlx import from_pretrained
        from parakeet_mlx.audio import get_logmel

        self.mx, self._get_logmel = mx, get_logmel
        mx.set_cache_limit(cache_limit_mb * 2**20)       # without it MLX's buffer cache grows to ~5 GB
        self.model_id = model or os.environ.get("VOICE_STT_MODEL", DEFAULT_MODEL)
        self.model = from_pretrained(self.model_id, dtype=mx.float32)   # fp32 is faster than bf16 here (28 vs 59 ms)
        self.name = f"parakeet ({self.model_id.rsplit('/', 1)[-1]})"
        options = ort.SessionOptions()
        options.inter_op_num_threads = options.intra_op_num_threads = 1
        options.log_severity_level = 3
        self.vad = ort.InferenceSession(str(fetch_silero(models_dir())), sess_options=options,
                                        providers=["CPUExecutionProvider"])
        self.lock = threading.Lock()

    def transcribe(self, audio: np.ndarray) -> str:
        mx = self.mx
        with self.lock:
            mel = self._get_logmel(mx.array(audio, dtype=mx.float32), self.model.preprocessor_config)
            return self.model.generate(mel)[0].text.strip()

    def warmup(self) -> None:
        """Compile the Metal kernels before the first turn."""
        self.transcribe((0.01 * np.random.default_rng(0).standard_normal(SR)).astype(np.float32))

    def turn(self, stop_word: str, rate: int) -> "ParakeetTurn":
        return ParakeetTurn(self, stop_word, rate)


# --- one turn --------------------------------------------------------------------------------------------------------

class ParakeetTurn:
    def __init__(self, engine: Parakeet, stop_word: str, rate: int, *, close_ms: int = CLOSE_MS,
                 partial_ms: int = PARTIAL_MS, recheck_ms: int = RECHECK_MS):
        self.m, self.stop_word, self.rate = engine, stop_word, rate
        self.close_frames = int(np.ceil(close_ms / 1000 / FD - 1e-9))
        self.recheck_frames = int(np.ceil(recheck_ms / 1000 / FD - 1e-9)) if recheck_ms else 0
        self.partial_s = partial_ms / 1000
        self.vad = _Silero(engine.vad)
        self._pending = np.zeros(0, np.float32)
        self._frames: list[np.ndarray] = []
        self._probs: list[float] = []
        self._dbs: list[float] = []
        self._level: float | None = None             # running dB level of confident speech
        self._speech = self._had = self._seg_open = False
        self._sil = 0
        self._rechecked = True
        self._last_partial_t = 0.0
        self._speech_end_t = 0.0
        self._prev_stop: tuple[str, float] | None = None
        self._done = False
        self._caption = ""
        self.asr_ms_total = 0.0
        self.passes = 0

    # --- the worker's side --------------------------------------------------------------------------------------
    def feed(self, pcm: np.ndarray) -> list[dict[str, Any]]:
        if self._done:
            return []
        x = resample(pcm.astype(np.float32) / 32768.0 if pcm.dtype == np.int16 else pcm.astype(np.float32), self.rate)
        self._pending = np.concatenate([self._pending, x.reshape(-1)])
        events: list[dict[str, Any]] = []
        while len(self._pending) >= FRAME:
            frame, self._pending = self._pending[:FRAME], self._pending[FRAME:]
            ev = self._frame(frame)
            if ev is not None:
                events.append(ev)
                if ev["op"] == "stt.final":
                    return self._dedupe(events)
        # At most one caption pass per call, so a burst of frames (the model thread was busy) catches up in one go.
        if self._seg_open and self._t() - self._last_partial_t >= self.partial_s:
            self._last_partial_t = self._t()
            text, ms = self._asr()
            hit, content = split_stop(text, self.stop_word)
            if hit:
                key = " ".join(_norm_tokens(content))
                if self._prev_stop and self._prev_stop[0] == key and self._t() - self._prev_stop[1] >= STABLE_GAP_S:
                    return self._dedupe(events + [self._final(content, True, ms)])
                if not self._prev_stop or self._prev_stop[0] != key:
                    self._prev_stop = (key, self._t())
            else:
                self._prev_stop = None
            events.append(self._partial(text))
        return self._dedupe(events)

    def finish(self) -> dict[str, Any]:
        """The turn is ended from outside (a tap, or the stream closed): the whole transcript, stop word as heard."""
        if self._done:
            return {"op": "stt.final", "text": "", "stop_word": False, "audio_s": round(self._t(), 2), "ms": 0}
        if not self._frames and len(self._pending) == 0:
            return self._final("", False, 0.0)
        if len(self._pending):
            self._frames.append(np.pad(self._pending, (0, FRAME - len(self._pending))))
            self._probs.append(self._probs[-1] if self._probs else 0.0)
            self._dbs.append(self._dbs[-1] if self._dbs else -100.0)
            self._pending = np.zeros(0, np.float32)
        text, ms = self._asr(full=True)
        hit, content = split_stop(text, self.stop_word)
        return self._final(content, hit, ms)

    # --- inside -------------------------------------------------------------------------------------------------
    def _t(self) -> float:
        return len(self._frames) * FD

    def _partial(self, text: str) -> dict[str, Any]:
        return {"op": "stt.partial", "text": text}

    def _dedupe(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Captions only when they change."""
        out = []
        for ev in events:
            if ev["op"] == "stt.partial":
                if not ev["text"] or ev["text"] == self._caption:
                    continue
                self._caption = ev["text"]
            out.append(ev)
        return out

    def _frame(self, frame: np.ndarray) -> dict[str, Any] | None:
        p = self.vad(frame)
        db = 10 * np.log10(float(np.mean(frame ** 2)) + 1e-10)
        self._frames.append(frame)
        self._probs.append(p)
        self._dbs.append(db)
        if p >= 0.8:
            self._level = db if self._level is None else 0.95 * self._level + 0.05 * db
        if self._level is not None and db < self._level - GATE_DB:
            p = 0.0
        self._speech = p >= (VAD_OFF if self._speech else VAD_ON)
        if self._speech:
            self._had = self._seg_open = True
            self._sil = 0
            self._speech_end_t = self._t()
            return None
        self._sil += 1
        if self._seg_open and self._sil >= self.close_frames:            # speech paused: is that the stop word?
            self._seg_open, self._rechecked = False, False
            self._last_partial_t = self._t()
            self._prev_stop = None
            text, ms = self._asr()
            hit, content = split_stop(text, self.stop_word)
            return self._final(content, True, ms) if hit else self._partial(text)
        if (not self._seg_open and self._had and not self._rechecked and self.recheck_frames
                and self._sil >= self.recheck_frames):                   # one more look, with all the context
            self._rechecked = True
            text, ms = self._asr(full=True)
            hit, content = split_stop(text, self.stop_word)
            return self._final(content, True, ms) if hit else None
        return None

    def _gated_audio(self, start_frame: int) -> np.ndarray:
        probs, dbs = np.asarray(self._probs), np.asarray(self._dbs)
        keep = probs >= VAD_ON
        confident = dbs[probs >= 0.8]
        if len(confident) >= 5:
            keep &= dbs >= np.percentile(confident, 90) - GATE_DB
        near = np.convolve(keep.astype(np.int8), np.ones(11, np.int8), mode="full")[4:4 + len(keep)] > 0
        gain = np.repeat(np.where(near, 1.0, 0.01), FRAME).astype(np.float32)          # -40 dB elsewhere
        gain = np.convolve(gain, np.ones(128, np.float32) / 128, mode="same")          # 8 ms ramps
        x = (np.concatenate(self._frames) * gain)[start_frame * FRAME:]
        return np.concatenate([x, np.zeros(int(TAIL_PAD_S * SR), np.float32)])

    def _asr(self, full: bool = False) -> tuple[str, float]:
        start = 0 if full else max(0, len(self._frames) - int(WINDOW_S / FD))
        audio = self._gated_audio(start)
        t0 = time.perf_counter()
        text = self.m.transcribe(audio)
        ms = 1000 * (time.perf_counter() - t0)
        self.asr_ms_total += ms
        self.passes += 1
        return text, ms

    def _final(self, content: str, stop: bool, ms: float) -> dict[str, Any]:
        if self._t() > WINDOW_S and stop:          # a long turn was checked in a window: read all of it for the text
            text, more = self._asr(full=True)
            content = split_stop(text, self.stop_word)[1]
            ms += more
        self._done = True
        latency = 1000 * (self._t() - self._speech_end_t) + ms
        return {"op": "stt.final", "text": content, "stop_word": stop, "audio_s": round(self._t(), 2),
                "ms": round(latency), "passes": self.passes}
