"""Figures for the humming-transcription page.

    python3 -m humtrans.figures /path/to/HumTrans/midis

Reads out/humtrans/*.json and the cached pYIN tracks; writes PNG and SVG to
research/humming-transcription/img/ on the site.
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np

from .common import CACHE, OUT, REPO, load_notes, ref_notes
from .official import LAGS, estimate, notes, score

SITE = REPO.parent.parent / "humming-transcription" / "img"
BG, PANEL, INK, DIM, LINE = "#0e1116", "#151a22", "#e6e9ef", "#9aa4b5", "#262d39"
MODEL_COLOR = {"VOCANO": "#58c7ff", "SheetSage": "#c07be0", "MIR-ST500": "#45e0e8", "JDC-STP": "#ffd23f",
               "pyin": "#ff5470"}
MODEL_LABEL = {"VOCANO": "VOCANO", "SheetSage": "Sheet Sage", "MIR-ST500": "MIR-ST500", "JDC-STP": "JDC-STP",
               "pyin": "pYIN (simple)"}
plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": PANEL, "axes.edgecolor": LINE, "axes.labelcolor": INK,
                     "xtick.color": DIM, "ytick.color": DIM, "text.color": INK, "font.size": 12,
                     "font.family": "DejaVu Sans", "axes.spines.top": False, "axes.spines.right": False,
                     "grid.color": LINE, "grid.alpha": 0.7, "axes.titlesize": 13})


def save(fig, name):
    SITE.mkdir(parents=True, exist_ok=True)
    for ext in ("png", "svg"):
        fig.savefig(SITE / f"{name}.{ext}", dpi=160, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def example(keys):
    """Reference notes against the hummed pitch, for two singers."""
    fig, axes = plt.subplots(len(keys), 1, figsize=(9, 3.1 * len(keys)))
    for ax, (key, title) in zip(np.atleast_1d(axes), keys):
        iv, p = ref_notes(key)
        _, _, d = load_notes(CACHE / "pyin" / f"{key}.json")
        f0 = np.array([np.nan if v is None else v for v in d["f0_midi"]]) - d["tuning"]
        row = next(r for r in json.loads((OUT / "perform_rows.json").read_text()) if r["key"] == key)
        f0 = f0 - 12 * row["octave_vs_label"]  # drawn in the label's octave
        t = np.arange(len(f0)) * 0.01
        for (s, e), m in zip(iv, p):
            ax.add_patch(plt.Rectangle((s, m - 0.4), e - s, 0.8, color="#ffd23f", alpha=0.35, lw=0))
        ax.plot(t, f0, color="#45e0e8", lw=2.2)
        end = min(8.0, iv[-1, 1])
        sel = (iv[:, 0] < end)
        lo, hi = p[sel].min() - 2, p[sel].max() + 2
        ax.set_xlim(0, end)
        ax.set_ylim(lo, hi)
        ax.set_ylabel("pitch, semitones")
        ax.set_title(title, loc="left")
        ax.grid(True, axis="x")
    np.atleast_1d(axes)[-1].set_xlabel("time, seconds")
    handles = [plt.Rectangle((0, 0), 1, 1, color="#ffd23f", alpha=0.5), plt.Line2D([], [], color="#45e0e8", lw=2.2)]
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    fig.legend(handles, ["label: the notes the hummer heard", "pitch they hummed"], loc="upper left",
               frameon=False, ncol=2, bbox_to_anchor=(0.06, 1.0))
    save(fig, "example")


def lag_curve(models):
    fig, ax = plt.subplots(figsize=(9, 4.6))
    for m in models:
        r = json.loads((OUT / f"official_rescored_{m}.json").read_text())[m]["test"]["curve_F1"]
        x = np.array([float(k) for k in r]) * 1000
        y = np.array(list(r.values())) * 100
        keep = x <= 600
        ax.plot(x[keep], y[keep], lw=2.6, color=MODEL_COLOR[m], label=MODEL_LABEL[m])
    ax.axvspan(-50, 50, color=DIM, alpha=0.18, lw=0)
    ax.annotate("the paper\nscored here", (0, 3.5), xytext=(-90, 14), textcoords="data",
                arrowprops={"arrowstyle": "->", "color": INK}, color=INK, fontsize=11)
    ax.set_xlabel("how far every predicted note is moved earlier, ms")
    ax.set_ylabel("note F1 on the test set, %")
    ax.set_title("Moving predictions earlier by about 180 ms multiplies every score", loc="left")
    ax.set_xlim(-100, 600)
    ax.set_ylim(0, None)
    ax.grid(True)
    ax.legend(frameon=False, loc="upper right")
    save(fig, "lag-curve")


def singer_lags():
    rows = json.loads((OUT / "perform_rows.json").read_text())
    by = defaultdict(list)
    for r in rows:
        if r["agree"] > 0.5:
            by[r["singer"]].append(r["lag"] * 1000)
    singers = sorted(by, key=lambda s: np.median(by[s]))
    fig, ax = plt.subplots(figsize=(9, 4.8))
    rng = np.random.default_rng(0)
    for i, s in enumerate(singers):
        v = np.array(by[s])
        late = np.median(v) > 300
        c = "#ff5470" if late else "#45e0e8"
        ax.scatter(v, i + rng.uniform(-0.28, 0.28, len(v)), s=9, color=c, alpha=0.45, lw=0)
        ax.plot([np.median(v)] * 2, [i - 0.38, i + 0.38], color=INK, lw=2.4)
    ax.axvspan(-50, 50, color=DIM, alpha=0.18, lw=0)
    ax.text(0, len(singers) - 0.35, "scoring\nwindow", ha="center", va="bottom", color=DIM, fontsize=10)
    ax.set_yticks(range(len(singers)))
    ax.set_yticklabels(singers)
    ax.set_ylim(-0.6, len(singers) + 0.5)
    ax.set_xlabel("how late the humming is against its label, ms  (one dot per recording, bar = median)")
    ax.set_title("Each singer has their own delay. Two are far behind.", loc="left")
    ax.grid(True, axis="x")
    save(fig, "singer-lags")


def protocols(models):
    fig, ax = plt.subplots(figsize=(9, 4.8))
    names = ["as published", "one delay for all", "one delay per singer"]
    colors = ["#5b6270", "#58c7ff", "#45e0e8"]
    order = sorted(models, key=lambda m: -json.loads((OUT / f"official_rescored_{m}.json").read_text())[m]["test_at_singer_lag"][2])
    h = 0.26
    for i, m in enumerate(order):
        r = json.loads((OUT / f"official_rescored_{m}.json").read_text())[m]
        vals = [r["test"]["at_0"][2], r["test_at_valid_lag"][2], r["test_at_singer_lag"][2]]
        for j, (v, c) in enumerate(zip(vals, colors)):
            y = i + (j - 1) * h
            ax.barh(y, v * 100, height=h * 0.92, color=c, label=names[j] if i == 0 else None)
            ax.text(v * 100 + 0.6, y, f"{v * 100:.0f}", va="center", fontsize=10, color=INK)
    ax.set_yticks(range(len(order)))
    ax.set_yticklabels([MODEL_LABEL[m] for m in order])
    ax.invert_yaxis()
    ax.set_xlabel("note F1 on the test set, %  (delays chosen on the validation set)")
    ax.set_title("Same predictions, scored three ways", loc="left")
    ax.grid(True, axis="x")
    ax.legend(frameon=False, loc="upper center", bbox_to_anchor=(0.45, -0.14), ncol=3)
    save(fig, "protocols")


def errors(models):
    e = json.loads((OUT / "errors.json").read_text())
    order = [m for m in models if m in e]
    fig, (a, b) = plt.subplots(1, 2, figsize=(11, 4.9), sharey=True)
    y = np.arange(len(order))
    a.barh(y - 0.18, [e[m]["onset_F1"] * 100 for m in order], 0.34, color="#58c7ff", label="right time")
    a.barh(y + 0.18, [e[m]["note_F1"] * 100 for m in order], 0.34, color="#45e0e8", label="right time and pitch")
    a.set_title("Found at the right time, and with the right pitch", loc="left", fontsize=12)
    a.set_xlabel("F1 on the test set, %", labelpad=2)
    a.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.2), ncol=2, fontsize=10.5)
    off = lambda m, d: e[m]["pitch_off_semitones_among_onset_matches"].get(str(d), 0) * 100
    b.barh(y - 0.18, [off(m, -1) for m in order], 0.34, color="#ff5470", label="one semitone flat")
    b.barh(y + 0.18, [off(m, 1) for m in order], 0.34, color="#ffd23f", label="one semitone sharp")
    b.set_title("Among well-timed notes, wrong pitches lean flat", loc="left", fontsize=12)
    b.set_xlabel("share of well-timed notes, %", labelpad=2)
    b.legend(frameon=False, loc="upper left", bbox_to_anchor=(0, -0.2), ncol=2, fontsize=10.5)
    for ax, top in ((a, 70), (b, 25)):
        ax.grid(True, axis="x")
        ax.set_xlim(0, top)
    a.set_yticks(y)
    a.set_yticklabels([MODEL_LABEL[m] for m in order])
    a.invert_yaxis()
    fig.tight_layout()
    save(fig, "errors")


def main():
    models = ["MIR-ST500", "VOCANO", "JDC-STP", "SheetSage", "pyin"]
    models = [m for m in models if (OUT / f"official_rescored_{m}.json").exists()]
    figs = {
        "example": lambda: example([
            ("F01_0024_0001_1", "Singer F01: the humming trails the label by 0.18 s"),
            ("M02_0190_0002_1", "Singer M02: 0.77 s behind, and an octave lower (moved up to compare)")]),
        "lag-curve": lambda: lag_curve([m for m in models if m != "pyin"]),
        "singer-lags": singer_lags,
        "protocols": lambda: protocols(models),
        "errors": lambda: errors(models),
    }
    for name in sys.argv[2:] or figs:
        figs[name]()


if __name__ == "__main__":
    main()
