"""Small made-up data in the shapes the arranger's files have (loops.json, fx.json, an arrangement), and a stand-in
for hands' LiveOps that records every step and answers from a tiny model of the mix set. Nothing here is real data."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

GOLDEN = Path(__file__).resolve().parent / "golden"

LOOPS = {
    "set": "HW002_121_full.als",
    "bpm": 160,
    "rate": 44100,
    "barSeconds": 1.5,
    "lanes": [
        {"id": "kick", "title": "Kick", "group": "kick", "color": "#ff6b5e"},
        {"id": "p1-oh", "title": "P1 open", "group": "hats", "color": "#ffe27a"},
        {"id": "splash", "title": "Splash", "group": "sfx", "color": "#62c8f2"},
        {"id": "chord", "title": "Chord", "group": "sfx", "color": "#8aa4ff"},
        {"id": "break-horn", "title": "Brk horn", "group": "break", "color": "#d9a3ff"},
    ],
    "clips": [
        {
            "id": "kick-rumble-a",
            "lane": "kick",
            "title": "Kick + rumble A",
            "kind": "loop",
            "bars": 4,
            "fileBars": 4,
            "file": "0000000000000001.flac",
        },
        {
            "id": "p1-oh-b",
            "lane": "p1-oh",
            "title": "P1 open hat B",
            "kind": "loop",
            "bars": 1,
            "fileBars": 1,
            "file": "0000000000000002.flac",
        },
        {
            "id": "splash-d",
            "lane": "splash",
            "title": "Splash D",
            "kind": "once",
            "bars": 2,
            "fileBars": 3,
            "file": "0000000000000003.flac",
        },
        {
            "id": "chord-a",
            "lane": "chord",
            "title": "Chord A",
            "kind": "loop",
            "bars": 8,
            "fileBars": 8,
            "file": "0000000000000004.flac",
            "tail": "0000000000000005.flac",
            "tailBars": 2,
        },
    ],
}

FX = {
    "set": "HW002_121_pp_fxa",
    "candidates": [
        {"id": "nr-lp-2", "kind": "riser", "file": "nr-lp-2.flac", "mode": "add", "lane": ""},
        {"id": "sc-hp-1bar", "kind": "scoop", "file": "sc-hp-1bar.flac", "mode": "replace", "lane": "kick"},
    ],
}

ARRANGEMENT = {
    "name": "8d2a2 Fast build, slow peak",
    "bars": 40,
    "regions": [
        {"lane": "splash", "clip": "splash-d", "start": 16, "len": 4, "off": 0},
        {"lane": "p1-oh", "clip": "p1-oh-b", "start": 4, "len": 36, "off": 0},
        {"lane": "kick", "clip": "kick-rumble-a", "start": 16, "len": 24, "off": 0},
        {"lane": "chord", "clip": "chord-a", "start": 16, "len": 16, "off": 0},
    ],
    "mutes": [],
    "saved": 1.0,
    "transitions": [
        {
            "id": "nr-lp-2",
            "seam": 17,
            "kind": "riser",
            "mode": "add",
            "lane": "",
            "startBeat": 56.0,
            "beats": 8.0,
            "gainDb": -3.0,
        },
        {
            "id": "sc-hp-1bar",
            "seam": 25,
            "kind": "scoop",
            "mode": "replace",
            "lane": "kick",
            "startBeat": 80.0,
            "beats": 16.0,
        },
    ],
    "mix": {
        "channels": {
            "kick": {
                "gainDb": -1.5,
                "pan": 0.0,
                "eq": {
                    "hp": {"on": True, "freq": 30},
                    "cuts": [
                        {"on": True, "freq": 320, "gainDb": -3.0, "q": 1.4},
                        {"on": False, "freq": 900, "gainDb": -2, "q": 1},
                    ],
                },
            },
            "chord": {"gainDb": -4.0, "pan": 0.1, "eq": {"lp": {"on": True, "freq": 9000}, "cuts": []}},
            "fx-riser": {"gainDb": 2.0, "pan": -0.2},
        }
    },
    "mix2": [{"target": "bus-kick", "device": "Saturator", "values": {"Drive": "6.0 dB"}}],
    "spectral": [
        {
            "id": "a",
            "parts": [
                {"target": "chord", "device": "gain", "values": {"dB": -1.0}},
                {"target": "main", "device": "EQ Eight", "values": {"1 Gain A": "1.0 dB"}},
            ],
        }
    ],
    "kickFuzz": {"id": "mf1", "loop": "solo-mf1.flac", "kickTurnedDb": 0.5, "bells": [[40.0, 8.0, 0.7]]},
    "desk": {"monitor": ["mon C1"]},
}


def write_data(data: Path) -> Path:
    """A data folder with loops.json, fx/fx.json and arrangements/short-8d2a2.json."""
    (data / "fx").mkdir(parents=True, exist_ok=True)
    (data / "arrangements").mkdir(parents=True, exist_ok=True)
    (data / "loops.json").write_text(json.dumps(LOOPS))
    (data / "fx" / "fx.json").write_text(json.dumps(FX))
    (data / "arrangements" / "short-8d2a2.json").write_text(json.dumps(ARRANGEMENT))
    return data


def relative(obj: Any, root: Path) -> Any:
    """`obj` with every mention of `root` replaced by DATA, so a golden does not depend on the temporary folder."""
    return json.loads(json.dumps(obj).replace(str(root), "DATA"))


def assert_golden(name: str, got: Any) -> None:
    """Compare with tests/golden/<name>.json; ARRANGER_GOLDEN=write writes it (only when pinning new behaviour)."""
    f = GOLDEN / f"{name}.json"
    got = json.loads(json.dumps(got))
    if os.environ.get("ARRANGER_GOLDEN") == "write":
        f.parent.mkdir(exist_ok=True)
        f.write_text(json.dumps(got, indent=1) + "\n")
    assert got == json.loads(f.read_text()), f"{name} differs from its golden"


class RecordingLive:
    """Stands in for hands.live.ops.LiveOps: records each step, answers LOM calls from a small model of the set
    (track names, device lists, clip starts). The calls themselves are what the tests pin."""

    def __init__(self, tracks: list[str] | None = None, front: str = "HW002_121_pp_mix") -> None:
        self.calls: list[list[Any]] = []
        self.tracks = list(tracks or ["1-Audio", "2-Audio"])
        self.front = front
        self.devices_on: dict[str, list[str]] = {}
        self.clip_starts = [64.0, 80.0, 96.0]

    def guard(self, where: str) -> str:
        self.calls.append(["guard", where])
        return self.front

    def run(self, code: str) -> Any:
        self.calls.append(["run", code])
        if code == "result = [t.name for t in song.tracks]":
            return list(self.tracks)
        if m := re.search(r"create_audio_track\(-1\)\nt\.name = '([^']*)'", code):
            self.tracks.append(m[1])
        if m := re.fullmatch(r"for _ in range\((\d+)\):\n    song.delete_track\(0\)\nresult = 'ok'", code):
            del self.tracks[: int(m[1])]
        if "available_input_routing_types" in code:
            return ["No Input", 0]
        if m := re.search(r"x.display_name == '([^']*)'\]\nif r:", code):
            return m[1]
        if "c.gain_display_string" in code:
            return "-3.0 dB"
        if code.startswith("result = [d.class_name for d in song.master_track.devices]"):
            return ["StereoGain"]
        if "arrangement_clips]" in code and code.startswith("result = [c.start_time"):
            return list(self.clip_starts)
        if code.startswith("out = []"):
            return [4.0] * code.count("create_audio_clip")
        return "ok"

    def setp(self, device: str, params: dict[str, Any]) -> None:
        self.calls.append(["setp", device, params])

    def mixer(self, track: str, vol_db: float | None = None, sends: tuple = (), pan: float | None = None) -> None:
        self.calls.append(["mixer", track, vol_db, list(sends), pan])

    def load_item(self, track: str, root: str, folder: str | None, name: str) -> None:
        self.calls.append(["load_item", track, root, folder, name])
        self.devices_on.setdefault(track, []).append(name)

    def devices(self, track: str) -> list[str]:
        self.calls.append(["devices", track])
        return list(self.devices_on.get(track, []))

    def export(
        self, out: Path, start_beat: float, length_beats: float, *, bits: int = 24, timeout_s: float = 300
    ) -> Path:
        self.calls.append(["export", out.name, start_beat, length_beats, bits, timeout_s])
        out.write_bytes(b"wav")
        return out
