"""The Options service on FakeLive: a job renders Version by Version through a fake export, the values go back, the
numbers arrive, and the older tools' folders show up as Options. No real export, no Live, no sound."""

from __future__ import annotations

import queue
import threading
import urllib.request

import numpy as np
import pytest
import soundfile as sf

from tests.app.conftest import wait_for
from tests.app.test_web import first_control
from zpkt.app import renders
from zpkt.app.bus import Command
from zpkt.live import state as S

RATE = 44100


def tone(path, amp, seconds=1.0):
    t = np.arange(int(RATE * seconds)) / RATE
    x = (amp * np.sin(2 * np.pi * 1000 * t)).astype(np.float32)
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(path, np.stack([x, x], axis=1), RATE, subtype="PCM_16")


class FakeExport:
    """Stands in for Live's export: it reads the control from Live, as it is during the render, and writes a WAV
    whose level is that value, so a Version's numbers show which values were in Live."""

    def __init__(self, rig, key):
        self.rig, self.key, self.seen, self.calls, self.fail_on = rig, key, [], [], None

    def __call__(self, conn, out, start, length):
        raw = S.flatten(S.take(conn))[self.key][1]
        self.seen.append(raw)
        self.calls.append((out, start, length))
        if self.fail_on == len(self.calls):
            raise RuntimeError("Live's Export dialog did not open")
        tone(out, 0.1 + 0.5 * raw)
        return out


def live_value(rig, key):
    return S.flatten(S.take(rig.conn))[key][1]


@pytest.fixture()
def desk_options(rig):
    _, key, _ = first_control(rig, "f")
    ex = FakeExport(rig, key)
    opts = rig.desk.options
    opts.exporter, opts.pause = ex, lambda s: None
    return rig, opts, key, ex


def request(key, *raws, title="Fader grid"):
    return {"title": title, "versions": [{"label": f"at {r}", "writes": [[key, r]]} for r in raws]}


def test_a_job_renders_each_version_with_its_values_then_puts_them_back(desk_options):
    rig, opts, key, ex = desk_options
    start = live_value(rig, key)
    stream = rig.desk.subscribe(app=True)
    option = opts.make(request(key, 0.3, 0.6))
    assert opts.run_pending() >= 1 or wait_for(lambda: opts.get(option["id"])["status"] == "ready")
    got = opts.get(option["id"])
    assert got["status"] == "ready" and got["done"] == 3 and got["progress"] == "ready"
    assert [v["status"] for v in got["versions"]] == ["ready"] * 3
    assert ex.seen == [pytest.approx(start), pytest.approx(0.3), pytest.approx(0.6)]
    assert live_value(rig, key) == pytest.approx(start)  # put back
    peaks = [v["measure"]["peak_db"] for v in got["versions"]]
    assert peaks[1] < peaks[2] and got["versions"][0]["gap"]["peak_db"] == 0
    assert got["versions"][2]["gap"]["peak_db"] == pytest.approx(peaks[2] - peaks[0], abs=0.01)
    assert all(v["file"] and v["file"].endswith(f"{v['id']}.wav") for v in got["versions"])
    assert rig.desk.history.entries == []  # the render's writes are not moves of yours
    texts = []
    while not stream.empty():
        m = stream.get_nowait()
        if m.get("t") == "option":
            texts.append(m["option"]["progress"])
    assert "rendering 1 of 3" in texts and "rendering 2 of 3" in texts and "rendering 3 of 3" in texts
    assert texts[-1] == "ready"


def test_the_range_goes_to_the_export(desk_options):
    _rig, opts, key, ex = desk_options
    opts.make({**request(key, 0.4), "range": {"start_beat": 64, "length_beats": 32}})
    assert wait_for(lambda: len(ex.calls) == 2)
    assert {(c[1], c[2]) for c in ex.calls} == {(64.0, 32.0)}


