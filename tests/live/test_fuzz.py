"""Fuzz the commands the Zpkt agent runs: whatever the arguments and whatever Live answers, a command ends
with an exit code and a message, never a Python traceback, and a reset always ends with a report.

Seeded, so a failure repeats: `HANDS_FUZZ_SEED=7 HANDS_FUZZ_N=2000 pytest tests/test_fuzz.py`.
Live, AppleScript, sleeps and every subprocess are faked; nothing here touches the real rig.
"""

from __future__ import annotations

import json
import os
import random
import subprocess
import time
import traceback

import pytest
from typer.testing import CliRunner

from zpkt.live import live_cli, panel_cli, rig, ui
from zpkt.live.cli import app
from zpkt.live.transport import McpResult, Transport

SEED = int(os.environ.get("HANDS_FUZZ_SEED", "1"))
N = int(os.environ.get("HANDS_FUZZ_N", "250"))

WORDS = [
    "",
    " ",
    "x",
    "Kick bus",
    "bus-kick",
    "Operator",
    "panel x",
    "../../etc/passwd",
    "/tmp/x",
    "a" * 3000,
    "näme ",
    "\x00",
    "'; rm -rf /",
    '"',
    "{}",
    "null",
    "-1",
    "1e999",
    "NaN",
    "🎛",
    "Filter Freq",
    "600 Hz",
    "50%",
    "-inf dB",
    "A1",
    "H9",
    "C-9",
]


def junk(r: random.Random, depth: int = 0):
    """Any JSON value, weighted towards the shapes specs use."""
    k = r.randrange(12 if depth < 3 else 7)
    if k == 0:
        return None
    if k == 1:
        return r.choice([True, False])
    if k == 2:
        return r.choice([0, 1, -1, 17, 8, 2**40, -(2**40), 0.5, -0.0, 1e308, 1e-9])
    if k in (3, 4, 5, 6):
        return r.choice(WORDS)
    if k in (7, 8):
        return [junk(r, depth + 1) for _ in range(r.randrange(4))]
    return {r.choice(SPEC_KEYS + WORDS): junk(r, depth + 1) for _ in range(r.randrange(5))}


SPEC_KEYS = [
    "name",
    "instrument",
    "params",
    "notes",
    "chords",
    "rhythm",
    "beats",
    "tempo",
    "tail",
    "controls",
    "title",
    "sound",
    "seq",
    "every",
    "gate",
    "bars",
    "faders",
    "devices",
    "track",
    "device",
    "song",
    "sections",
    "parts",
    "pans",
    "from",
    "to",
    "steps",
    "values",
    "label",
    "param",
    "sends",
    "kind",
]

GOOD = {
    "make": [
        {
            "name": "p",
            "instrument": "Operator",
            "params": {"Filter Freq": "600 Hz"},
            "notes": [["A1", 0, 0.5, 110]],
            "beats": 4,
            "controls": ["Filter Freq"],
        },
        {"sound": "saw", "seq": "A B C D", "every": 4},
        {"name": "q", "sound": "pad", "chords": "Dm9,G7", "tempo": 100, "tail": 1},
    ],
    "mix": [
        {
            "name": "buses",
            "bars": [17, 8],
            "faders": ["bus-kick", "bus-hats"],
            "pans": ["bus-kick"],
            "devices": [
                {"track": "bus-kick", "device": "Saturator", "params": {"Drive": "6 dB"}, "controls": ["Drive"]}
            ],
        },
        {"name": "m2", "bars": [3, 2], "faders": ["bus-hats"]},
    ],
    "apply": [
        {"params": {"Filter Freq": "1 kHz"}, "seq": "A C E", "every": 0.5, "tempo": 120},
        {"controls": ["Filter Res", "Tone"], "title": "t"},
    ],
    "mixapply": [{"values": {"bus-kick": "-3 dB"}, "bars": [9, 4]}, {"values": {"bus_hats_volume": 0.5}}],
    "axes": [
        {"filter_freq": {"values": ["200 Hz", "2 kHz"]}, "osc_a_wave": {"steps": 2}},
        {"filter_freq": {"from": "200 Hz", "to": "2 kHz", "steps": 4}},
        {"bus-kick": {"values": ["-6 dB", "-3 dB", 0.85]}},
        {"bus_kick_volume": {"steps": 3}, "bus-hats": {"from": "-12 dB", "to": "0 dB", "steps": 2}},
    ],
    "state": [{"values": {"filter_freq": 0.4, "bus_kick_volume": 0.6}}, {"filter_freq": 0.2}],
    "song": [
        {
            "name": "s",
            "tempo": 124,
            "sections": [{"name": "intro", "bars": 8, "parts": ["p"]}, {"bars": 4, "parts": []}],
        }
    ],
}


