from datetime import datetime, timedelta

import pytest

from booth.config import Settings
from booth.gui import Stop
from booth.jobs import Jobs
from booth.live import Builder
from booth.runner import Gate, Runner, loudness_gain
from conftest import example


class Rig:
    def __init__(self, tmp_path, fake, *, front="booth_template", last=None, encode=None):
        self.jobs = Jobs(tmp_path)
        self.settings = Settings(hours=["00:00-23:59"])
        self.front = front
        self.last = last
        self.gate = Gate(self.settings, front=lambda: self.front, last_lom=lambda: self.last)
        self.notes = []
        lv, self.ops = fake
        self.runner = Runner(self.jobs, self.settings, self.gate, builder=lambda step: Builder(lv, step=step),
                             notify=lambda t, b: self.notes.append((t, b)), encode=encode or self.fake_encode)
        self.runner.open()

    @staticmethod
    def fake_encode(plan, score, wav, out, size):
        for name in ("render.m4a", "video.mp4", "still.jpg"):
            (out / name).write_bytes(b"x")


def test_a_job_runs_to_done(tmp_path, fake):
    r = Rig(tmp_path, fake)
    job, created = r.jobs.add("at://m/1#v1", example(), {})
    assert created and r.runner.tick() == job["id"]
    done = r.jobs.public(r.jobs.get(job["id"]))
    assert done["state"] == "done" and set(done["files"]) == {"render.m4a", "video.mp4", "still.jpg", "score.json", "measure.json"}
    assert {"open", "build", "export", "close", "encode", "total"} <= set(done["timings"])
    assert done["measure"]["lufs"] is not None and len(done["measure"]["sections"]) == 4


def test_the_same_key_is_the_same_job(tmp_path, fake):
    r = Rig(tmp_path, fake)
    a, _ = r.jobs.add("k", example(), {})
    b, created = r.jobs.add("k", example("lullaby"), {})
    assert not created and a["id"] == b["id"]


@pytest.mark.parametrize("front,last,why", [
    ("HW002_121_v_9", None, "something else"),
    (None, None, "something else"),
    ("booth_template", datetime.now() - timedelta(seconds=30), "last few minutes"),
])
def test_the_gate(tmp_path, fake, front, last, why):
    r = Rig(tmp_path, fake, front=front, last=last)
    r.jobs.add("k", example(), {})
    assert why in r.gate.reason(r.jobs)
    assert r.runner.tick() is None and r.jobs.queue()


def test_our_own_lom_use_doesnt_block_the_next_job(tmp_path, fake):
    r = Rig(tmp_path, fake)
    r.jobs.add("a", example(), {})
    r.runner.tick()
    r.last = datetime.now()                       # the job just finished talking to Live
    r.jobs.add("b", example("lullaby"), {})
    assert r.gate.reason(r.jobs) is None


def test_closed_and_hours(tmp_path, fake):
    r = Rig(tmp_path, fake)
    r.runner.close("Anthony is working")
    assert r.gate.reason(r.jobs) == "Anthony is working"
    r.runner.open()
    r.settings.hours = ["03:00-03:01"]
    r.gate.now = lambda: datetime(2026, 11, 1, 12, 0)
    assert "hours" in r.gate.reason(r.jobs)


def test_a_surprise_holds_the_job_and_closes_the_booth(tmp_path, fake):
    r = Rig(tmp_path, fake)
    r.ops.devices_override = ["Wrong"]
    a, _ = r.jobs.add("a", example(), {})
    b, _ = r.jobs.add("b", example("lullaby"), {})
    r.runner.tick()
    held = r.jobs.get(a["id"])
    assert held["state"] == "held" and held["error"]["stage"] == "load p1"
    assert r.jobs.kv("open") == "0" and r.notes and "booth open" in r.notes[0][1]
    assert r.runner.tick() is None and r.jobs.get(b["id"])["state"] == "queued"   # never the next job
    r.ops.devices_override = None
    assert r.runner.open() == 1
    r.runner.tick()
    assert r.jobs.get(a["id"])["state"] == "done"