def test_a_failed_export_fails_the_job_says_why_and_still_puts_the_values_back(desk_options):
    rig, opts, key, ex = desk_options
    start = live_value(rig, key)
    ex.fail_on = 2
    option = opts.make(request(key, 0.3, 0.6))
    assert wait_for(lambda: opts.get(option["id"])["status"] == "failed")
    got = opts.get(option["id"])
    assert got["error"] == "Live's Export dialog did not open" == got["progress"]
    assert [v["status"] for v in got["versions"]] == ["ready", "failed", "failed"]
    assert got["versions"][1]["error"] == got["error"]
    assert live_value(rig, key) == pytest.approx(start)
    assert len(ex.calls) == 2  # it stopped at the failure


def test_a_job_for_another_set_is_refused_before_anything_is_written(desk_options):
    rig, opts, key, ex = desk_options
    rig.desk.bus.guard.open_set = lambda: "Some other set"
    rig.desk.bus.guard.forget()
    option = opts.make(request(key, 0.3))
    assert wait_for(lambda: opts.get(option["id"])["status"] == "failed")
    assert "Some other set" in opts.get(option["id"])["error"] and ex.calls == []


def test_a_job_that_cannot_get_live_fails_with_busy_not_silence(desk_options, monkeypatch):
    rig, opts, key, _ex = desk_options
    monkeypatch.setattr(renders, "CLAIM_WAIT_S", 0.1)
    held, release = threading.Event(), threading.Event()

    def hold():
        with rig.conn.exclusive():
            held.set()
            release.wait(5)

    t = threading.Thread(target=hold)
    t.start()
    held.wait(2)
    try:
        option = opts.make(request(key, 0.3))
        assert wait_for(lambda: opts.get(option["id"])["status"] == "failed")
        assert "Live is busy" in opts.get(option["id"])["error"]
    finally:
        release.set()
        t.join()


def test_keys_the_desk_does_not_know_are_refused_with_a_400(desk_options):
    rig, _opts, _key, _ex = desk_options
    code, body = rig.command("options.make", request("No such track/volume", 0.5))
    assert code == 400 and "does not know No such track/volume" in body["error"]
    assert rig.command("options.make", {"title": "t"})[0] == 400


def test_over_http_a_job_is_made_listed_and_finishes_on_its_own_thread(desk_options):
    rig, _opts, key, _ex = desk_options
    code, body = rig.command("options.make", request(key, 0.3))
    assert code == 200 and body["option"]["kind"] == "grid" and body["option"]["total"] == 2
    oid = body["option"]["id"]
    assert wait_for(lambda: rig.get(f"/api/options?option={oid}")[1]["status"] == "ready")
    listed = rig.get("/api/options")[1]
    assert listed["t"] == "options" and [o["id"] for o in listed["options"]] == [oid]
    assert rig.get("/api/options?option=nope")[0] == 404
    assert rig.command("options.list")[1]["options"][0]["id"] == oid


def test_pick_makes_a_version_now_as_one_move_by_you(desk_options):
    rig, opts, key, _ex = desk_options
    option = opts.make(request(key, 0.3, 0.6))
    assert wait_for(lambda: opts.get(option["id"])["status"] == "ready")
    code, _body = rig.command("options.pick", {"option": option["id"], "version": "v2"})
    assert code == 200
    assert live_value(rig, key) == pytest.approx(0.6)
    assert wait_for(lambda: rig.desk.history.entries)
    entry = rig.desk.history.entries[-1]
    assert entry["who"] == "you" and entry["moves"][0]["key"] == key
    assert opts.get(option["id"])["now"] == "v2"
    undone = rig.command("history.undo")
    assert undone[0] == 200


def test_pick_says_no_for_the_base_a_missing_version_and_a_version_not_ready(desk_options):
    rig, opts, key, _ex = desk_options
    option = opts.make(request(key, 0.3))
    assert wait_for(lambda: opts.get(option["id"])["status"] == "ready")
    code, body = rig.command("options.pick", {"option": option["id"], "version": "base"})
    assert code == 400 and "nothing to put on Now" in body["error"]
    assert rig.command("options.pick", {"option": option["id"], "version": "v9"})[0] == 400
    assert rig.command("options.pick", {"option": "nope", "version": "v1"})[0] == 400


