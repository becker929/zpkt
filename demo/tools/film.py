"""Film Ableton Live playing HW002 for the demo. Run inside hands' environment:

  cd hands && uv run python ../demo/tools/film.py main      # bars 79-182, arrangement view
  cd hands && uv run python ../demo/tools/film.py knob      # an agent turns the kick's knobs at the peak
  cd hands && uv run python ../demo/tools/film.py cut       # an agent runs Edit > Delete Time

Each shot writes out/footage/<shot>.mp4 (the whole screen, 30 fps) and
<shot>.sync.json: Live's song time against the footage clock, so the reel
can show exactly the bar it is playing.
"""
import json
import math
import pathlib
import subprocess
import sys
import threading
import time

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from livectl import menu, r, win  # noqa: E402

OUT = pathlib.Path(__file__).resolve().parent.parent / "out/footage"
BEATS_PER_BAR = 4


class Recorder:
    """ffmpeg screen capture; keeps (wall clock, footage time) pairs from -progress."""

    def __init__(self, name: str) -> None:
        OUT.mkdir(parents=True, exist_ok=True)
        self.path = OUT / f"{name}.mp4"
        self.marks: list[tuple[float, float]] = []
        self.proc = subprocess.Popen(
            ["ffmpeg", "-v", "error", "-y", "-f", "avfoundation", "-capture_cursor", "0",
             "-framerate", "30", "-i", "0:none", "-c:v", "libx264", "-preset", "ultrafast",
             "-crf", "14", "-pix_fmt", "yuv420p", "-r", "30", "-progress", "pipe:1", "-nostats", str(self.path)],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self) -> None:
        for line in self.proc.stdout:
            if line.startswith("out_time_us="):
                try:
                    self.marks.append((time.time(), int(line.split("=")[1]) / 1e6))
                except ValueError:
                    pass

    def wait_started(self) -> None:
        for _ in range(100):
            if any(t > 0 for _, t in self.marks):
                return
            time.sleep(0.1)
        raise RuntimeError("ffmpeg produced no frames")

    def stop(self) -> float:
        self.proc.stdin.write("q")
        self.proc.stdin.flush()
        self.proc.wait(timeout=30)
        # footage t=0 in wall-clock time; progress reports only ever arrive late
        return min(w - t for w, t in self.marks if t > 0)


def poll_song(until_beat: float, samples: list, stop_after: float = 600) -> None:
    start = time.time()
    while time.time() - start < stop_after:
        t0 = time.time()
        beat = r("song.current_song_time")
        t1 = time.time()
        samples.append(((t0 + t1) / 2, beat))
        if beat >= until_beat:
            return
        time.sleep(0.08)


def save(name: str, rec: Recorder, samples: list, extra: dict | None = None) -> None:
    t0 = rec.stop()
    data = {"footage_t0_wall": t0, "samples": [[w - t0, b] for w, b in samples], **(extra or {})}
    # beats = rate * footage_time + offset, from the playing samples
    play = [(t, b) for t, b in data["samples"] if b > samples[0][1] + 0.5]
    if len(play) > 4:
        n = len(play)
        mt = sum(t for t, _ in play) / n
        mb = sum(b for _, b in play) / n
        rate = sum((t - mt) * (b - mb) for t, b in play) / sum((t - mt) ** 2 for t, _ in play)
        data["fit"] = {"beats_per_s": rate, "beat_at_t0": mb - rate * mt}
        resid = max(abs(b - (rate * t + data["fit"]["beat_at_t0"])) for t, b in play)
        data["fit"]["max_resid_beats"] = resid
    (OUT / f"{name}.sync.json").write_text(json.dumps(data, indent=1))
    print(name, json.dumps(data.get("fit")), rec.path)


def play_from(bar: int) -> None:
    r("song.stop_playing()")
    r("song.view.__setattr__('follow_song', True)")
    # start_playing() always starts at the start marker; jump once it is running
    r("song.start_playing()")
    r(f"song.current_song_time = {(bar - 1) * BEATS_PER_BAR}.0")


def main_shot() -> None:
    win()
    rec = Recorder("main")
    rec.wait_started()
    time.sleep(1.0)
    samples: list = []
    play_from(79)
    poll_song((182 - 1) * BEATS_PER_BAR, samples)
    r("song.stop_playing()")
    time.sleep(0.5)
    save("main", rec, samples)


def knob_shot() -> None:
    """At the peak, an agent sweeps the kick sampler's transpose and volume."""
    win()
    sim = "song.tracks[1].devices[0].chains[1].devices[0]"
    names = r(f"[(p.name, p.value, p.min, p.max) for p in {sim}.parameters]")
    params = {n: (v, lo, hi) for n, v, lo, hi in names}
    tr, vol = params["Transpose"], params["Volume"]
    rec = Recorder("knob")
    rec.wait_started()
    time.sleep(0.6)
    samples: list = []
    play_from(125)
    t_start = time.time()
    moves = []
    it, iv = [n for n, *_ in names].index("Transpose"), [n for n, *_ in names].index("Volume")
    while time.time() - t_start < 11:
        x = (time.time() - t_start) / 11
        k = math.sin(math.pi * min(1, max(0, (x - 0.12) / 0.76)))
        tv = round(tr[0] + (12 - tr[0]) * k)  # semitone steps
        vv = vol[0] + (0.0 - vol[0]) * k * 0.6
        t0 = time.time()
        beat = r(f"({sim}.parameters[{it}].__setattr__('value', {tv}), "
                 f"{sim}.parameters[{iv}].__setattr__('value', {vv}), song.current_song_time)[2]")
        t1 = time.time()
        samples.append(((t0 + t1) / 2, beat))
        moves.append(((t0 + t1) / 2, tv, vv))
    r(f"{sim}.parameters[{[n for n, *_ in names].index('Transpose')}].__setattr__('value', {tr[0]})")
    r(f"{sim}.parameters[{[n for n, *_ in names].index('Volume')}].__setattr__('value', {vol[0]})")
    r("song.stop_playing()")
    time.sleep(0.4)
    save("knob", rec, samples, {"moves": [[w, a, b] for w, a, b in moves]})


def cut_shot() -> None:
    """An agent selects bars 105-112 and runs Edit > Delete Time, then undoes it."""
    win()
    play_from(97)  # follow pages the view so bars 97-160 are on screen
    time.sleep(0.8)
    r("song.stop_playing()")
    r('Live.Application.get_application().view.show_view("Arranger")')
    r('Live.Application.get_application().view.focus_view("Arranger")')
    rec = Recorder("cut")
    rec.wait_started()
    time.sleep(1.2)
    before = r("song.last_event_time")
    r(f"song.loop_start = {(105 - 1) * 4}.0")
    r("song.loop_length = 32.0")
    menu("Edit", "Select Loop")
    time.sleep(1.6)
    t_cut = time.time()
    menu("Edit", "Delete Time")
    time.sleep(2.4)
    after = r("song.last_event_time")
    menu("Edit", "Undo Delete Time") or menu("Edit", "Undo")
    time.sleep(1.4)
    samples = [(time.time(), 0.0)]
    save("cut", rec, samples, {"cut_wall": t_cut, "last_event_before": before, "last_event_after": after})


if __name__ == "__main__":
    {"main": main_shot, "knob": knob_shot, "cut": cut_shot}[sys.argv[1]]()
