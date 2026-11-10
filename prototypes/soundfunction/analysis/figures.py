"""The page's figures from the role hits and the sweeps.  python3 analysis/figures.py"""
import csv, math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

BG, PANEL, INK, DIM, LINE = "#0e1116", "#151a22", "#e6e9ef", "#9aa4b5", "#262d39"
ROLE_COLOR = {"kick": "#ff5470", "rumble": "#c07be0", "hat_closed": "#45e0e8", "hat_open": "#45e0e8", "perc": "#3fd8b0",
              "clap": "#ffd23f", "stab": "#ffa23f", "pad": "#58c7ff", "riser": "#a6f5bb", "impact": "#ff9f45"}
LABEL = {"hat_closed": "closed hat", "hat_open": "open hat", "perc": "perc hit"}
plt.rcParams.update({"figure.facecolor": BG, "axes.facecolor": PANEL, "axes.edgecolor": LINE, "axes.labelcolor": INK,
                     "xtick.color": DIM, "ytick.color": DIM, "text.color": INK, "font.size": 11, "font.family": "DejaVu Sans",
                     "axes.spines.top": False, "axes.spines.right": False, "grid.color": LINE, "grid.alpha": 0.6})

def f(r, k):
    try: return float(r[k])
    except: return float("nan")

def save(fig, name):
    for ext in ("png", "svg"):
        fig.savefig(f"out/plots/{name}.{ext}", dpi=160, bbox_inches="tight", facecolor=BG)
    plt.close(fig)

def role_map():
    rows = list(csv.DictReader(open("out/roles.csv")))
    fig, ax = plt.subplots(figsize=(8, 5.4))
    for r in rows:
        name = r["file"].split("/")[-1][:-4]
        x, y, c = max(f(r, "attack_ms"), 0.1), f(r, "decay40_ms"), f(r, "spectral_centroid_hz")
        size = 80 + 900 * min(1, c / 12000)
        ax.scatter(x, y, s=size, color=ROLE_COLOR.get(name, INK), alpha=0.85, edgecolor=BG, linewidth=1.2, zorder=3)
        ax.annotate(LABEL.get(name, name), (x, y), xytext=(8, 6), textcoords="offset points", fontsize=10, color=INK)
    ax.set_xscale("log"); ax.set_yscale("log")
    ax.set_xlabel("rise time, ms  (how fast it starts)"); ax.set_ylabel("time to fall 40 dB, ms  (how long it lasts)")
    ax.set_title("One clean hit per job. Dot size = brightness.", loc="left", fontsize=12, color=INK, pad=12)
    ax.grid(True, which="major"); ax.set_axisbelow(True)
    save(fig, "role-map")

def sweep(sound, param, feats, labels, title, name, xlabel):
    rows = sorted((r for r in csv.DictReader(open("out/hits.csv")) if r["sound"] == sound and r["param"] == param), key=lambda r: f(r, "value"))
    xs = [f(r, "value") for r in rows]
    fig, axes = plt.subplots(1, len(feats), figsize=(3.2 * len(feats), 3.4))
    if len(feats) == 1: axes = [axes]
    for ax, feat, lab in zip(axes, feats, labels):
        ys = [f(r, feat) for r in rows]
        ax.plot(xs, ys, "-o", color=ROLE_COLOR.get(sound, "#45e0e8"), linewidth=2, markersize=6)
        ax.set_title(lab, fontsize=10.5, color=INK, loc="left"); ax.set_xlabel(xlabel); ax.grid(True); ax.set_axisbelow(True)
    fig.suptitle(title, x=0.01, ha="left", fontsize=12, color=INK)
    fig.tight_layout()
    save(fig, name)

if __name__ == "__main__":
    role_map()
    sweep("kick", "pitch_end_hz", ["f0_hz_at_100ms", "band_sub_share", "band_low_share"],
          ["pitch measured at 100 ms, Hz", "share of energy 20–60 Hz", "share of energy 60–150 Hz"],
          "Kick: where the pitch lands decides sub weight", "sweep-kick-pitch", "pitch it lands on, Hz")
    sweep("kick", "amp_decay_ms", ["t60_estimate_ms", "crest_factor_db", "sustain_share"],
          ["ring-out time (T60), ms", "peak over average, dB", "share of energy after 50 ms"],
          "Kick: a longer tail trades punch for weight", "sweep-kick-decay", "decay setting, ms")
    sweep("kick", "drive", ["crest_factor_db", "rms_db", "spectral_centroid_hz"],
          ["peak over average, dB", "average level, dB", "brightness (centroid), Hz"],
          "Kick: drive flattens the peak and lifts the body", "sweep-kick-drive", "drive amount")
    sweep("kick", "click_level", ["band_high_share", "spectral_centroid_hz_100ms"],
          ["share of energy 2–6 kHz", "brightness in the first 100 ms, Hz"],
          "Kick: the click lives in the first 100 ms", "sweep-kick-click", "click level")
    sweep("hat", "decay_ms", ["decay20_ms", "decay40_ms", "sustain_share"],
          ["time to fall 20 dB, ms", "time to fall 40 dB, ms", "share of energy after 50 ms"],
          "Hat: closed and open are the same sound with different decay", "sweep-hat-decay", "decay setting, ms")
    sweep("hat", "highpass_hz", ["spectral_centroid_hz", "band_air_share"],
          ["brightness (centroid), Hz", "share of energy above 6 kHz"],
          "Hat: the high-pass sets how much air it has", "sweep-hat-highpass", "high-pass, Hz")
    sweep("clap", "bursts", ["attack_ms", "rise_10_90_ms", "spectral_flux_mean"],
          ["time to peak, ms", "10–90% rise, ms", "spectral change per frame"],
          "Clap: stacked bursts make the only slow-rising drum", "sweep-clap-bursts", "number of bursts")
    sweep("stab", "drive", ["crest_factor_db", "decay20_ms", "spectral_centroid_hz"],
          ["peak over average, dB", "time to fall 20 dB, ms", "brightness (centroid), Hz"],
          "Stab: drive turns a pluck into a held tone", "sweep-stab-drive", "drive amount")
    print("figures written to out/plots/")
