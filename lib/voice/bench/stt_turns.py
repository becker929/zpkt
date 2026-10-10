"""Run voice.stt's turn over a benchmark test set and score it (docs/voice-benchmark.md).

    uv run --extra engines python bench/stt_turns.py <testset dir> [--frame-ms 40] [--json out.json]

The test set is a folder of 16 kHz mono WAVs and a manifest.json: a list of {"id", "cond", "file", "voice", "stop",
"ref_content", "t_stop_end"} (the bench's own set lives outside the repo, in ~/_agent_scratch/voice-bench/stt/testset).

Latency is measured the way the phone sees it: frames are fed in order, stream time advances with the audio fed, and
the model time spent after "tomato" ended is added (frames queue while it runs). Reported: stop-word recall, false
ends (a final on a file without the stop word, or before it was said), latency, and the final text's word error
rate (numbers and spellings normalised).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
import wave
from pathlib import Path

import numpy as np

from voice.stt import Parakeet

ROBOTIC = {"Fred", "Kathy", "Ralph"}          # macOS voices that sound least like a person
NUMBERS = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen "
           "sixteen seventeen eighteen nineteen").split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
EQUIV = [(" a slash b ", " a b "), (" ab ", " a b "), (" high hat", " hihat"), (" hi hat", " hihat"),
         (" decibels ", " db "), (" decibel ", " db "), (" dee bee ", " db "), (" percent ", " % ")]


def spoken(n: int) -> str:
    if n < 0:
        return "minus " + spoken(-n)
    if n < 20:
        return NUMBERS[n]
    if n < 100:
        return TENS[n // 10] + ("" if n % 10 == 0 else " " + NUMBERS[n % 10])
    if n < 1000:
        return NUMBERS[n // 100] + " hundred" + ("" if n % 100 == 0 else " " + spoken(n % 100))
    return " ".join(NUMBERS[int(d)] for d in str(n))


def normalise(text: str) -> list[str]:
    t = text.lower().replace("%", " percent ").replace("-", " minus " if re.search(r"-\d", text) else " ")
    t = re.sub(r"\d+", lambda m: f" {spoken(int(m.group()))} ", t)
    t = " " + re.sub(r"[^a-z ]+", " ", t) + " "
    for a, b in EQUIV:
        t = t.replace(a, b)
    return t.split()


def word_errors(ref: str, hyp: str) -> tuple[int, int]:
    r, h = normalise(ref), normalise(hyp)
    d = list(range(len(h) + 1))
    for i in range(1, len(r) + 1):
        prev, d[0] = d[0], i
        for j in range(1, len(h) + 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r[i - 1] != h[j - 1]))
    return d[len(h)], len(r)


def read(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        assert w.getframerate() == 16_000 and w.getnchannels() == 1 and w.getsampwidth() == 2, path
        return np.frombuffer(w.readframes(w.getnframes()), np.int16)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("testset", type=Path)
    ap.add_argument("--frame-ms", type=int, default=40)
    ap.add_argument("--json", type=Path)
    a = ap.parse_args()
    manifest = json.loads((a.testset / "manifest.json").read_text())
    t0 = time.perf_counter()
    engine = Parakeet()
    engine.warmup()
    load_s = time.perf_counter() - t0
    step = 16 * a.frame_ms
    rows = []
    for m in manifest:
        pcm = read(a.testset / m["file"])
        turn = engine.turn("tomato", 16_000)
        final, after_ms = None, 0.0
        for i in range(0, len(pcm), step):
            before = turn.asr_ms_total
            events = turn.feed(pcm[i:i + step])
            if m["stop"] and (i + step) / 16_000 >= m["t_stop_end"]:
                after_ms += turn.asr_ms_total - before
            final = next((e for e in events if e["op"] == "stt.final"), None)
            if final:
                break
        row = {"id": m["id"], "cond": m["cond"], "voice": m["voice"], "stop": m["stop"], "detected": bool(final)}
        if final:
            row["early"] = bool(m["stop"] and final["audio_s"] < m["t_stop_end"] - 0.05)
            row["text"] = final["text"]
            if m["stop"]:
                row["latency_ms"] = round(1000 * (final["audio_s"] - m["t_stop_end"]) + after_ms)
                row["err"], row["n"] = word_errors(m["ref_content"], final["text"])
        rows.append(row)
        print(f"{m['cond']:>9} {m['id']:>4} stop={m['stop']!s:5} -> {row.get('text', '-')!r}"
              f" {row.get('latency_ms', '')}", file=sys.stderr)

    stops = [r for r in rows if r["stop"]]
    hits = [r for r in stops if r["detected"] and not r["early"]]
    natural = [r for r in stops if r["voice"] not in ROBOTIC]
    natural_hits = [r for r in natural if r["detected"] and not r["early"]]
    false_ends = sum(r["detected"] for r in rows if not r["stop"]) + sum(r.get("early", False) for r in stops)
    lat = np.array([r["latency_ms"] for r in hits])
    errs, words = sum(r["err"] for r in hits), sum(r["n"] for r in hits)
    by_cond = {c: f"{np.median([r['latency_ms'] for r in hits if r['cond'] == c]):.0f}"
               for c in sorted({r["cond"] for r in hits})}
    summary = {
        "engine": engine.name, "load_s": round(load_s, 2), "frame_ms": a.frame_ms,
        "stop_recall": f"{len(hits)}/{len(stops)}", "recall_natural": f"{len(natural_hits)}/{len(natural)}",
        "false_ends": f"{false_ends}/{sum(not r['stop'] for r in rows)}",
        "latency_ms": {"median": round(float(np.median(lat))), "p90": round(float(np.percentile(lat, 90))),
                       "max": int(lat.max())},
        "latency_median_by_cond": by_cond,
        "final_wer_pct": round(100 * errs / max(words, 1), 1),
    }
    print(json.dumps(summary, indent=1))
    if a.json:
        a.json.write_text(json.dumps({"summary": summary, "rows": rows}, indent=1))


if __name__ == "__main__":
    main()