def test_a_silent_render_holds(tmp_path, fake):
    r = Rig(tmp_path, fake)
    r.ops.export_silent = True
    a, _ = r.jobs.add("a", example(), {})
    r.runner.tick()
    assert r.jobs.get(a["id"])["state"] == "held" and r.jobs.kv("open") == "0"


def test_an_encode_failure_fails_but_keeps_the_booth_open(tmp_path, fake):
    def boom(*a):
        raise RuntimeError("ffmpeg went away")
    r = Rig(tmp_path, fake, encode=boom)
    a, _ = r.jobs.add("a", example(), {})
    r.runner.tick()
    j = r.jobs.get(a["id"])
    assert j["state"] == "failed" and j["error"]["retryable"] and r.jobs.kv("open") == "1"


def test_a_restart_holds_running_jobs(tmp_path, fake):
    r = Rig(tmp_path, fake)
    a, _ = r.jobs.add("a", example(), {})
    r.jobs.update(a["id"], state="rendering")
    r.jobs.recover()
    assert r.jobs.get(a["id"])["state"] == "held"


def test_loudness_gain():
    assert loudness_gain(-15.0, 6.0) is None and loudness_gain(None, 6.0) is None
    assert loudness_gain(-21.6, 6.0) == 14.0
    assert loudness_gain(-40.0, 6.0) == 24.0


def test_a_quiet_render_is_exported_again_louder_in_live(tmp_path, fake):
    r = Rig(tmp_path, fake)
    r.ops.level = 0.05
    a, _ = r.jobs.add("a", example(), {})
    r.runner.tick()
    j = r.jobs.get(a["id"])
    assert j["state"] == "done" and len(r.ops.exports) == 2 and "loudness" in j["timings"]
    assert any(d.startswith("song.master_track.devices[2]") and "Input Gain" in v for d, v in r.ops.sets)
    assert j["measure"]["master_gain_db"] > 6 and j["measure"]["lufs"] > -21


def test_a_loud_enough_render_is_exported_once(tmp_path, fake):
    r = Rig(tmp_path, fake)
    r.ops.level = 0.5
    a, _ = r.jobs.add("a", example(), {})
    r.runner.tick()
    assert r.jobs.get(a["id"])["state"] == "done" and len(r.ops.exports) == 1


def test_a_loop_is_made_only_when_asked(tmp_path, fake):
    made = []
    r = Rig(tmp_path, fake)
    r.runner.loop = lambda wav, seconds, m4a: (made.append(seconds), m4a.write_bytes(b"x"))
    plain, _ = r.jobs.add("at://m/2#v1", example(), {})
    r.runner.tick()
    assert "loop.m4a" not in r.jobs.public(r.jobs.get(plain["id"]))["files"] and not made
    looped, _ = r.jobs.add("at://m/3#v1", example(), {"loop": True})
    r.runner.tick()
    assert "loop.m4a" in r.jobs.public(r.jobs.get(looped["id"]))["files"]
    s = example()
    assert made == [pytest.approx(sum(sec["bars"] for sec in s["song"]) * 4 * 60.0 / s["bpm"])]


def test_the_loop_folds_the_tail_onto_the_start_and_fits_room_worlds_limit(tmp_path):
    import json, subprocess
    from booth import video
    # 70 s of song and 2 s of tail: a tone that is silent for the song's last second, so only the tail sounds there
    wav = tmp_path / "render.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=440:d=72", "-af", "volume='if(between(t,69,70),0,1)':eval=frame",
                    "-ar", "44100", "-ac", "2", str(wav)], check=True)
    m4a = tmp_path / "loop.m4a"
    kbps = video.loop(wav, 70.0, m4a)
    assert m4a.stat().st_size <= video.CLIP_BYTES and 48 <= kbps <= 192
    d = json.loads(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "json", str(m4a)],
                                  capture_output=True, check=True).stdout)["format"]["duration"]
    assert abs(float(d) - 70.0) < 0.1
