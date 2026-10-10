"""Real project data for the reel: render envelopes, commits, counts.

Writes out/assets.js (window.ASSETS). Everything shown on screen as a fact
comes from here or from a file cited in reel.html.
"""
import json
import pathlib
import subprocess

import numpy as np

ROOT = pathlib.Path(__file__).resolve().parents[2]  # zpkt/
OUT = ROOT / "demo/out"
VERSIONS = pathlib.Path.home() / "_agent_scratch/renders/versions"
SR = 8000
POINTS = 96

# The arrangement experiments shown in the factory montage, in screen order.
PICKS = [
    "b3-01-postdrop-climb-30s", "b42-01-wuh-on-the-bar-48s", "b4-09-climb-scoop-peak-48s",
    "b41-09-t1-splash-8-beats-42s", "b3-08-two-step-18s", "b42-03-wuh-then-16th-chops-48s",
    "v09-ksms-shape-60s", "b4-07-break-beatbox-x2-scoop-48s", "b3-06-break-then-climb-30s",
    "b42-05-long-wuh-then-chops-48s", "b4-01-long-scoop-four-steps-42s", "v10-hedon-shape-60s",
    "b41-02-t1-scoop8-hats-climb-42s", "b3-10-mini-arc-33s", "b4-08-peak-break-return-48s",
    "b42-09-t1-splash-8-and-3-42s",
]


def envelope(path: pathlib.Path) -> list[float]:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "f32le", "-ac", "1", "-ar", str(SR), "-"],
        check=True, capture_output=True,
    ).stdout
    x = np.frombuffer(raw, dtype=np.float32)
    chunks = np.array_split(x, POINTS)
    env = np.array([np.sqrt(np.mean(c ** 2)) for c in chunks])
    return [round(float(v), 3) for v in env / (env.max() + 1e-9)]


def git(*args: str) -> str:
    return subprocess.run(["git", "-C", str(ROOT), *args], check=True, capture_output=True,
                          text=True).stdout


def main() -> None:
    mp3s = sorted(VERSIONS.glob("*.mp3"))
    renders = []
    for name in PICKS:
        path = next(p for p in mp3s if p.stem.endswith(name))
        renders.append({"name": name, "env": envelope(path)})

    log = [line.split("\t", 2) for line in git("log", "--format=%h\t%an\t%s").splitlines()]
    authors = [a for _, a, _ in log]
    first = git("log", "--reverse", "--format=%ad", "--date=short").splitlines()[0]
    data = {
        "renders": renders,
        "commits": [{"h": h, "a": a, "s": s} for h, a, s in log[:60]],
        "stats": {
            "commits": len(log),
            "claude_commits": authors.count("Claude"),
            "renders": len(mp3s),
            "versions": len({p.stem.removesuffix("-r3") for p in mp3s}),
            "first_commit": first,
        },
    }
    OUT.mkdir(exist_ok=True)
    (OUT / "assets.js").write_text("window.ASSETS = " + json.dumps(data, separators=(",", ":")) + ";\n")
    print(json.dumps(data["stats"]), len(renders), "envelopes")


if __name__ == "__main__":
    main()