NEAR = [
    0,
    1,
    -1,
    2,
    3,
    4,
    8,
    16,
    17,
    64,
    65,
    200,
    0.5,
    19,
    20,
    999,
    1000,
    1e9,
    "0",
    "4",
    "bus-kick",
    "bus-hats",
    "Bus-Kick",
    "kick",
    "mix",
    "Main",
    "Drive",
    "drive",
    "Filter Freq",
    "filter",
    "Volume",
    "3 dB",
    "-6 dB",
    "200 Hz",
    "40 kHz",
    "150 %",
    "Saw D",
    "saw",
    "pad",
    "Operator",
    "Saturator",
    "Reverb",
    "p",
    "buses",
    "A1",
    "C#3",
    "A B - C",
    "Dm9,G7",
    "whole",
    "0,0.75,1.5",
    True,
    False,
    None,
    [],
    {},
]


def mutate(node, r: random.Random):
    """Change one value somewhere inside: to a near miss most of the time, to junk otherwise."""
    if isinstance(node, dict) and node and r.random() < 0.8:
        k = r.choice(list(node))
        node[k] = mutate(node[k], r)
        return node
    if isinstance(node, list) and node and r.random() < 0.8:
        k = r.randrange(len(node))
        node[k] = mutate(node[k], r)
        if r.random() < 0.2:
            node.append(json.loads(json.dumps(node[k])))
        return node
    return r.choice(NEAR) if r.random() < 0.7 else junk(r)


def spec(r: random.Random, kind: str | None = None):
    """A good spec with a value or two broken (mostly), with a key that does not belong, or plain junk."""
    x = r.random()
    if x < 0.08:
        return junk(r)
    s = json.loads(json.dumps(r.choice(GOOD[kind if kind and r.random() < 0.85 else r.choice(list(GOOD))])))
    for _ in range(r.randrange(1, 3)):
        s = mutate(s, r)
    if isinstance(s, dict) and x < 0.2:
        s[r.choice(SPEC_KEYS)] = junk(r)
    if isinstance(s, dict) and s and x > 0.9:
        s.pop(r.choice(list(s)), None)
    return s


class Chaos(Transport):
    """A Live that answers anything: junk of any type, an error, or a lost reply."""

    def __init__(self, r: random.Random, *_a, **_k) -> None:
        self.r = r

    def execute(self, code: str) -> McpResult:
        k = self.r.randrange(10)
        if k == 0:
            return McpResult(status="error", error="Cannot reach Ableton: [Errno 61] Connection refused")
        if k == 1:
            return McpResult(
                status="error", error="Timed out after 12s", warning="Code may still be running on the main thread."
            )
        if k == 2:
            return McpResult(
                status="error",
                error="AttributeError: 'NoneType' object has no attribute 'devices'",
                traceback="Traceback ...",
            )
        return McpResult(status="ok", result=junk(self.r))

    def ping(self) -> float:
        return 0.01

    def close(self) -> None:
        pass


