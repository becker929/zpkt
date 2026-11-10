"""Read a script aloud: text -> phonemes (through the lexicon) -> Kokoro -> mp3.

Phonemes are the default and the only input the model sees, so what is heard is what the
lexicon says. The phoneme script is written next to the output for review.

Script format: one paragraph per line; a line "@@" is a long pause, "@" a short one.
"""
from __future__ import annotations

import logging
import subprocess
import tempfile
import wave
from pathlib import Path

import numpy as np

from .lexicon import Lexicon, translate_script
from .tts import Kokoro, to_int16

log = logging.getLogger("voice.read")
PAUSE = {"@@": 1.6, "@": 0.8}
LINE_GAP = 0.35


def phonemes(script: Path, out: Path | None = None, lexicon: Lexicon | None = None) -> Path:
    lex = lexicon or Lexicon()
    lines = script.read_text(encoding="utf-8").splitlines()
    phon = translate_script(lines, lex)
    out = out or script.with_suffix(".phon")
    out.write_text("\n".join(phon) + "\n", encoding="utf-8")
    log.info("%d lines; %d new lexicon words (%s)", len(phon), len(lex.added), lex.path)
    return out


def speak(phon: Path, wav: Path, voice: str = "af_heart", speed: float = 1.0) -> float:
    tts = Kokoro(variant="fp32")
    voice = voice if voice in tts.voices else "af_heart"
    rate, chunks = tts.rate, []
    lines = [l.strip() for l in phon.read_text(encoding="utf-8").splitlines() if l.strip()]
    for i, line in enumerate(lines):
        if line in PAUSE:
            chunks.append(np.zeros(int(rate * PAUSE[line]), dtype=np.int16))
            continue
        audio, rate = tts.model.create(line, voice=voice, speed=speed, is_phonemes=True)
        chunks.append(to_int16(np.asarray(audio, dtype=np.float32)))
        chunks.append(np.zeros(int(rate * LINE_GAP), dtype=np.int16))
        if i % 25 == 0:
            log.info("%d/%d lines", i, len(lines))
    audio = np.concatenate(chunks)
    with wave.open(str(wav), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(rate)
        w.writeframes(audio.tobytes())
    return len(audio) / rate


def read(script: Path, out: Path, voice: str = "af_heart", speed: float = 1.0, title: str = "", artist: str = "") -> Path:
    phon = phonemes(script, out.with_suffix(".phon"))
    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "speech.wav"
        seconds = speak(phon, wav, voice, speed)
        tags = [x for k, v in (("title", title), ("artist", artist)) if v for x in ("-metadata", f"{k}={v}")]
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-af", "loudnorm=I=-16:TP=-1.5:LRA=11",
                        "-ar", "24000", "-ac", "1", "-c:a", "libmp3lame", "-q:a", "4", *tags, str(out)], check=True)
    log.info("%s: %.0f s", out, seconds)
    return out
