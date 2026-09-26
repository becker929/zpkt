"""Level-matched comparison and blind testing (subject 6: Ch. 20-21).

- `match`: gain each file so integrated loudness is equal (default: the
  quietest file's loudness, so nothing is pushed into clipping).
- `abx_kit`: writes A, B and N shuffled X trials plus a sealed answer key.
- `abx_score`: binomial p-value for a set of answers.
- `refs_table`: one file against a folder of references on the core measures.
"""
from __future__ import annotations

import json
import math
import os
import random

import numpy as np

from . import dsp
from . import io as aio
from . import loudness as L
from .util import lin, r


def match(audios, target=None, section=None):
    """audios: list of Audio. section: (start_s, dur_s) to match on a passage only.
    Returns list of (array, gain_db)."""
    levels = []
    for a in audios:
        x = a.x if section is None else dsp.excerpt(a.x, a.sr, *section, fade_ms=0)
        levels.append(L.integrated(x, a.sr))
    tgt = min(levels) if target is None else target
    out = []
    for a, lv in zip(audios, levels):
        g = tgt - lv
        out.append((a.x * lin(g), g))
    return out, tgt


def abx_kit(a, b, outdir, trials=12, start=None, dur=None, seed=None):
    """Level-match A and B, cut the same excerpt, write the kit. Returns key path."""
    os.makedirs(outdir, exist_ok=True)
    (xa, ga), (xb, gb) = match([a, b])[0]
    if start is not None:
        xa = dsp.excerpt(xa, a.sr, start, dur or 15)
        xb = dsp.excerpt(xb, b.sr, start, dur or 15)
    aio.save(os.path.join(outdir, "A.wav"), xa, a.sr)
    aio.save(os.path.join(outdir, "B.wav"), xb, b.sr)
    rng = random.Random(seed if seed is not None else int.from_bytes(os.urandom(4), "big"))
    key = []
    for i in range(1, trials + 1):
        pick = rng.choice("AB")
        aio.save(os.path.join(outdir, f"X{i:02d}.wav"), xa if pick == "A" else xb, a.sr)
        key.append(pick)
    meta = {"A": a.path, "B": b.path, "gain_db": {"A": r(ga), "B": r(gb)}, "trials": trials,
            "key": key, "excerpt": [start, dur]}
    kp = os.path.join(outdir, ".answer_key.json")
    with open(kp, "w") as f:
        json.dump(meta, f, indent=2)
    with open(os.path.join(outdir, "HOW_TO.md"), "w") as f:
        f.write(ABX_HOWTO.format(n=trials))
    return kp


ABX_HOWTO = """# ABX session

A.wav and B.wav are level-matched (equal integrated LUFS).
For each X01..X{n:02d}, decide whether it is A or B. Loop freely.
Write your answers as one string, e.g. `ABBA...`, then run:

    python3 -m mlab abx-score <this folder> <answers>

Do not open `.answer_key.json` first.
{n} trials: 10 or more of 12 right (p = 0.019) means you really hear a difference.
"""


def binom_p(correct, n):
    """One-sided probability of >= correct right answers by guessing."""
    return sum(math.comb(n, k) for k in range(correct, n + 1)) / 2 ** n


def abx_score(folder, answers):
    with open(os.path.join(folder, ".answer_key.json")) as f:
        key = json.load(f)["key"]
    answers = answers.strip().upper()
    n = min(len(key), len(answers))
    correct = sum(1 for i in range(n) if key[i] == answers[i])
    p = binom_p(correct, n)
    return {"trials": n, "correct": correct, "p_value": r(p, 4),
            "verdict": "difference heard (p<0.05)" if p < 0.05 else "no reliable difference"}


def refs_table(target_rows: dict, ref_rows: dict[str, dict], keys):
    """Markdown table: target vs each reference vs reference median on selected keys."""
    names = list(ref_rows)
    head = "| measure | this | " + " | ".join(names) + " | ref median | this − median |\n"
    head += "|---|---|" + "---|" * len(names) + "---|---|\n"
    lines = []
    for k in keys:
        vals = [ref_rows[n].get(k) for n in names]
        nums = [v for v in vals if isinstance(v, (int, float))]
        med = float(np.median(nums)) if nums else None
        t = target_rows.get(k)
        diff = r(t - med) if (isinstance(t, (int, float)) and med is not None) else ""
        lines.append(f"| {k} | {t} | " + " | ".join(str(v) for v in vals) + f" | {r(med)} | {diff} |")
    return head + "\n".join(lines) + "\n"