def test_an_agent_proposes_an_option_but_needs_a_word_to_make_one_now(desk_options):
    rig, opts, key, _ex = desk_options
    made = rig.desk.bus.submit(Command("options.make", "agent", request(key, 0.4)))
    assert made[0] == 200
    oid = made[1]["option"]["id"]
    assert wait_for(lambda: opts.get(oid)["status"] == "ready")
    refused = rig.desk.bus.submit(Command("options.pick", "agent", {"option": oid, "version": "v1"}))
    assert refused[0] == 403
    rig.desk.bus.option_picked = lambda option: option == oid  # you picked it
    ok = rig.desk.bus.submit(
        Command("options.pick", "agent", {"option": oid, "version": "v1"}, approval=f"option:{oid}", group="g")
    )
    assert ok[0] == 200 and rig.desk.history.entries[-1]["who"] == "agent"


# ---- the older tools' Options ---------------------------------------------------------------------------------------


@pytest.fixture()
def arranger(rig):
    root = rig.tmp / "arranger"
    tone(root / "mix2" / "b1" / "base.flac".replace("flac", "wav"), 0.2)
    sf.write(root / "mix2" / "b1" / "p00.flac", np.zeros((RATE, 2), dtype=np.float32) + 0.1, RATE)
    (root / "mix2" / "b1" / "base.wav").rename(root / "mix2" / "b1" / "base.flac") if False else None
    sf.write(root / "mix2" / "b1" / "base.flac", np.zeros((RATE, 2), dtype=np.float32) + 0.2, RATE)
    import json

    req = root / "mix2" / "requests"
    req.mkdir(parents=True)
    (req / "b1.json").write_text(
        json.dumps(
            {
                "id": "b1",
                "status": "ready",
                "made": 5,
                "total": 3,
                "done": 3,
                "target": "bus-kick",
                "device": "Saturator",
                "base": "base.flac",
                "baseLufs": -9.0,
                "points": [{"k": 0, "values": {"Drive": "6 dB"}, "file": "p00.flac", "lufs": -8.0}],
            }
        )
    )
    (req / "broken.json").write_text("{nope")
    tone(root / "spectral" / "before.wav", 0.3)
    (root / "spectral" / "renders.json").write_text(
        json.dumps({"renders": [{"id": "before", "title": "Before", "file": "before.wav", "lufsWhole": -9.5}]})
    )
    (root / "kickfuzz").mkdir()
    (root / "kickfuzz" / "renders.json").write_text("{not json")
    return root


def test_mix2_spectral_and_kick_files_are_listed_as_options_and_a_bad_file_is_said(rig, arranger):
    got = rig.get("/api/options")[1]
    assert sorted(o["id"] for o in got["options"]) == ["mix2-b1", "spectral"]
    assert len(got["skipped"]) == 1 and "kickfuzz" in got["skipped"][0]
    mix2 = next(o for o in got["options"] if o["id"] == "mix2-b1")
    assert mix2["kind"] == "mix2" and [v["id"] for v in mix2["versions"]] == ["base", "p00"]


def test_showing_a_version_measures_it_once_and_puts_it_on_the_hear_bar(rig, arranger):
    calls = []
    real = rig.desk.options.measurer
    rig.desk.options.measurer = lambda p: calls.append(p) or real(p)
    stream = rig.desk.subscribe(app=True)
    code, body = rig.command("options.show", {"option": "mix2-b1", "version": "p00"})
    assert code == 200 and body["version"]["measure"]["peak_db"] == pytest.approx(-20.0, abs=0.1)
    assert body["version"]["gap"] is None  # the base is not measured yet
    rig.command("options.show", {"option": "mix2-b1", "version": "p00"})
    assert len(calls) == 1  # kept
    rig.command("options.show", {"option": "mix2-b1", "version": "base"})
    shown = rig.get("/api/options")[1]
    assert shown["shown"]["version"]["id"] == "base"
    p00 = next(v for o in shown["options"] if o["id"] == "mix2-b1" for v in o["versions"] if v["id"] == "p00")
    assert p00["gap"]["peak_db"] == pytest.approx(-6.02, abs=0.1)  # 0.1 against 0.2
    msgs = []
    while not stream.empty():
        msgs.append(stream.get_nowait()["t"])
    assert msgs.count("options") == 3


