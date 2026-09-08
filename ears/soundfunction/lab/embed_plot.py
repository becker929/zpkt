#!/usr/bin/env python3
"""Draw the embedding: corpus as grey, references orange, the owner's tracks teal, with the
axis meaning spelled out from the loadings.   python3 lab/embed_plot.py -> out/plots/embedding.png"""
import json, sys
from pathlib import Path
import numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from analysis.figures_programme import BG, PANEL, INK, DIM, LINE, REAL, SYNTH, save
ROOT = Path(__file__).resolve().parent.parent
E = json.load(open(ROOT / "lab" / "drive" / "reports" / "embedding.json"))
items = E["items"]; names = E["names"]
def axis_words(k):
    L = sorted(E["loadings"].items(), key=lambda kv: -abs(kv[1][k]))[:4]
    pos = [names[f] for f, v in L if v[k] > 0]; neg = [names[f] for f, v in L if v[k] < 0]
    return f"← {', '.join(neg)}   |   {', '.join(pos)} →"
fig, ax = plt.subplots(figsize=(10, 7.5))
c = [i for i in items if i["kind"] == "corpus"]; r = [i for i in items if i["kind"] == "reference"]; t = [i for i in items if i["kind"] == "track"]
ax.scatter([i["x"] for i in c], [i["y"] for i in c], s=22, color=DIM, alpha=0.45, linewidths=0, label=f"corpus ({len(c)})", zorder=2)
ax.scatter([i["x"] for i in r], [i["y"] for i in r], s=90, color=SYNTH, edgecolor=BG, linewidths=1.2, label="your references", zorder=4)
ax.scatter([i["x"] for i in t], [i["y"] for i in t], s=110, color=REAL, edgecolor=BG, linewidths=1.2, marker="D", label="your tracks", zorder=5)
for i in r + t:
    short = i["label"].split(" - ")[-1].split(" _ ")[-1][:26]
    ax.annotate(short, (i["x"], i["y"]), xytext=(7, 5), textcoords="offset points", fontsize=9, color=INK, zorder=6,
                bbox=dict(boxstyle="round,pad=0.15", fc=PANEL, ec="none", alpha=0.75))
ax.set_xlabel(f"axis 1 ({E['explained'][0]:.0%} of the spread)\n{axis_words(0)}", fontsize=10)
ax.set_ylabel(f"axis 2 ({E['explained'][1]:.0%})\n{axis_words(1)}", fontsize=10)
ax.axhline(0, color=LINE, linewidth=1); ax.axvline(0, color=LINE, linewidth=1)
ax.grid(True, alpha=0.35); ax.set_axisbelow(True)
ax.legend(frameon=False, loc="upper left", fontsize=9)
ax.set_title("Where your tracks sit: 14 measures per track, two axes, standardised on the corpus", loc="left", fontsize=12, pad=12)
fig.tight_layout(); save(fig, "embedding"); print("drew out/plots/embedding.png")
