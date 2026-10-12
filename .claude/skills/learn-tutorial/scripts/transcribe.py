"""Transcribe a 16 kHz mono WAV with Parakeet TDT 0.6B v3 (MLX): words and sentences with times,
plus the demo windows (where music plays instead of speech).

    run transcribe.py src/audio16k.wav transcript.parakeet.json --demo analysis/demo_windows.json

This calls parakeet_mlx directly. zpkt's voice.stt engine is built for live turns (VAD, a stop
word) and gives no timestamps. Parakeet TDT leaves no gap over music: the last word before a demo
absorbs it ("one." ran 19.4-25.4 s in run 1). So a word longer than --demo-min seconds marks a
demo or playback window; later steps measure audio inside those windows.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

MODEL = "mlx-community/parakeet-tdt-0.6b-v3"


def words_from_tokens(tokens) -> list[dict]:
    """Merge subword tokens into words: a token whose text starts with a space begins a word."""
    words: list[dict] = []
    for t in tokens:
        if not words or t.text.startswith(" "):
            words.append({"text": t.text.strip(), "start": t.start, "end": t.end, "confs": [t.confidence]})
        else:
            w = words[-1]
            w["text"] += t.text
            w["end"] = t.end
            w["confs"].append(t.confidence)
    return [{"text": w["text"], "start": round(w["start"], 3), "end": round(w["end"], 3),
             "conf": round(min(w["confs"]), 3)} for w in words if w["text"]]


def demo_windows(words: list[dict], min_s: float) -> list[dict]:
    return [{"start": w["start"], "end": w["end"], "seconds": round(w["end"] - w["start"], 2), "after_word": w["text"]}
            for w in words if w["end"] - w["start"] > min_s]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("wav")
    ap.add_argument("out")
    ap.add_argument("--demo", help="write demo windows (words longer than --demo-min) here")
    ap.add_argument("--demo-min", type=float, default=1.0, help="s")
    ap.add_argument("--chunk", type=float, help="chunk length in s for long videos (overlap 15 s)")
    a = ap.parse_args()

    import mlx.core as mx
    from parakeet_mlx import from_pretrained

    t0 = time.perf_counter()
    model = from_pretrained(MODEL, dtype=mx.float32)
    t1 = time.perf_counter()
    kw = {"chunk_duration": a.chunk, "overlap_duration": 15.0} if a.chunk else {}
    res = model.transcribe(a.wav, dtype=mx.float32, **kw)
    t2 = time.perf_counter()
    words = words_from_tokens(res.tokens)
    data = {"model": MODEL, "load_s": round(t1 - t0, 2), "asr_s": round(t2 - t1, 2), "chunk_duration": a.chunk,
            "text": res.text,
            "sentences": [{"start": round(s.start, 3), "end": round(s.end, 3), "conf": round(s.confidence, 3),
                           "text": s.text.strip()} for s in res.sentences],
            "words": words}
    Path(a.out).write_text(json.dumps(data, indent=1, ensure_ascii=False) + "\n")
    low = sum(w["conf"] < 0.6 for w in words)
    print(f"load {data['load_s']} s, asr {data['asr_s']} s: {len(data['sentences'])} sentences, {len(words)} words, "
          f"{low} under 0.6 confidence -> {a.out}")
    if a.demo:
        dw = demo_windows(words, a.demo_min)
        Path(a.demo).parent.mkdir(parents=True, exist_ok=True)
        Path(a.demo).write_text(json.dumps(dw, indent=1, ensure_ascii=False) + "\n")
        print(f"{len(dw)} demo windows -> {a.demo}")
        for w in dw:
            print(f"  {w['start']:8.2f}-{w['end']:8.2f} s ({w['seconds']} s)")


if __name__ == "__main__":
    main()