@pytest.fixture
def chaos(monkeypatch, tmp_path):
    r = random.Random(SEED)
    make = lambda *a, **k: Chaos(r)
    for mod in (panel_cli, live_cli):
        monkeypatch.setattr(mod, "LiveClient", make)
    monkeypatch.setattr(rig, "LiveClient", make)
    monkeypatch.setattr(time, "sleep", lambda s: None)

    def osa(*a, **k):
        if r.random() < 0.3:
            raise ui.UiError("osascript did not finish in 30 s")
        return r.choice(
            [
                "",
                "true",
                "false",
                "CLEAN",
                "OPEN | x",
                "HW002|AXStandardWindow\nSettings|AXStandardWindow",
                "x|AXDialog",
                "NONE",
                "Mac mini Speakers",
                "|",
            ]
        )

    monkeypatch.setattr(ui, "_osascript", lambda argv, timeout: osa())

    def run(argv, *a, **k):
        if r.random() < 0.1:
            raise subprocess.TimeoutExpired(argv, 1)
        return subprocess.CompletedProcess(argv, r.choice([0, 0, 1]), r.choice(["", "123\n", "junk"]), "")

    monkeypatch.setattr(subprocess, "run", run)
    monkeypatch.setattr(subprocess, "Popen", lambda *a, **k: None)
    monkeypatch.setattr(os, "kill", lambda *a: None)
    monkeypatch.chdir(tmp_path)
    return r


def clean(result, argv) -> None:
    exc = result.exception
    if exc is not None and not isinstance(exc, SystemExit):
        tb = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)[-6:])
        pytest.fail(f"traceback from: hands {' '.join(json.dumps(a) for a in argv)}\n{tb}")
    assert result.exit_code in (0, 1, 2), (argv, result.exit_code)
    assert "Traceback (most recent call last)" not in result.output, argv


def commands(r: random.Random) -> list[str]:
    j = lambda: json.dumps(spec(r))
    w = lambda: r.choice([*WORDS, "p", "buses", "s"])
    return r.choice(
        [
            lambda: ["panel", "make", "--spec", j(), *r.choice([[], ["--replace"], ["--force"]])],
            lambda: ["panel", "make", "--spec", r.choice(["", "{", "[1,2", "nul", '{"name": "x",}', w()])],
            lambda: ["panel", "apply", w(), "--spec", j()],
            lambda: ["panel", "apply", w(), "--state", j()],
            lambda: ["panel", "grid", w(), "--axes", j()],
            lambda: ["panel", "grid", w(), "--axes", j(), "--state", j()],
            lambda: ["panel", "pick", w(), str(r.choice([0, 1, -1, 99, 2**40])), w()],
            lambda: ["panel", "drop", w()],
            lambda: ["panel", "params", w(), "--grep", r.choice(["", "(", "[", "*", "filter", "a" * 500])],
            lambda: ["song", "make", "--spec", j()],
            lambda: ["song", "render", w()],
            lambda: ["song", "drop", w()],
            lambda: (
                [
                    "live",
                    "exec",
                    r.choice(
                        [
                            "",
                            " ",
                            "1",
                            "song.tempo",
                            "import song\nprint(song.tempo)",
                            "result = [",
                            "\x00",
                            "print(",
                            "song.tempo = 1",
                            "x = 'a' * 10**6\nresult = x",
                            w(),
                        ]
                    ),
                    *r.choice([[], ["--json"], ["--raw"]]),
                ]
            ),
            lambda: ["live", "check", *r.choice([[], ["--expect", w()], ["--any-set"]])],
            lambda: ["live", "ping"],
            lambda: ["rig", "check", *r.choice([[], ["--json"], ["--no-play"]])],
            lambda: (
                [
                    "rig",
                    "reset",
                    "--json",
                    *r.choice(
                        [[], ["--level", r.choice(["soft", "restart", "auto", "x"])], ["--set", w()], ["--discard"]]
                    ),
                ]
            ),
            lambda: ["sweep", *r.choice([[], ["--json"], ["--days", "-1"], ["--pressure"]])],
        ]
    )()


def test_no_command_ends_in_a_traceback(chaos, monkeypatch):
    runner = CliRunner()
    for write in (False, True):  # as the agent (read-only exec) and as a person
        monkeypatch.setenv("ZPKT_AGENT", "1") if write else monkeypatch.delenv("ZPKT_AGENT", raising=False)
        for _ in range(N):
            argv = commands(chaos)
            clean(runner.invoke(app, argv), argv)


