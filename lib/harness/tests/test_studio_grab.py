"""Capturing the screen: the helper's client against a stand-in helper (fake_screengrab.py), building the helper on
first use (with a stand-in swiftc), and falling back to `screencapture`. One live test, opt-in: STUDIO_LIVE_SCREEN=1
builds the real helper and takes a few captures of this Mac's screen."""

import asyncio
import logging
import os
import stat
import sys
import time
from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageCms

from harness.studio import grab, shots
from harness.studio.shots import Frame

FAKE_HELPER = Path(__file__).with_name("fake_screengrab.py")


@pytest.fixture
def helper(tmp_path):
    return grab.Helper([sys.executable, str(FAKE_HELPER)], tmp_path / "frame.bgra", timeout=2)


@pytest.fixture
def starts(tmp_path, monkeypatch):
    """How many helper processes have started (they log to a file)."""
    log = tmp_path / "helper.log"
    monkeypatch.setenv("FAKE_LOG", str(log))
    return lambda: sum(line.startswith("launched ") for line in log.read_text().splitlines()) if log.exists() else 0


def executable(path: Path, text: str) -> Path:
    path.write_text(text)
    path.chmod(path.stat().st_mode | stat.S_IXUSR)
    return path


class Swiftc:
    """A stand-in swiftc: logs each build, then "compiles" the source into a script that runs the fake helper (or
    fails, with FAKE_SWIFTC_FAILS=1)."""

    def __init__(self, tmp: Path):
        self.log = tmp / "swiftc.log"
        self.path = str(executable(tmp / "swiftc", SWIFTC.format(python=sys.executable, log=str(self.log),
                                                                   helper=FAKE_HELPER)))

    def calls(self) -> list[str]:
        return self.log.read_text().splitlines() if self.log.exists() else []


SWIFTC = """#!{python}
import os, sys
args = sys.argv[1:]
with open({log!r}, "a") as f:
    f.write(" ".join(args) + "\\n")
if os.environ.get("FAKE_SWIFTC_FAILS") == "1":
    sys.exit("screengrab.swift:1:1: error: cannot find 'SCStream' in scope")
out = args[args.index("-o") + 1]
with open(out, "w") as f:
    f.write("#!/bin/sh\\nexec {python} {helper} \\"$@\\"\\n")
os.chmod(out, 0o755)
"""


@pytest.fixture
def swiftc(tmp_path):
    return Swiftc(tmp_path)


@pytest.fixture
def source(tmp_path):
    return executable(tmp_path / "screengrab.swift", "// the helper's source\n")


@pytest.fixture
def screencaptures(monkeypatch):
    """screencapture, replaced: each call returns a small grey frame and is counted."""
    calls = []

    async def fake(timeout=15.0):
        calls.append(time.monotonic())
        return Frame(np.full((48, 64, 3), 128, np.uint8), time.monotonic())

    monkeypatch.setattr(grab, "screencapture", fake)
    return calls


# --- the helper's client -------------------------------------------------------------------------------------------
async def test_a_shot_is_read_from_padded_bgra_rows(helper):
    first = await helper.shot()
    assert helper.preflight is True
    assert first.pixels.shape == (48, 64, 3) and not first.pixels.flags.writeable
    assert tuple(first.pixels[0, 0]) == (40, 40, 40)
    assert tuple(first.pixels[20, 2]) == (250, 120, 10)             # BGRA on the wire, RGB here
    second = await helper.shot()                                   # the block moved two pixels
    assert tuple(second.pixels[20, 2]) == (40, 40, 40) and tuple(second.pixels[20, 4]) == (250, 120, 10)
    assert await helper.front() == (8, 4, 32, 24)
    await helper.close()


async def test_the_stream_hands_back_the_same_frame_until_the_screen_changes(helper):
    await helper.start(2)
    assert helper.streaming
    a = await helper.frame()
    assert await helper.frame() is a                               # nothing changed: no new frame read
    await helper.call("change")
    b = await helper.frame()
    assert b is not a and not np.array_equal(a.pixels, b.pixels)
    await helper.stop()
    assert not helper.streaming
    with pytest.raises(grab.HelperError, match="no stream"):
        await helper.frame()
    await helper.close()


async def test_a_helper_that_dies_is_started_again(helper, starts):
    await helper.shot()
    with pytest.raises(grab.HelperError, match="exited"):
        await helper.call("die")
    assert (await helper.shot()).pixels.shape == (48, 64, 3)
    assert starts() == 2
    await helper.close()


async def test_a_helper_that_hangs_is_killed_and_started_again(helper, starts):
    await helper.start(2)
    helper.timeout = 0.3
    with pytest.raises(grab.HelperError, match="no answer"):
        await helper.call("hang")
    assert not helper.streaming                                    # the stream went with the process
    helper.timeout = 2                                             # time enough for a fresh one to start
    await helper.shot()
    assert starts() == 2
    await helper.close()


