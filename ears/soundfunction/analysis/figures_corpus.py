"""Corpus figures from out/grid.json.  python3 analysis/figures_corpus.py"""
import json, numpy as np, matplotlib
matplotlib.use("Agg"); import matplotlib.pyplot as plt
from matplotlib.colors import LinearSegmentedColormap
BG, PANEL, INK, DIM, LINE = "#0e1116", "#151a22", "#e6e9ef", "#9aa4b5", "#262d39"
plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": PANEL, "axes.edgecolor": LINE, "axes.labelcolor": INK,
                     "xtick.color": DIM, "ytick.color": DIM, "text.color": INK, "font.size": 11, "axes.spines.top": False, "axes.spines.right": False})
g = json.load(open("out/grid.json"))
bands = ["sub", "low", "low-mid", "mid", "high", "air"]
cmap = LinearSegmentedColormap.from_list("bw", ["#151a22", "#1f4d6b", "#45e0e8", "#ffd23f"])
def save(fig, name):
    for ext in ("png", "svg"): fig.savefig(f"out/plots/{name}.{ext}", dpi=160, bbox_inches="tight", facecolor=BG)
    plt.close(fig)

# 1. where attacks and energy sit in the bar, averaged over the corpus
fig, axes = plt.subplots(1, 2, figsize=(10, 3.9))
for ax, key, title in zip(axes, ("profile_attack", "profile_energy"), ("Where the ATTACKS land", "Where the ENERGY sits")):
    P = np.array([t[key] for t in g]); P = P / P.sum(2, keepdims=True); M = P.mean(0)
    M = M / M.sum(1, keepdims=True) * 16          # 1.0 = uniform
    im = ax.imshow(M, aspect="auto", cmap=cmap, vmin=0.4, vmax=2.2)
    ax.set_yticks(range(6)); ax.set_yticklabels(bands)
    ax.set_xticks(range(16)); ax.set_xticklabels([("1" if i == 0 else "2" if i == 4 else "3" if i == 8 else "4" if i == 12 else "+" if i % 2 == 0 else "·") for i in range(16)])
    for x in (4, 8, 12): ax.axvline(x - 0.5, color=BG, linewidth=1.2)
    ax.set_title(title, loc="left", fontsize=11.5, color=INK); ax.set_xlabel("step in the bar (1 2 3 4 = beats, + = offbeats)")
cb = fig.colorbar(im, ax=axes, fraction=0.025, pad=0.02); cb.set_label("× the even share", color=DIM); cb.ax.yaxis.set_tick_params(color=DIM)
fig.suptitle("26 tracks, folded onto one bar. Sub attacks mark the beats; sub energy swells between them.", x=0.01, ha="left", fontsize=12)
save(fig, "corpus-bar-grid")

# 2. band energy over bars for two tracks, kick-off runs shaded
picks = sorted(range(len(g)), key=lambda i: -len(g[i]["returns"]))[:2]
fig, axes = plt.subplots(len(picks), 1, figsize=(10, 2.6 * len(picks)), sharex=False)
for ax, i in zip(np.atleast_1d(axes), picks):
    t = g[i]; M = np.array(t["bar_matrix"]); M = M / (M.max(1, keepdims=True) + 1e-12)
    nb = M.shape[1]
    for s, e in t["kick_off_runs"]: ax.axvspan(s, e, color="#ff5470", alpha=0.13, linewidth=0)
    for row, col, lab in ((1, "#ff5470", "low (kick body)"), (5, "#45e0e8", "air (hats)"), (3, "#ffd23f", "mid")):
        ax.plot(np.arange(nb) + 0.5, M[row], color=col, linewidth=1.4, label=lab)
    name = t["file"].split("/")[-1][3:-4].replace("-", " ")
    ax.set_title(f"{name} · {t['tempo']:.1f} BPM · {nb} bars · shaded = kick off", loc="left", fontsize=10.5, color=INK)
    ax.set_ylabel("level"); ax.set_yticks([]); ax.set_xlim(0, nb); ax.grid(True, axis="x", color=LINE, alpha=0.5)
    for x in range(0, nb, 16): ax.axvline(x, color=LINE, linewidth=0.6)
np.atleast_1d(axes)[-1].set_xlabel("bar"); np.atleast_1d(axes)[0].legend(loc="upper right", fontsize=9, frameon=False)
fig.tight_layout(); save(fig, "corpus-two-tracks")

# 3. lock quality and kick-off structure, one small panel each
fig, axes = plt.subplots(1, 3, figsize=(10, 3.2))
locks = sorted(t["lock"] for t in g)
axes[0].bar(range(len(locks)), locks, color="#45e0e8"); axes[0].axhline(0.25, color="#ffd23f", linestyle="--", linewidth=1)
axes[0].set_title("Sub attacks on the beats, per track", loc="left", fontsize=10.5); axes[0].set_xticks([]); axes[0].set_ylabel("share on beat bins"); axes[0].text(0.3, 0.26, "chance", color="#ffd23f", fontsize=9)
longest = sorted(t["longest_off_bars"] for t in g)
axes[1].bar(range(len(longest)), longest, color="#ff5470"); axes[1].set_title("Longest kick-off run, per track", loc="left", fontsize=10.5); axes[1].set_xticks([]); axes[1].set_ylabel("bars")
for y in (8, 16, 24, 32): axes[1].axhline(y, color=LINE, linewidth=0.6)
runs = [e - s for t in g for s, e in t["kick_off_runs"] if e - s >= 4]
axes[2].hist(runs, bins=np.arange(3.5, 45.5, 1), color="#c07be0"); axes[2].set_title("All kick-off runs of 4+ bars", loc="left", fontsize=10.5); axes[2].set_xlabel("bars"); axes[2].set_ylabel("count")
for x in (8, 16, 24, 32): axes[2].axvline(x, color="#ffd23f", linewidth=0.8, alpha=0.7)
fig.tight_layout(); save(fig, "corpus-structure")
print("wrote corpus figures; two-track picks:", [g[i]["file"].split("/")[-1] for i in picks])
