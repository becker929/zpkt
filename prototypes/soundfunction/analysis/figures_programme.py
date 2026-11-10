"""Figures for part two of the report.   python3 analysis/figures_programme.py [stage1|stage3|stage4|all]

Palette: two validated series colours on the dark surface (teal = real / measured,
orange = synthetic / reference); magnitude uses one teal ramp; text stays in ink.
"""
import csv, json, sys, statistics as st
import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap

BG, PANEL, INK, DIM, LINE = "#0e1116", "#151a22", "#e6e9ef", "#9aa4b5", "#262d39"
REAL, SYNTH, THIRD = "#1f9fa8", "#cf7f2a", "#b57bd6"
RAMP = LinearSegmentedColormap.from_list("teal", ["#151a22", "#155e66", "#1f9fa8", "#9fe8ee"])
plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": PANEL, "axes.edgecolor": LINE, "axes.labelcolor": INK,
                     "xtick.color": DIM, "ytick.color": DIM, "text.color": INK, "font.size": 11, "font.family": "DejaVu Sans",
                     "axes.spines.top": False, "axes.spines.right": False, "grid.color": LINE, "grid.alpha": 0.6})
JOBS = ["kick", "rumble", "hat", "clap", "hook", "space"]
ROLE_OF = {"hat_closed": "hat", "hat_open": "hat", "perc": "hook", "stab": "hook", "pad": "space", "riser": "space", "impact": "space"}


def save(fig, name):
    for ext in ("png", "svg"):
        fig.savefig(f"out/plots/{name}.{ext}", dpi=160, bbox_inches="tight", facecolor=BG)
    plt.close(fig)


def bars(ax, x, h, color, width=0.36, label=None):
    ax.bar(x, h, width=width, color=color, label=label, linewidth=0, zorder=3)


def stage1():
    d = json.load(open("out/classifier_union.json"))
    rs, rr = d["by_domain"]["synth"]["recall"], d["by_domain"]["real"]["recall"]
    fig, ax = plt.subplots(figsize=(8, 4))
    x = np.arange(len(JOBS))
    bars(ax, x - 0.2, [rs[j] * 100 for j in JOBS], SYNTH, label="synthetic sounds")
    bars(ax, x + 0.2, [rr.get(j, 0) * 100 for j in JOBS], REAL, label="real samples")
    for i, j in enumerate(JOBS):
        ax.text(x[i] + 0.2, rr.get(j, 0) * 100 + 2, f"{rr.get(j, 0) * 100:.0f}", ha="center", fontsize=9, color=INK)
    ax.set_xticks(x); ax.set_xticklabels(JOBS); ax.set_ylim(0, 105); ax.set_ylabel("named right, out of 100")
    ax.set_title("Seven measures, one model: how often it names the job", loc="left", fontsize=12, pad=12)
    ax.grid(True, axis="y"); ax.set_axisbelow(True); ax.legend(frameon=False, loc="lower left", fontsize=9)
    save(fig, "stage1-recall")

    # synthetic vs real: where the pilot's sounds were not like the real thing
    def med(path):
        rows = list(csv.DictReader(open(path))); out = {}
        for j in JOBS:
            sel = [r for r in rows if ROLE_OF.get(r["sound"], r["sound"]) == j]
            out[j] = {k: st.median(float(r[k]) for r in sel if r[k] not in ("", "nan")) for k in ("rise_10_90_ms", "sustain_share", "decay40_ms")}
        return out
    s, r = med("out/library_synth.csv"), med("out/library_real.csv")
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.6))
    for ax, k, lab, log in zip(axes, ["rise_10_90_ms", "decay40_ms", "sustain_share"], ["rise time, ms", "time to fall 40 dB, ms", "share of energy after 50 ms"], [True, True, False]):
        y = np.arange(len(JOBS))
        for i, j in enumerate(JOBS):
            a, b = s[j][k], r[j][k]
            if log: a, b = max(a, 0.05), max(b, 0.05)
            ax.plot([a, b], [i, i], color=LINE, linewidth=2, zorder=2)
            ax.scatter([a], [i], color=SYNTH, s=46, zorder=3, label="synthetic" if i == 0 else None)
            ax.scatter([b], [i], color=REAL, s=46, zorder=3, label="real" if i == 0 else None)
        ax.set_yticks(y); ax.set_yticklabels(JOBS); ax.invert_yaxis(); ax.set_xlabel(lab)
        if log: ax.set_xscale("log")
        ax.grid(True, axis="x"); ax.set_axisbelow(True)
    axes[0].legend(frameon=False, fontsize=9, loc="upper right")
    fig.suptitle("Median per job: the pilot's synthetic sounds against real samples", x=0.01, ha="left", fontsize=12)
    fig.tight_layout(); save(fig, "stage1-synth-vs-real")