def test_a_made_panel_survives_any_later_command(chaos, tmp_path):
    """Files left by earlier commands (a panel, a grid, a song; whole, cut short or junk) do not crash later ones."""
    runner = CliRunner()
    renders = tmp_path / "renders"
    renders.mkdir(exist_ok=True)
    for _ in range(N):
        for name in ("p", "buses", "s"):
            body = json.dumps(spec(chaos))
            for f in (renders / f"{name}.panel.json", renders / f"{name}.song.json", renders / f"panel-{name}.json"):
                f.write_text(body[: chaos.randrange(len(body) + 1)] if chaos.random() < 0.3 else body)
        argv = commands(chaos)
        clean(runner.invoke(app, argv), argv)


def test_a_reset_always_ends_with_a_report(chaos, tmp_path, monkeypatch):
    """Whatever Live, macOS and the disk do in the middle, `reset` returns a Report that says ok or what is wrong."""
    monkeypatch.setattr(rig, "_log", lambda: tmp_path / "Log.txt")
    clock = [0.0]
    monkeypatch.setattr(time, "monotonic", lambda: clock.__setitem__(0, clock[0] + 7) or clock[0])
    lines = [
        "info: Live App: Begin Init",
        "info: Audio In Out: Output Device: No Device",
        "info: Message Box: Audio is disabled.",
        "info: Message Box: Would you like to recover your work?",
        "info: Audio In Out: Output Device: Mac mini Speakers (0 In, 2 Out)",
        "\xff\xfe junk",
    ]
    for _ in range(N):
        (tmp_path / "Log.txt").write_text("\n".join(chaos.choice(lines) for _ in range(chaos.randrange(8))))
        als = tmp_path / "sets" / "HW002.als"
        als.write_text("x") if chaos.random() < 0.7 else als.unlink(missing_ok=True)
        report = rig.reset(
            set_path=chaos.choice([None, als, tmp_path / "gone.als"]),
            level=chaos.choice(["auto", "soft", "restart"]),
            keep=chaos.random() < 0.8,
        )
        assert isinstance(report.ok, bool) and isinstance(report.steps, list)
        assert report.ok or report.needs_you or (report.health or {}).get("problems"), report
        json.dumps(report.__dict__)


# ---------------------------------------------------------------- a Live that behaves: the spec is what is wrong


def snapshot(live) -> dict:
    s = live.song
    return {
        "tracks": [
            (
                t.name,
                [(d.name, [round(q.value, 6) for q in d.parameters]) for d in t.devices],
                len(t.arrangement_clips),
                bool(t.arm),
                round(t.mixer_device.volume.value, 6) if hasattr(t, "mixer_device") else None,
            )
            for t in s.tracks
        ],
        "tempo": s.tempo,
        "loop": s.loop,
        "start": s.start_time,
        "pos": s.current_song_time,
    }