def test_a_measure_is_taken_again_when_the_file_changes(rig, arranger):
    calls = []
    real = rig.desk.options.measurer
    rig.desk.options.measurer = lambda p: calls.append(p) or real(p)
    rig.command("options.show", {"option": "spectral", "version": "before"})
    f = arranger / "spectral" / "before.wav"
    tone(f, 0.05)
    import os

    os.utime(f, (1, 1_900_000_000))
    rig.command("options.show", {"option": "spectral", "version": "before"})
    assert len(calls) == 2


def test_a_version_file_is_served_with_range_and_only_when_an_option_names_it(rig, arranger):
    url = f"{rig.url}/api/options/file?option=spectral&version=before"
    whole = urllib.request.urlopen(url).read()
    assert whole[:4] == b"RIFF"
    req = urllib.request.Request(url, headers={"Range": "bytes=0-3"})
    with urllib.request.urlopen(req) as r:
        assert r.status == 206 and r.read() == b"RIFF" and r.headers["Content-Type"] == "audio/wav"
    for bad in ("option=spectral&version=nope", "option=../x&version=before", "option=mix2-b1&version=nope"):
        with pytest.raises(urllib.error.HTTPError) as e:
            urllib.request.urlopen(f"{rig.url}/api/options/file?{bad}")
        assert e.value.code == 404


def test_a_gone_version_has_no_file_to_serve(rig, arranger):
    import json
    import urllib.error

    row = arranger / "mix2" / "requests" / "b1.json"
    d = json.loads(row.read_text())
    d["points"].append({"k": 1, "values": {}, "file": "p01.flac", "lufs": -1})
    row.write_text(json.dumps(d))
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(f"{rig.url}/api/options/file?option=mix2-b1&version=p01")
    assert e.value.code == 404


def test_the_shell_stream_starts_with_the_options(rig):
    with urllib.request.urlopen(rig.url + "/events?app=1", timeout=10) as r:
        kinds = []
        for _ in range(4):
            import json

            kinds.append(json.loads(r.readline().decode().removeprefix("data: "))["t"])
            r.readline()
    assert kinds == ["full", "hear", "hist", "options"]


def test_the_queue_is_one_lock_with_the_bus(desk_options):
    """A job holds Live per Version: the bus's own lock is the connections' lock, so a move waits its turn."""
    rig, opts, key, _ex = desk_options
    inside, release = threading.Event(), threading.Event()

    def slow(conn, out, a, b):
        inside.set()
        release.wait(5)
        tone(out, 0.2)
        return out

    opts.exporter = slow
    opts.make(request(key, 0.3))
    assert inside.wait(3)
    q: queue.Queue = queue.Queue()

    def try_lock():
        try:
            with rig.conn.exclusive(wait_s=0.1):
                q.put("got it")
        except Exception as exc:
            q.put(str(exc))

    t = threading.Thread(target=try_lock)
    t.start()
    t.join()
    assert "busy" in q.get()
    release.set()
    assert wait_for(lambda: opts.all()[0]["status"] == "ready", 10)


def test_the_real_export_is_zpkt_live_export_with_the_apps_connection(rig, tmp_path, monkeypatch):
    from zpkt.live import export

    seen = {}

    def fake(client, out, start, length, **kw):
        seen.update(client=client, out=out, start=start, length=length, kw=kw)
        return [out]

    monkeypatch.setattr(export, "export", fake)
    got = renders.export_main(rig.conn, tmp_path / "a.wav", 32.0, 16.0)
    assert got == tmp_path / "a.wav"
    assert seen["client"] is rig.conn and (seen["start"], seen["length"]) == (32.0, 16.0)
    assert seen["kw"] == {"method": "keys"}
    monkeypatch.setattr(export, "export", lambda *a, **k: [])
    with pytest.raises(RuntimeError, match="exported nothing"):
        renders.export_main(rig.conn, tmp_path / "b.wav", None, None)
