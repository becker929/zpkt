"""Plotting helpers. Matplotlib is optional at the OS level; this module needs it.

If it's missing: `pip install matplotlib` (no other new dependency is required).
"""
from __future__ import annotations

import csv
import json
import sys
from collections import defaultdict
from pathlib import Path

import numpy as np

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
except ImportError:
    print("plots.py needs matplotlib: `pip install matplotlib`", file=sys.stderr)
    raise

BG = "#0b0b0d"
FG = "#e6e6e6"
MUTED = "#6b6b70"
BAND_ORDER = ["sub", "low", "lowmid", "mid", "high", "air"]
BAND_COLORS = {
    "sub": "#6ee7ff", "low": "#7c9bff", "lowmid": "#b28dff",
    "mid": "#ff8dc7", "high": "#ffb86b", "air": "#ffe66b",
}


def _dark_axes(ax):
    ax.set_facecolor(BG)
    for spine in ax.spines.values():
        spine.set_color(MUTED)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors=FG, labelsize=8)
    ax.xaxis.label.set_color(FG)
    ax.yaxis.label.set_color(FG)
    ax.title.set_color(FG)
    ax.grid(False)


def _new_fig(nrows=1, ncols=1, figsize=(7, 4), **kw):
    fig, axes = plt.subplots(nrows, ncols, figsize=figsize, facecolor=BG, **kw)
    for ax in np.atleast_1d(axes).ravel():
        _dark_axes(ax)
    return fig, axes


def _save(fig, out_dir, name):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    paths = []
    for ext in ("png", "svg"):
        p = out_dir / f"{name}.{ext}"
        fig.savefig(p, facecolor=BG, dpi=150 if ext == "png" else None)
        paths.append(str(p))
    plt.close(fig)
    return paths


def plot_sweep(csv_path, sound, param, features, out_dir="out/plots"):
    """Line plots of `features` vs the swept parameter value, for one sound/param."""
    rows = []
    with open(csv_path, newline="") as fh:
        for r in csv.DictReader(fh):
            if r.get("sound") == sound and r.get("param") == param:
                rows.append(r)
    if not rows:
        raise ValueError(f"no rows for sound={sound!r} param={param!r} in {csv_path}")

    def to_val(s):
        try:
            return float(s)
        except (TypeError, ValueError):
            return s

    rows.sort(key=lambda r: to_val(r["value"]))
    xs = [to_val(r["value"]) for r in rows]

    fig, axes = _new_fig(len(features), 1, figsize=(6, 2.2 * len(features)), sharex=True)
    axes = np.atleast_1d(axes)
    for ax, feat in zip(axes, features):
        ys = [float(r[feat]) if r.get(feat) not in (None, "") else float("nan") for r in rows]
        ax.plot(xs, ys, "-o", color="#7c9bff", ms=4, lw=1.5)
        ax.set_ylabel(feat, fontsize=8)
    axes[-1].set_xlabel(param)
    fig.suptitle(f"{sound} — {param} sweep", color=FG, fontsize=10)
    fig.tight_layout()
    return _save(fig, out_dir, f"{sound}__{param}__sweep")


def plot_bar_profile(track_json_entry, out_dir="out/plots"):
    """6-band x 16-step heatmap of where each band hits within the bar."""
    entry = track_json_entry
    bands = entry.get("bar_matrix_bands_order", BAND_ORDER)
    mat = np.array([entry["bands"][b]["bar_profile_16step"] for b in bands])

    fig, ax = _new_fig(figsize=(6, 3))
    im = ax.imshow(mat, aspect="auto", cmap="magma", interpolation="nearest")
    ax.set_yticks(range(len(bands)))
    ax.set_yticklabels(bands)
    ax.set_xticks(range(16))
    ax.set_xlabel("16th-note step in bar")
    ax.set_title(Path(entry.get("file", "track")).stem)
    cbar = fig.colorbar(im, ax=ax, fraction=0.03)
    cbar.ax.yaxis.set_tick_params(color=FG)
    plt.setp(cbar.ax.get_yticklabels(), color=FG)
    fig.tight_layout()
    name = Path(entry.get("file", "track")).stem + "__barprofile"
    return _save(fig, out_dir, name)