def stage3():
    d = json.load(open("out/pump_synth.json"))
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    ax = axes[0]
    ax.plot([r["duck_ms"] for r in d], [r["pump_depth_db"] for r in d], "-o", color=REAL, linewidth=2, markersize=7)
    ax.set_xlabel("ducking we built in, ms"); ax.set_ylabel("pump depth we measured, dB"); ax.grid(True); ax.set_axisbelow(True)
    ax.set_title("Known ducking in, measured depth out", loc="left", fontsize=11)
    ax = axes[1]
    for r in d:
        c = np.array(r["curve_db"]); t = np.arange(len(c)) * 4
        ax.plot(t, c, color=RAMP(0.35 + 0.65 * r["duck_ms"] / 300), linewidth=2, label=f"{r['duck_ms']} ms")
    ax.set_xlabel("time after the kick, ms"); ax.set_ylabel("low band level, dB"); ax.grid(True); ax.set_axisbelow(True)
    ax.legend(frameon=False, fontsize=8, title="ducking", title_fontsize=8); ax.set_title("The beat curve for each loop", loc="left", fontsize=11)
    fig.tight_layout(); save(fig, "stage3-pump-check")


def stage4():
    S = json.load(open("corpus2/summary.json")); T = S["tracks"]; A = S["all"]
    # 1 pump depth across the corpus
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    ax = axes[0]; v = [t["pump_depth_db"] for t in T if t.get("pump_depth_db") is not None]
    ax.hist(v, bins=np.arange(0, 32, 2), color=REAL, linewidth=0, zorder=3, rwidth=0.92)
    ax.axvline(A["pump_depth_median"], color=INK, linewidth=1.2, linestyle="--"); ax.text(A["pump_depth_median"] + 0.5, ax.get_ylim()[1] * 0.9, f"median {A['pump_depth_median']:.1f} dB", fontsize=9)
    ax.set_xlabel("pump depth, dB"); ax.set_ylabel("tracks"); ax.grid(True, axis="y"); ax.set_axisbelow(True); ax.set_title("How deep the low band dips after the kick", loc="left", fontsize=11)
    ax = axes[1]; v = [t["pump_return_ms"] for t in T if t.get("pump_return_ms") is not None]
    ax.hist(v, bins=np.arange(80, 420, 20), color=REAL, linewidth=0, zorder=3, rwidth=0.92)
    ax.set_xlabel("time until it is back, ms"); ax.set_ylabel("tracks"); ax.grid(True, axis="y"); ax.set_axisbelow(True); ax.set_title("How long the dip lasts", loc="left", fontsize=11)
    fig.tight_layout(); save(fig, "stage4-pump-corpus")
    # 2 the bar grid, aligned to bar one
    P = np.array(S["mean_profile_attack"])
    fig, ax = plt.subplots(figsize=(9, 3.4))
    im = ax.imshow(P / P.max(axis=1, keepdims=True), aspect="auto", cmap=RAMP, vmin=0, vmax=1)
    ax.set_yticks(range(6)); ax.set_yticklabels(["sub 20–60", "low 60–150", "low-mid", "mid 400–2k", "high 2–6k", "air 6k+"])
    ax.set_xticks(range(16)); ax.set_xticklabels([str(i + 1) if i % 4 == 0 else "·" for i in range(16)])
    ax.set_xlabel("step in the bar (1, 2, 3, 4 are the beats)"); ax.set_title(f"Where each band's attacks land, averaged over {A['n']} tracks, bar one found", loc="left", fontsize=11, pad=10)
    for i in range(6):
        ax.axhline(i - 0.5, color=BG, linewidth=2)
    for k in range(16):
        ax.axvline(k - 0.5, color=BG, linewidth=2)
    plt.colorbar(im, ax=ax, fraction=0.03, pad=0.02).set_label("share, scaled per band")
    save(fig, "stage4-bar-grid")
    # 3 clap on 2 and 4, and the breakdown lengths
    fig, axes = plt.subplots(1, 2, figsize=(9, 3.6))
    ax = axes[0]; v = [t["clap_on_2_4"] for t in T]
    ax.hist(v, bins=np.linspace(0.5, 0.8, 16), color=REAL, linewidth=0, zorder=3, rwidth=0.92)
    ax.axvline(0.55, color=INK, linewidth=1.2, linestyle="--"); ax.text(0.555, ax.get_ylim()[1] * 0.9, "clear backbeat", fontsize=9)
    ax.set_xlabel("share of mid and high attacks on the louder beat pair"); ax.set_ylabel("tracks"); ax.grid(True, axis="y"); ax.set_axisbelow(True)
    ax.set_title("Is there a clap on two and four?", loc="left", fontsize=11)
    ax = axes[1]; h = A["break_len_hist"]; ks = sorted(int(k) for k in h); ks = [k for k in ks if k <= 40]
    cols = [REAL if k % 8 == 0 else ("#155e66" if k % 4 == 0 else LINE) for k in ks]
    ax.bar(ks, [h[str(k)] for k in ks], color=cols, width=0.8, linewidth=0, zorder=3)
    ax.set_xlabel("bars the kick is off (teal = multiple of 8, dark teal = of 4)"); ax.set_ylabel("count"); ax.grid(True, axis="y"); ax.set_axisbelow(True)
    ax.set_title("How long the kick stays away", loc="left", fontsize=11)
    fig.tight_layout(); save(fig, "stage4-phrase")
    # 4 per-label spread of three headline numbers (producers rarely have 3+ tracks after the cap)
    pp = S["per_label"]; names = sorted(pp, key=lambda a: -pp[a]["n"])
    nice = lambda a: a.replace("-netlabel", "").replace("_", " ").replace("-", " ")
    fig, axes = plt.subplots(1, 3, figsize=(10, 0.4 * len(names) + 1.8), sharey=True)
    y = np.arange(len(names))
    vals = {"backbeat": [pp[a]["clear_backbeat"] / pp[a]["n"] for a in names], "pump": [pp[a]["pump_depth_median"] for a in names], "off": [pp[a]["kick_off_share_median"] for a in names]}
    alls = {"backbeat": A["clear_backbeat"] / A["n"], "pump": A["pump_depth_median"], "off": A["kick_off_share_median"]}
    for ax, k, lab in zip(axes, ["backbeat", "pump", "off"], ["share of tracks with a clear backbeat", "pump depth, dB (median)", "share of bars with no kick (median)"]):
        ax.axvline(alls[k], color=INK, linewidth=1, linestyle="--", zorder=2)
        ax.scatter(vals[k], y, color=REAL, s=44, zorder=3)
        ax.set_xlabel(lab); ax.grid(True, axis="x"); ax.set_axisbelow(True)
    axes[0].set_yticks(y); axes[0].set_yticklabels([f"{nice(a)[:24]} ({pp[a]['n']})" for a in names], fontsize=9); axes[0].invert_yaxis()
    fig.suptitle("The same numbers per label (dashed line = whole corpus)", x=0.01, ha="left", fontsize=12)
    fig.tight_layout(); save(fig, "stage4-labels")
    # 5 tempo
    fig, ax = plt.subplots(figsize=(8, 3))
    ax.hist([t["tempo"] for t in T], bins=np.arange(128, 182, 2), color=REAL, linewidth=0, zorder=3, rwidth=0.92)
    ax.set_xlabel("tempo, beats per minute"); ax.set_ylabel("tracks"); ax.grid(True, axis="y"); ax.set_axisbelow(True)
    ax.set_title(f"Tempo of the {A['n']} tracks", loc="left", fontsize=11)
    save(fig, "stage4-tempo")