async def test_a_call_cancelled_half_way_leaves_no_stale_reply(helper, starts):
    call = asyncio.create_task(helper.call("hang"))
    await asyncio.sleep(0.3)
    call.cancel()
    with pytest.raises(asyncio.CancelledError):
        await call
    assert await helper.front() == (8, 4, 32, 24)                  # its answer, not one meant for the hang
    assert starts() == 2
    await helper.close()


async def test_calls_go_one_at_a_time(helper):
    frames = await asyncio.gather(*(helper.shot() for _ in range(4)))
    blocks = sorted(int(np.argmax(f.pixels[20, :, 0] > 200)) for f in frames)
    assert blocks == [2, 4, 6, 8]                                  # four whole shots, none mixed up
    await helper.close()


async def test_without_screen_recording_captures_are_refused(helper, monkeypatch):
    monkeypatch.setenv("FAKE_PREFLIGHT", "0")
    with pytest.raises(grab.CaptureUnavailable, match="tmux"):
        await helper.shot()
    with pytest.raises(grab.CaptureUnavailable):
        await helper.start(2)
    assert helper.preflight is False
    await helper.close()


async def test_close_ends_the_process(helper):
    await helper.shot()
    proc = helper._proc
    await helper.close()
    assert proc.returncode is not None


# --- building it ---------------------------------------------------------------------------------------------------
def test_the_helper_is_built_once_per_source(tmp_path, source, swiftc):
    bin_dir = tmp_path / "bin"
    path = grab.build(bin_dir, source, swiftc.path)
    assert path.parent == bin_dir and path.name.startswith("screengrab-") and len(path.name) == len("screengrab-") + 12
    assert os.access(path, os.X_OK) and len(swiftc.calls()) == 1
    assert grab.build(bin_dir, source, swiftc.path) == path and len(swiftc.calls()) == 1   # kept
    assert "-swift-version 6" in swiftc.calls()[0] and swiftc.calls()[0].endswith(str(source))

    source.write_text("// a changed source\n")
    changed = grab.build(bin_dir, source, swiftc.path)
    assert changed != path and len(swiftc.calls()) == 2
    assert sorted(p.name for p in bin_dir.iterdir()) == sorted([path.name, changed.name])   # no leftovers


def test_a_failed_build_says_why_and_leaves_nothing(tmp_path, source, swiftc, monkeypatch):
    monkeypatch.setenv("FAKE_SWIFTC_FAILS", "1")
    with pytest.raises(grab.BuildError, match="cannot find 'SCStream'"):
        grab.build(tmp_path / "bin", source, swiftc.path)
    assert list((tmp_path / "bin").iterdir()) == []


def test_without_the_developer_tools_there_is_no_swiftc(monkeypatch):
    monkeypatch.setattr(grab.shutil, "which", lambda name: None)
    assert grab.find_swiftc() is None
    with pytest.raises(grab.BuildError, match="no swiftc"):
        grab.build(Path("/nonexistent"), grab.SOURCE)


# --- the capture the app uses --------------------------------------------------------------------------------------
async def test_screengrab_builds_the_helper_on_first_use(tmp_path, source, swiftc, screencaptures):
    capture = grab.ScreenGrab(tmp_path / "bin", source=source, swiftc=swiftc.path)
    assert swiftc.calls() == []                                    # nothing until a capture is asked for
    frame = await capture.grab()
    assert frame.pixels.shape == (48, 64, 3) and frame.window == (8, 4, 32, 24)
    await capture.grab()
    assert len(swiftc.calls()) == 1 and screencaptures == []
    assert isinstance(capture, grab.Streaming)

    await capture.watch(2)
    a = await capture.latest()
    assert await capture.latest() is a
    await capture.unwatch()
    assert (await capture.latest()) is not a                       # no stream: a capture
    await capture.close()


async def test_without_a_helper_screencapture_takes_over_and_says_so_once(tmp_path, source, swiftc, screencaptures,
                                                                          monkeypatch, caplog):
    monkeypatch.setenv("FAKE_SWIFTC_FAILS", "1")
    capture = grab.ScreenGrab(tmp_path / "bin", source=source, swiftc=swiftc.path)
    with caplog.at_level(logging.WARNING, logger="harness.studio.grab"):
        for _ in range(3):
            assert (await capture.grab()).pixels.shape == (48, 64, 3)
        await capture.watch(2)
        await capture.latest()
    assert len(screencaptures) == 4 and len(swiftc.calls()) == 1
    said = [r.message for r in caplog.records if "screencapture" in r.message]
    assert len(said) == 1 and said[0].startswith("screenshots through screencapture: swiftc failed: ")
    assert said[0].endswith("error: cannot find 'SCStream' in scope")
    await capture.close()


