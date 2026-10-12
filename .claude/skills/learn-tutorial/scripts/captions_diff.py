"""Diff YouTube's auto-captions against the Parakeet transcript and flag every spoken value.

    run captions_diff.py src/<id>.en.json3 transcript.parakeet.json --words transcript.captions.json \\
        --out captions_diff.md

Two lists come out:
- differing spans, with VALUE marked where either side holds a number, a note name, a unit
  (dB, Hz, ms, %, BPM, bars...) or a device or control name. Those disagreements change a recipe;
  homophones ("bass"/"base") and filler do not. Settle each VALUE span by ear or on screen.
- every spoken value in the transcript with its time, agreed or not, as a checklist for the
  scrape: each one must end up in the recipe or in its gaps.
"""

from __future__ import annotations

import argparse
import difflib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import fmt_time  # noqa: E402

NUMBER_WORDS = {"zero", "one", "two", "three", "four", "five", "six", "seven", "eight", "nine", "ten", "eleven",
                "twelve", "fifteen", "sixteen", "twenty", "thirty", "forty", "fifty", "sixty", "hundred",
                "thousand", "half", "quarter", "third", "eighth", "sixteenth", "double", "triple"}
UNITS = r"(db|decibels?|hz|hertz|khz|kilohertz|ms|milliseconds?|seconds?|%|percent|bpm|bars?|beats?|semitones?|" \
        r"cents|octaves?|lufs|ratio|samples?|steps?)"
DEVICES = {"operator", "simpler", "sampler", "wavetable", "drift", "meld", "analog", "collision", "tension",
           "electric", "drum rack", "instrument rack", "eq eight", "eq three", "channel eq", "compressor",
           "glue", "glue compressor", "multiband", "ott", "limiter", "saturator", "roar", "overdrive",
           "pedal", "amp", "cabinet", "redux", "erosion", "vinyl distortion", "dynamic tube", "drum buss",
           "utility", "auto filter", "auto pan", "beat repeat", "echo", "delay", "simple delay",
           "filter delay", "grain delay", "reverb", "hybrid reverb", "chorus", "phaser", "flanger",
           "frequency shifter", "spectrum", "tuner", "gate", "corpus", "resonators", "vocoder",
           "shifter", "arpeggiator", "note length", "velocity", "sidechain",
           "warp", "transpose", "detune", "glide", "portamento", "attack", "decay", "sustain", "release",
           "threshold", "cutoff", "resonance", "drive", "dry/wet", "dry wet", "quantize", "swing",
           "groove pool", "tempo", "time signature"}
NOTE_RE = re.compile(r"^[a-g](#|b|sharp|flat)?-?\d$|^[a-g](#|sharp|flat)$", re.I)


def caption_words(path: Path) -> list[dict]:
    d = json.loads(path.read_text())
    words = []
    for ev in d.get("events", []):
        t0 = ev.get("tStartMs", 0)
        for s in ev.get("segs", []):
            for w in s.get("utf8", "").split():
                words.append({"text": w, "start": round((t0 + s.get("tOffsetMs", 0)) / 1000, 3),
                              "conf": s.get("acAsrConf")})
    return words


def norm(w: str) -> str:
    w = w.lower().replace("’", "'")
    w = re.sub(r"[^a-z0-9'#%]+", "", w)
    return {"gonna": "going", "wanna": "want"}.get(w, w)


def is_value(words: list[str]) -> bool:
    text = " ".join(w.lower() for w in words)
    if re.search(r"\d", text) or re.search(rf"\b{UNITS}\b", text):
        return True
    if any(norm(w) in NUMBER_WORDS for w in words) or any(NOTE_RE.match(w.strip(".,;:!?")) for w in words):
        return True
    return any(re.search(rf"\b{re.escape(d)}\b", text) for d in DEVICES)


def spoken_values(words: list[dict]) -> list[dict]:
    """Every word (with a word either side) that carries a value, in transcript order."""
    out = []
    for i, w in enumerate(words):
        if is_value([w["text"]]) or (i + 1 < len(words) and is_value([w["text"], words[i + 1]["text"]])
                                      and not is_value([words[i + 1]["text"]])):
            ctx = " ".join(x["text"] for x in words[max(0, i - 2):i + 3])
            if out and out[-1]["i"] >= i - 2:
                continue
            out.append({"i": i, "t": w["start"], "word": w["text"], "context": ctx})
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("captions", help="YouTube json3")
    ap.add_argument("parakeet", help="transcribe.py output")
    ap.add_argument("--words", help="write the caption words with times here")
    ap.add_argument("--out", required=True, help="Markdown report")
    a = ap.parse_args()

    if not Path(a.captions).exists():
        raise SystemExit(f"no captions at {a.captions}: YouTube had none in English (see meta.json 'captions'; "
                         "an en-orig file works the same). Skip the diff, check spoken values by ear, and say so "
                         "in PROCESS.md")
    cap = caption_words(Path(a.captions))
    if a.words:
        Path(a.words).write_text(json.dumps(cap, indent=1, ensure_ascii=False) + "\n")
    pk = json.loads(Path(a.parakeet).read_text())["words"]
    sm = difflib.SequenceMatcher(a=[norm(w["text"]) for w in pk], b=[norm(w["text"]) for w in cap], autojunk=False)
    rows, n_value = [], 0
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        pk_w, cap_w = [w["text"] for w in pk[i1:i2]], [w["text"] for w in cap[j1:j2]]
        value = is_value(pk_w) or is_value(cap_w)
        n_value += value
        t = pk[i1]["start"] if i1 < len(pk) else pk[-1]["end"]
        rows.append(f"| {len(rows) + 1} | {fmt_time(t)} | {' '.join(pk_w) or '-'} | {' '.join(cap_w) or '-'} | {op} | "
                    f"{'**VALUE**' if value else ''} |")
    vals = spoken_values(pk)
    head = (f"Parakeet words: {len(pk)}; caption words: {len(cap)}; normalised match {sm.ratio():.3f}; "
            f"{len(rows)} differing spans, {n_value} with a value.\n")
    md = [head, "## Differing spans", "",
          "| # | time | Parakeet | YouTube auto-caption | kind | value? |", "|---|---|---|---|---|---|", *rows, "",
          "## Spoken values (check each against the screen and the recipe)", "",
          "| time | word | context |", "|---|---|---|",
          *[f"| {fmt_time(v['t'])} | {v['word']} | {v['context']} |" for v in vals], ""]
    Path(a.out).write_text("\n".join(md))
    print(head + f"{len(vals)} spoken values -> {a.out}")
    for r in rows:
        if "VALUE" in r:
            print(r)


if __name__ == "__main__":
    main()