def test_a_bad_spec_is_an_error_to_act_on_and_leaves_the_set_as_it_was(tmp_path, monkeypatch):
    """Against a Live that works, every failure is a PanelError or LiveError (never a TypeError the agent cannot
    read), and a command that failed changed nothing in the set."""
    from test_panel import bars_recorder, mix_live, recorder

    from zpkt.live import mix, panel, song, versions
    from zpkt.live.transport import LiveError

    monkeypatch.setattr(time, "sleep", lambda s: None)
    r = random.Random(SEED)
    kinds: dict[str, int] = {}
    reached: dict[str, int] = {}
    for k in range(N * 4):
        live, out = mix_live(), tmp_path / str(k % 50)
        live.song.create_audio_track = lambda i, live=live: live.song.tracks.append(
            __import__("test_panel").Track("Audio")
        )
        seen: list = []
        steps = [
            lambda: panel.make(
                live,
                {"name": "p", "instrument": "Operator", "notes": [["A1", 0, 0.5, 110]], "beats": 4},
                out,
                replace=True,
                recorder=recorder(seen),
            ),
            lambda: mix.make(
                live,
                {
                    "name": "buses",
                    "bars": [17, 4],
                    "faders": ["bus-kick", "bus-hats"],
                    "devices": [{"track": "bus-kick", "device": "Saturator", "params": {"Drive": "3 dB"}}],
                },
                out,
                replace=True,
                recorder=bars_recorder(seen),
            ),
        ]
        for step in steps:  # mostly with good panels already there
            if r.random() < 0.85:
                step()
        before = snapshot(live)

        def broken(*, transport, before, after, **_):
            from zpkt.live.agent import with_prelude

            transport.run(before + "\nresult = 'ok'")
            transport.run(with_prelude(after + "\nresult = 'ok'"))
            raise panel.PanelError("Live recorded nothing; check its audio output")

        rec_i, rec_m = (
            lambda seen, make=make: broken if r.random() < 0.15 else make(seen) for make in (recorder, bars_recorder)
        )
        rec = lambda mixed: rec_m(seen) if mixed else rec_i(seen)
        name, kind, fn = r.choice(
            [
                (
                    "panel.make",
                    "make",
                    lambda sp: panel.make(live, sp, out, replace=r.random() < 0.5, recorder=rec_i(seen)),
                ),
                (
                    "mix.make",
                    "mix",
                    lambda sp: (mix.make if mix.is_mix(sp) else panel.make)(
                        live, sp, out, replace=r.random() < 0.5, recorder=rec(mix.is_mix(sp))
                    ),
                ),
                (
                    "panel.apply",
                    "apply",
                    lambda sp: panel.apply(
                        live,
                        "p",
                        out,
                        spec=sp,
                        state_values=spec(r, "state") if r.random() < 0.3 else None,
                        recorder=rec_i(seen),
                    ),
                ),
                (
                    "panel.apply state",
                    "state",
                    lambda sp: panel.apply(live, "p", out, state_values=sp, recorder=rec_i(seen)),
                ),
                (
                    "mix.apply",
                    "mixapply",
                    lambda sp: mix.apply(
                        live,
                        versions.load(out, "buses"),
                        out,
                        spec=sp,
                        state_values=spec(r, "state") if r.random() < 0.3 else None,
                        recorder=rec_m(seen),
                    ),
                ),
                (
                    "grid",
                    "axes",
                    lambda sp: versions.grid(
                        live,
                        r.choice(["p", "buses"]),
                        out,
                        sp,
                        state_values=spec(r, "state") if r.random() < 0.3 else None,
                        recorder=rec_m(seen),
                    ),
                ),
                (
                    "pick",
                    "state",
                    lambda sp: versions.pick(
                        live, r.choice(["p", "buses"]), out, r.choice([1, 2, junk(r)]), r.choice(["A", "b", junk(r)])
                    ),
                ),
                ("song.make", "song", lambda sp: song.make(live, sp, out, recorder=rec_i(seen))),
            ]
        )
        sp = spec(r, kind)
        call = (name, lambda: fn(sp))
        try:
            call[1]()
            reached[call[0] + " ok"] = reached.get(call[0] + " ok", 0) + 1
        except (panel.PanelError, LiveError) as exc:
            assert snapshot(live) == before, f"{call[0]} failed ({exc}) and left the set changed, spec {json.dumps(sp)}"
            reached[call[0] + " error"] = reached.get(call[0] + " error", 0) + 1
        except Exception as exc:
            where = traceback.extract_tb(exc.__traceback__)[-1]
            kinds.setdefault(
                f"{call[0]}: {type(exc).__name__}: {str(exc)[:70]} at {os.path.basename(where.filename)}:{where.lineno} | {json.dumps(sp)[:200]}",
                0,
            )
    assert not kinds, f"{len(kinds)} crash(es) on bad specs:\n" + "\n".join(sorted(kinds)[:40])
    for name in (
        "panel.make",
        "mix.make",
        "panel.apply",
        "mix.apply",
        "grid",
        "song.make",
    ):  # the fuzz is not all refusals
        assert reached.get(name + " ok") and reached.get(name + " error"), reached