async def test_a_failing_helper_is_restarted_then_given_up(tmp_path, source, swiftc, screencaptures, starts,
                                                           monkeypatch):
    monkeypatch.setenv("FAKE_SHOT_FAILS", "1")
    capture = grab.ScreenGrab(tmp_path / "bin", source=source, swiftc=swiftc.path)
    for _ in range(5):
        await capture.grab()                                       # each failure still gets a screenshot
    assert len(screencaptures) == 5
    assert starts() == grab.ScreenGrab.MAX_FAILURES                # restarted after each failure, then given up
    assert capture.helper is None
    await capture.close()


async def test_without_screen_recording_screengrab_refuses(tmp_path, source, swiftc, screencaptures, monkeypatch):
    monkeypatch.setenv("FAKE_PREFLIGHT", "0")
    capture = grab.ScreenGrab(tmp_path / "bin", source=source, swiftc=swiftc.path)
    with pytest.raises(grab.CaptureUnavailable, match="Screen Recording"):
        await capture.grab()
    await capture.watch(2)                                         # quietly no stream...
    with pytest.raises(grab.CaptureUnavailable):
        await capture.latest()                                     # ...and the capture says why
    assert screencaptures == []                                    # no wallpaper-only screenshots instead
    await capture.close()


# --- pixels from files ---------------------------------------------------------------------------------------------
def test_raw_bgra_rows_with_padding(tmp_path):
    w, h, bpr = 4, 3, 4 * 4 + 16
    rgb = np.arange(w * h * 3, dtype=np.uint8).reshape(h, w, 3) * 7
    rows = np.zeros((h, bpr), np.uint8)
    px = rows[:, : w * 4].reshape(h, w, 4)
    px[..., 0], px[..., 1], px[..., 2], px[..., 3] = rgb[..., 2], rgb[..., 1], rgb[..., 0], 255
    (tmp_path / "f.bgra").write_bytes(rows.tobytes())
    assert np.array_equal(grab.load_bgra(tmp_path / "f.bgra", w, h, bpr), rgb)


def test_a_png_with_a_colour_profile_is_read_as_srgb(tmp_path):
    rgb = np.random.default_rng(0).integers(0, 255, (8, 8, 3), dtype=np.uint8)
    srgb = ImageCms.ImageCmsProfile(ImageCms.createProfile("sRGB")).tobytes()
    Image.fromarray(rgb).save(tmp_path / "s.png", icc_profile=srgb)
    assert np.abs(grab.load_srgb(tmp_path / "s.png").astype(int) - rgb).max() <= 1


# --- the real screen (opt-in) --------------------------------------------------------------------------------------
@pytest.mark.skipif(os.environ.get("STUDIO_LIVE_SCREEN") != "1", reason="STUDIO_LIVE_SCREEN=1 captures the screen")
async def test_live_screen(tmp_path):
    cache = Path(os.environ.get("STUDIO_LIVE_BIN", tmp_path / "bin"))
    capture = grab.ScreenGrab(cache)
    t0 = time.perf_counter()
    first = await capture.grab()                                   # builds the helper if it isn't cached
    t1 = time.perf_counter()
    second = await capture.grab()
    t2 = time.perf_counter()
    await capture.watch(2)
    t3 = time.perf_counter()
    streamed = await capture.latest()
    t4 = time.perf_counter()
    await capture.unwatch()
    await capture.close()
    assert capture.helper is not None and capture.helper.preflight, "no helper, or no Screen Recording permission"
    assert first.pixels.shape == second.pixels.shape == streamed.pixels.shape
    pair = shots.make_pair(first.pixels, second.pixels, window=second.window)
    lite = shots.make_pair(second.pixels, streamed.pixels, preset=shots.PRESETS["firehose"])
    print(f"\nscreen {pair.screen}, front window {second.window}"
          f"\nfirst grab (build + start + shot + front) {1000 * (t1 - t0):.0f} ms, grab {1000 * (t2 - t1):.0f} ms, "
          f"watch {1000 * (t3 - t2):.0f} ms, latest {1000 * (t4 - t3):.0f} ms"
          f"\nmajor: full {pair.full_size} {len(pair.full) / 1000:.0f} KB, zoom {pair.zoom_size} "
          f"{len(pair.zoom) / 1000:.0f} KB on {pair.rect}, changed {pair.changed}"
          f"\nfirehose: full {lite.full_size} {len(lite.full) / 1000:.0f} KB, zoom {len(lite.zoom) / 1000:.0f} KB")
    assert len(pair.full) <= 120_000 and len(pair.zoom) <= 60_000
    assert pair.full[:4] == b"RIFF" and pair.zoom[:4] == b"RIFF"
