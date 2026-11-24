"""zpkt.live.state offline: comparing, recipe import, and `put` against a small fake Live."""

from __future__ import annotations

import copy
import json
import re

from zpkt.live import state as S
from zpkt.live.transport import McpResult, Transport


def _track(vol: float, devices: dict | None = None, mute: bool = False) -> dict:
    return {
        "mixer": {
            "volume": [f"{vol} dB", vol],
            "pan": ["C", 0.0],
            "sends": {"A-Space": ["-inf dB", "0.0"]},
            "mute": [str(mute), mute],
            "solo": ["False", False],
        },
        "devices": [
            {"name": n, "class": "X", "params": {p: [str(v), v] for p, v in ps.items()}}
            for n, ps in (devices or {}).items()
        ],
    }


def _state(**kw) -> dict:
    return {
        "returns": ["A-Space"],
        "tracks": {
            "kick": _track(0.85, {"desk EQ": {"Gain": 0.5, "Freq": 0.2}}),
            "A-Space": _track(1.0, {"Reverb": {"Decay": 0.3}}),
            "Main": _track(0.85, {"desk Glue": {"Threshold": 0.4}}),
            **kw,
        },
    }


def test_same_state_has_no_diff():
    a = S.load_dict(_state())
    assert S.diff(a, copy.deepcopy(a)) == []
    assert S.summarize([]) == "same"


def test_diff_names_the_value_and_collapses_one_sided_tracks():
    a, b = _state(), _state()
    b["tracks"]["kick"]["devices"][0]["params"]["Gain"] = ["3 dB", 0.6]
    b["tracks"]["mon A"] = _track(0.7)
    rows = S.diff(S.load_dict(a), S.load_dict(b))
    assert ("kick/desk EQ/Gain", "0.5", "3 dB") in rows
    text = S.summarize(rows)
    assert "kick/desk EQ/Gain: 0.5 -> 3 dB" in text
    assert "mon A/* only in B" in text
    assert S.diff(S.load_dict(a), S.load_dict(b), ignore=("mon ",)) == [("kick/desk EQ/Gain", "0.5", "3 dB")]


def test_return_letters_do_not_matter():
    a = _state()
    desk = {
        "returns": [{"name": "Space", "devices": [{"name": "Reverb", "values": {"Decay": ["0.3", 0.3]}}]}],
        "chains": {"kick": [{"name": "desk EQ", "values": {"Gain": ["0.5", 0.5]}}]},
        "mixer": {
            "kick": {
                "volume": ["0.85 dB", 0.85],
                "pan": ["C", 0.0],
                "sends": {"Space": ["-inf dB", 0.0]},
                "mute": False,
            }
        },
    }
    rec = S.from_desk(desk)
    assert rec["partial"]
    assert S.diff(rec, S.load_dict(a)) == []  # a partial state is judged on its own keys only


def test_text_values_from_the_bridge_become_numbers():
    raw = _state()
    raw["tracks"]["kick"]["devices"][0]["params"]["Gain"] = "['3 dB', 0.6]"  # a whole pair as text, deep in a reply
    st = S.load_dict(raw)
    assert st["tracks"]["kick"]["mixer"]["sends"]["A-Space"][1] == 0.0
    assert st["tracks"]["kick"]["devices"][0]["params"]["Gain"] == ["3 dB", 0.6]


class FakeLive(Transport):
    """Holds a state; answers take()'s reads from it and applies put()'s writes to it."""

    def __init__(self, st: dict) -> None:
        self.st = copy.deepcopy(st)
        self.writes: list[str] = []

    def _find(self, code: str) -> str:
        m = re.search(r"t\.name == '([^']+)'", code)
        if "song.master_track" in code:
            return "Main"
        name = m.group(1)
        return name if name in self.st["tracks"] else next(n for n in self.st["tracks"] if n[2:] == name)

    def execute(self, code: str) -> McpResult:
        if code.startswith("result = [t.name for t in list(song.tracks)"):
            return McpResult(status="ok", result=list(self.st["tracks"]))
        if code.startswith("result = [r.name for r in song.return_tracks]"):
            return McpResult(status="ok", result=self.st["returns"])
        if "def _one(t, is_track)" in code:
            names = eval(code[code.rindex(" for n in ") + 10 : code.rindex("}")])
            return McpResult(status="ok", result={n: json.loads(json.dumps(self.st["tracks"][n])) for n in names})
        self.writes.append(code)
        t = self.st["tracks"][self._find(code)]
        if "ps = {p.name: p" in code:
            k = int(re.search(r"\.devices\[(\d+)\]", code).group(1))
            for n, v in eval(re.search(r"for n, v in (\[.*\]):", code).group(1)):
                t["devices"][k]["params"][n] = [str(v), v]
        for v in re.findall(r"m\.volume\.value = ([\d.]+)", code):
            t["mixer"]["volume"] = [v, float(v)]
        return McpResult(status="ok", result="ok")


def test_put_writes_only_what_differs_and_reads_back():
    want = S.load_dict(_state())
    live = FakeLive(_state())
    live.st["tracks"]["kick"]["devices"][0]["params"]["Gain"] = ["0.9", 0.9]
    live.st["tracks"]["Main"]["mixer"]["volume"] = ["0.1", 0.1]
    assert S.put(live, want) == []
    assert len(live.writes) == 2  # one device chunk, one mixer line
    assert "'Freq'" not in live.writes[0]  # unchanged values are not written
    assert live.st["tracks"]["kick"]["devices"][0]["params"]["Gain"][1] == 0.5


def test_put_reports_what_the_set_lacks():
    want = S.load_dict(_state())
    want["tracks"]["kick"]["devices"].append({"name": "desk Sat", "class": "X", "params": {"Drive": ["0", 0.0]}})
    rows = S.put(FakeLive(_state()), want)
    assert ("kick/desk Sat", "device", None) in rows


def test_live_open_command_calls_open_set(monkeypatch):
    from typer.testing import CliRunner

    from zpkt.live.cli import app
    from zpkt.live import session

    seen = {}
    monkeypatch.setattr(
        session, "open_set", lambda client, name, save_current=True: seen.update(name=name, save=save_current) or 3.2
    )
    res = CliRunner().invoke(app, ["live", "open", "HW_x.als", "--no-save"])
    assert res.exit_code == 0 and "opened HW_x.als in 3.2 s" in res.output
    assert seen == {"name": "HW_x", "save": False}