def stems():
    """Part three: the separated corpus."""
    S = json.load(open("corpus2/stems_summary.json")); R = json.load(open("corpus2/stems_results.json"))
    keep = {t["id"] for t in json.load(open("corpus2/summary.json"))["tracks"]}; R = [r for r in R if r["id"] in keep]
    has_bass = lambda r: r["levels"].get("bass", -99) > -18
    # 1 the pump three ways
    fig, ax = plt.subplots(figsize=(8, 3.8))
    data = [[r["pump_mix"] for r in R if r.get("pump_mix") is not None], [min(r["pump_bass"], 30) for r in R if has_bass(r) and r.get("pump_bass") is not None], [min(r["sidechain"], 30) for r in R if has_bass(r) and r.get("sidechain") is not None]]
    parts = ax.violinplot(data, showmedians=True, widths=0.8)
    for b in parts["bodies"]: b.set_facecolor(REAL); b.set_alpha(0.55); b.set_edgecolor(REAL)
    for k in ("cbars", "cmins", "cmaxes", "cmedians"): parts[k].set_color(INK); parts[k].set_linewidth(1)
    ax.set_xticks([1, 2, 3]); ax.set_xticklabels(["mix low band", "bass stem, on the beat", "bass stem, on kick onsets"])
    ax.set_ylabel("dip, dB (values above 30 drawn at 30)"); ax.grid(True, axis="y"); ax.set_axisbelow(True)
    ax.set_title(f"The pump three ways, {S['n_with_bass']} excerpts with an audible bass stem", loc="left", fontsize=11)
    save(fig, "stems-pump-three-ways")
    # 2 where real kicks land
    fig, ax = plt.subplots(figsize=(8, 3.2))
    kp = [r["kick_pitch_hz"] for r in R if r.get("kick_pitch_hz")]
    ax.hist(kp, bins=np.arange(35, 100, 2.5), color=REAL, linewidth=0, zorder=3, rwidth=0.92)
    ax.axvline(S["kick_pitch_hz"]["median"], color=INK, linewidth=1.2, linestyle="--"); ax.text(S["kick_pitch_hz"]["median"] + 0.6, ax.get_ylim()[1] * 0.9, f"median {S['kick_pitch_hz']['median']:.0f} Hz", fontsize=9)
    ax.set_xlabel("pitch 100 ms into the kick, Hz"); ax.set_ylabel("tracks"); ax.grid(True, axis="y"); ax.set_axisbelow(True)
    ax.set_title(f"Where the kick lands in {len(kp)} real tracks", loc="left", fontsize=11)
    save(fig, "stems-kick-pitch")
    # 3 corpus hits against the libraries, three measures for kick, hat, clap
    M = S["medians"]; libs = [("corpus", REAL), ("real_packs", THIRD), ("synth_v2", SYNTH), ("synth_v1", LINE)]
    fig, axes = plt.subplots(1, 3, figsize=(10, 3.4))
    for ax, k, lab, log in zip(axes, ["decay40_ms", "band_sub_share", "spectral_centroid_hz"], ["time to fall 40 dB, ms", "share below 60 Hz", "brightness, Hz"], [True, False, True]):
        jobs = ["kick", "hat", "clap"]; y = np.arange(len(jobs))
        for j, (lib, col) in enumerate(libs):
            xs = [M[lib][job][k] if M[lib][job][k] is not None else np.nan for job in jobs]
            ax.scatter([max(x, 0.01) if log else x for x in xs], y + (j - 1.5) * 0.15, color=col, s=40, zorder=3, label=lib.replace("_", " ") if ax is axes[0] else None)
        ax.set_yticks(y); ax.set_yticklabels(jobs); ax.invert_yaxis(); ax.set_xlabel(lab)
        if log: ax.set_xscale("log")
        ax.grid(True, axis="x"); ax.set_axisbelow(True)
    axes[0].legend(frameon=False, fontsize=8, loc="lower right")
    fig.suptitle("Real hits from the corpus against the three libraries", x=0.01, ha="left", fontsize=12)
    fig.tight_layout(); save(fig, "stems-libraries")


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which == "all": which = "programme"   # 'all' means the part-two set; stems is drawn on request
    for name, fn in [("stage1", stage1), ("stage3", stage3), ("stage4", stage4), ("stems", stems)]:
        if which in (name, "all"): fn(); print("drew", name)