def plot_track_bands(bars_npy, boundaries=None, breakdown=None, drop_bar=None,
                      band_names=None, name="track", out_dir="out/plots"):
    """Per-band energy across bars, with segment boundaries + candidate breakdown/drop."""
    mat = np.load(bars_npy) if isinstance(bars_npy, (str, Path)) else np.asarray(bars_npy)
    bands = band_names or BAND_ORDER[: mat.shape[0]]
    bars = np.arange(mat.shape[1])

    fig, ax = _new_fig(figsize=(8, 3.2))
    for i, b in enumerate(bands):
        row = mat[i]
        row = row / (row.max() + 1e-12)
        ax.plot(bars, row, color=BAND_COLORS.get(b, "#ffffff"), lw=1.4, label=b)

    if breakdown:
        ax.axvspan(breakdown["start_bar"], breakdown["end_bar"], color="#ffffff", alpha=0.08)
    if boundaries:
        for bnd in boundaries:
            ax.axvline(bnd, color=MUTED, lw=0.7, ls="--")
    if drop_bar is not None:
        ax.axvline(drop_bar, color="#ff5566", lw=1.5)

    ax.set_xlabel("bar")
    ax.set_ylabel("normalised band energy")
    ax.set_title(name)
    ax.legend(loc="upper right", fontsize=7, facecolor=BG, labelcolor=FG, framealpha=0.3)
    fig.tight_layout()
    return _save(fig, out_dir, f"{name}__bands")


DEFAULT_SWEEP_FEATURES = [
    "duration_s", "attack_ms", "decay_ms", "rms_db",
    "spectral_centroid_hz", "spectral_flatness", "harmonic_percussive_ratio",
    "band_sub_share", "band_high_share",
]


def main(hits_csv="out/hits.csv", tracks_json="out/tracks.json", out_dir="out/plots"):
    """Regenerate every plot this pipeline knows how to make, from CLI output files."""
    if Path(hits_csv).exists():
        groups = defaultdict(list)
        with open(hits_csv, newline="") as fh:
            for r in csv.DictReader(fh):
                if r.get("sound") and r.get("param"):
                    groups[(r["sound"], r["param"])].append(r)
        for (sound, param), rows in groups.items():
            feats = [f for f in DEFAULT_SWEEP_FEATURES if f in rows[0]]
            try:
                plot_sweep(hits_csv, sound, param, feats, out_dir=out_dir)
                print(f"[plots] sweep {sound}/{param}", file=sys.stderr)
            except Exception as e:
                print(f"[plots] FAILED sweep {sound}/{param}: {e}", file=sys.stderr)
    else:
        print(f"[plots] no {hits_csv}, skipping sweep plots", file=sys.stderr)

    if Path(tracks_json).exists():
        entries = json.load(open(tracks_json))
        for entry in entries:
            name = Path(entry.get("file", "track")).stem
            try:
                plot_bar_profile(entry, out_dir=out_dir)
                npy = entry.get("bar_matrix_npy")
                mat = npy if npy and Path(npy).exists() else np.array(entry["bar_matrix"])
                plot_track_bands(
                    mat,
                    boundaries=[s["start_bar"] for s in entry.get("segments", [])],
                    breakdown=entry.get("candidate_breakdown"),
                    drop_bar=entry.get("candidate_drop_bar"),
                    band_names=entry.get("bar_matrix_bands_order"),
                    name=name, out_dir=out_dir,
                )
                print(f"[plots] track {name}", file=sys.stderr)
            except Exception as e:
                print(f"[plots] FAILED track {name}: {e}", file=sys.stderr)
    else:
        print(f"[plots] no {tracks_json}, skipping track plots", file=sys.stderr)


if __name__ == "__main__":
    main()
