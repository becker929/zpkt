"""Options on the phone: N renders in one file, held in memory, switched on the audio clock with no request to the
Mac. What the page played is recorded by the ear (heard.py): the Mac's sweep, a held option, a switch that keeps the
beat, the loudness match, and a held option giving way to the Mac at the bar line."""

import asyncio

import numpy as np
import pytest

from conftest import IPHONE_15, open_page
from heard import dominant_hz, heard
from test_heard import listener, the_ear  # noqa: F401 - listener is a fixture
from test_turn import is_mic, is_playback

pytestmark = pytest.mark.ui

FREQS = (300.0, 450.0, 600.0, 750.0)
AMPS = (0.05, 0.1, 0.2, 0.4)


def card(seq: int) -> str:
    return f'#messages [data-seq="{seq}"]'


async def ready(page, seq: int) -> None:
    await page.wait(f"() => document.querySelector('{card(seq)}')?.dataset.state === 'ready'")


async def click_tick(page, seq: int, index: int) -> None:
    """A mouse click on the slider's tick for option `index`."""
    box = await page.page.locator(f"{card(seq)} .opt-tick[data-index='{index}']").bounding_box()
    await page.page.mouse.click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


def rms(x: np.ndarray) -> float:
    return float(np.sqrt(np.mean(x ** 2)))


def on_the_beat(ear, t: float) -> bool:
    """Whether a bar starts at `t` (audio-clock s): each option's bars begin with 20 ms of silence, then the tone."""
    return rms(ear.between(t + 0.003, t + 0.017)) < 0.01 < rms(ear.between(t + 0.025, t + 0.045))


async def test_the_card_shows_the_options_and_loads_them_before_any_tap(phone, fake):
    page = phone
    music = await fake.present_options()
    seq = music["seq"]
    await ready(page, seq)                     # fetched with no audio context yet: nothing has been tapped
    info = await page.js(f"""(() => {{
      const el = document.querySelector('{card(seq)}');
      return {{
        layout: el.dataset.layout, ticks: el.querySelectorAll('.opt-tick').length,
        now: [...el.querySelectorAll('.opt-tick')].findIndex((t) => t.hasAttribute('data-now')),
        value: el.querySelector('.opt-value').textContent, asSet: !el.querySelector('.opt-asset').hidden,
        keep: el.querySelector('.opt-act--keep').textContent, status: el.querySelector('.opt-status').textContent,
        valuetext: el.querySelector('[data-slider]').getAttribute('aria-valuetext'),
      }};
    }})()""")
    assert info == {"layout": "slider", "ticks": 4, "now": 1, "value": "33%", "asSet": True, "keep": "Keep 33%",
                    "status": "Ready: switching is instant", "valuetext": "33%"}


async def test_the_macs_play_sweeps_a_bar_of_each_option(listener, fake):
    page = listener
    fake.turn_frames = 0
    music = await fake.present_options()
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await ready(page, music["seq"])
    mark = len(fake.inbox)
    await fake.play(music["seq"], 1)
    idle = await fake.expect(is_playback("idle", 1), since=mark, timeout=15)
    assert idle["done"] == 1
    await fake.expect(is_mic("open", "t1"), since=mark)
    ear = the_ear(await heard(page.page))
    entry = (await page.js("window.studio.engine.log"))[-1]
    assert entry["outcome"] == "played"
    assert abs(entry["stopAt"] - entry["t0"] - 4 * fake.bar_s) < 1e-6, "one bar of each of the four options"
    t0 = entry["t0"]
    heard_hz = [dominant_hz(ear.between(t0 + k * fake.bar_s + 0.05, t0 + (k + 1) * fake.bar_s - 0.02), ear.rate)
                for k in range(4)]
    assert [round(h / 10) * 10 for h in heard_hz] == [300, 450, 600, 750]
    (_, end), = ear.loud(hold=0.06)
    assert abs(end - entry["stopAt"]) < 0.02, "then silence"


async def test_moving_the_slider_switches_at_once_and_keeps_the_beat(phone, fake):
    page = phone
    music = await fake.present_options()
    seq = music["seq"]
    await ready(page, seq)
    await click_tick(page, seq, 2)                       # touching the slider plays that option, held
    await page.wait("() => window.studio.engine.position() !== null")
    await asyncio.sleep(1.6)
    pressed = await page.js(f"""(() => {{
      document.querySelector('{card(seq)} [data-slider]').focus();
      document.querySelector('{card(seq)} [data-slider]').dispatchEvent(new KeyboardEvent('keydown', {{key: 'ArrowRight', bubbles: true}}));
      return performance.now() / 1000;
    }})()""")
    await asyncio.sleep(2.0)
    assert await page.js(f"document.querySelector('{card(seq)}').dataset.pick") == "3"
    assert await page.js(f"document.querySelector('{card(seq)} .opt-value').textContent") == "100%"
    await page.page.click(f"{card(seq)} .play")          # stop
    await page.wait("() => window.studio.engine.nowPlaying === null")
    ear = the_ear(await heard(page.page))
    entry = (await page.js("window.studio.engine.log"))[-1]
    assert entry["counted"] is False and entry["outcome"] == "stopped"
    t0 = entry["t0"]
    end = entry["endedAt"]

    # Where the sound changed from option 2 to option 3, on the page's clock: soon after the key.
    win = int(0.01 * ear.rate)
    times = np.arange(ear.index(t0) + win, ear.index(end) - win, win)
    hz = [dominant_hz(ear.samples[i:i + 4 * win], ear.rate) for i in times]
    switch = next(ear.time(i) for i, f in zip(times, hz) if f > 700)
    latency = ear.perf(switch) - pressed
    assert 0 <= latency < 0.12, f"the switch was heard {latency * 1000:.0f} ms after the key"
    assert dominant_hz(ear.between(t0 + 0.1, switch - 0.05), ear.rate) == pytest.approx(600, abs=10)
    assert dominant_hz(ear.between(switch + 0.05, end - 0.05), ear.rate) == pytest.approx(750, abs=10)

    # Every bar line, before and after the switch, is where it was when the option started: same place in the bar.
    lines = [t0 + k * fake.bar_s for k in range(1, int((end - t0) / fake.bar_s))]
    lines = [t for t in lines if abs(t - switch) > 0.06]                      # not inside the crossfade
    assert len(lines) >= 4 and any(t > switch for t in lines), lines
    assert all(on_the_beat(ear, t) for t in lines), [round((t - t0) / fake.bar_s, 3) for t in lines]
    assert not on_the_beat(ear, t0 + 1.5 * fake.bar_s), "and the check can tell"


async def test_match_loudness_is_on_and_levels_the_options(phone, fake):
    page = phone
    music = await fake.present_options()
    seq = music["seq"]
    await ready(page, seq)
    await click_tick(page, seq, 3)                       # the loudest: 0.4, 18 dB above the quietest
    await page.wait("() => window.studio.engine.nowPlaying !== null")
    await asyncio.sleep(0.8)
    toggled = await page.js("performance.now() / 1000")
    assert await page.js(f"document.querySelector('{card(seq)} .opt-match').getAttribute('aria-checked')") == "true", \
        "Match loudness is on by default"
    await page.page.click(f"{card(seq)} .opt-match")
    assert await page.js(f"document.querySelector('{card(seq)} .opt-match').getAttribute('aria-checked')") == "false"
    await asyncio.sleep(0.8)
    await page.page.click(f"{card(seq)} .play")
    ear = the_ear(await heard(page.page))
    entry = (await page.js("window.studio.engine.log"))[-1]
    t0 = entry["t0"]
    split = next(t for t in np.arange(t0, entry["endedAt"], 0.01) if ear.perf(t) >= toggled)
    before = rms(ear.between(t0 + 0.1, split - 0.05))
    after = rms(ear.between(split + 0.15, entry["endedAt"] - 0.05))
    assert 20 * np.log10(after / before) == pytest.approx(18.06, abs=0.7), "matched to the quietest, then Live's level"


async def test_keep_stops_and_says_which_option(phone, fake):
    page = phone
    fake.script = lambda text: asyncio.sleep(0)          # the Mac takes the turn and does nothing
    music = await fake.present_options()
    seq = music["seq"]
    await ready(page, seq)
    await click_tick(page, seq, 2)
    await page.wait("() => window.studio.engine.nowPlaying !== null")
    await page.page.click(f"{card(seq)} .opt-act--keep")
    said = await fake.expect(lambda m: m["type"] == "say")
    assert said["text"] == f"Keep rumble Drive at 67%: option 3 of 4 on card {seq}."
    await page.wait("() => window.studio.engine.nowPlaying === null")
    mark = len(fake.inbox)
    await page.page.click(f"{card(seq)} [data-action='opt-finer']")
    finer = await fake.expect(lambda m: m["type"] == "say", since=mark)
    assert finer["text"] == f"Finer on rumble Drive between 33% and 100%, around 67% (card {seq})."


async def test_a_held_option_gives_way_to_the_mac_at_the_bar_line(phone, fake):
    page = phone
    fake.turn_frames = 0                                # listening, until the Mac has something
    music = await fake.present_options()
    seq = music["seq"]
    await ready(page, seq)
    await page.page.click("#turn")                      # this page owns the speaker; then hold an option
    await fake.until(lambda: fake.owner is not None)
    await page.page.click(f"{card(seq)} .play")
    await page.wait("() => window.studio.engine.nowPlaying !== null")
    await asyncio.sleep(0.6)
    reply = await fake.upsert("agent", text="Here it is.", role="reply", audio=None, duration=None, streaming=True)
    await fake.speak(reply, 0.4)
    await fake.expect(is_playback("idle", 1), timeout=15)
    log = await page.js("window.studio.engine.log")
    held = next(e for e in log if e["seq"] == seq)
    assert held["counted"] is False and held["outcome"] == "played"
    bars = (held["stopAt"] - held["t0"]) / fake.bar_s
    assert abs(bars - round(bars)) * fake.bar_s < 0.013, f"it ended {bars:.3f} bars in, not on a bar line"
    assert log[-1]["kind"] == "speech" and log[-1]["outcome"] == "played"


async def test_buttons_play_the_option_tapped(phone, fake):
    page = phone
    music = await fake.present_options(layout="buttons", now=None, title="Reverb on the clap")
    seq = music["seq"]
    await ready(page, seq)
    assert await page.js(f"[...document.querySelectorAll('{card(seq)} .opt-button')].map((b) => b.textContent)") == \
        ["Plate", "Hall", "Room", "Spring"]
    await page.page.click(f"{card(seq)} .opt-button[data-index='1']")
    await page.wait("() => window.studio.engine.position() !== null")
    await asyncio.sleep(0.5)
    checked = await page.js(f"[...document.querySelectorAll('{card(seq)} .opt-button')].map((b) => b.getAttribute('aria-checked'))")
    assert checked == ["false", "true", "false", "false"]
    pos = await page.js("window.studio.engine.position()")
    assert pos["option"] == 1
    await page.page.click(f"{card(seq)} .play")
    ear = the_ear(await heard(page.page))
    (start, end), = ear.loud(hold=0.06)
    assert dominant_hz(ear.between(start + 0.05, end - 0.05), ear.rate) == pytest.approx(450, abs=10)


# --- in WebKit at an iPhone's size: the browser that matters most ---------------------------------------------------

@pytest.fixture
async def iphone(webkit, fake):
    page = await open_page(webkit, fake, device=IPHONE_15)
    yield page
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def tap_tick(page, seq: int, index: int) -> None:
    box = await page.page.locator(f"{card(seq)} .opt-tick[data-index='{index}']").bounding_box()
    await page.page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)


async def test_safari_taps_on_the_slider_switch_options_on_the_beat(iphone, fake):
    page = iphone
    music = await fake.present_options()
    seq = music["seq"]
    await ready(page, seq)
    await tap_tick(page, seq, 2)                         # a tap is the gesture that starts the audio, too
    await page.wait("() => window.studio.engine.position() !== null")
    await asyncio.sleep(1.6)
    await tap_tick(page, seq, 3)
    await asyncio.sleep(2.0)
    await page.page.tap(f"{card(seq)} .play")
    await page.wait("() => window.studio.engine.nowPlaying === null")
    ear = the_ear(await heard(page.page))
    entry = (await page.js("window.studio.engine.log"))[-1]
    t0, end = entry["t0"], entry["endedAt"]
    win = int(0.01 * ear.rate)
    times = np.arange(ear.index(t0) + win, ear.index(end) - win, win)
    switch = next(ear.time(i) for i in times if dominant_hz(ear.samples[i:i + 4 * win], ear.rate) > 700)
    assert dominant_hz(ear.between(t0 + 0.1, switch - 0.05), ear.rate) == pytest.approx(600, abs=10)
    assert dominant_hz(ear.between(switch + 0.05, end - 0.05), ear.rate) == pytest.approx(750, abs=10)
    lines = [t for t in (t0 + k * fake.bar_s for k in range(1, int((end - t0) / fake.bar_s))) if abs(t - switch) > 0.06]
    assert len(lines) >= 4 and all(on_the_beat(ear, t) for t in lines), lines


@pytest.mark.parametrize("layout", ["slider", "buttons"])
async def test_an_options_card_fits_the_smallest_iphone(webkit, fake, layout):
    page = await open_page(webkit, fake, device={**IPHONE_15, "viewport": {"width": 320, "height": 700}})
    music = await fake.present_options(layout=layout, title="Rumble drive, from none to all the way up")
    await ready(page, music["seq"])
    assert await page.js("document.documentElement.scrollWidth") == 320
    keep = await page.page.locator(f"{card(music['seq'])} .opt-act--keep").bounding_box()
    assert keep["x"] + keep["width"] <= 320 and keep["height"] >= 40
    assert page.errors == []
    await page.page.context.close()


async def test_during_a_sweep_the_card_picks_the_option_that_sounds(listener, fake):
    # What Keep, Finer here and play mean is what was heard last: the sweep moves the pick, and the pill names it.
    page = listener
    fake.turn_frames = 0
    music = await fake.present_options()
    seq = music["seq"]
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await ready(page, seq)
    await fake.play(seq, 1)
    seen, pills = [], set()
    for _ in range(12):
        pos = await page.js("window.studio.engine.position()")
        pick = await page.js(f"Number(document.querySelector('{card(seq)}').dataset.pick)")
        if pos and pos.get("sweeping"):
            seen.append((pos["option"], pick))
            pills.add(await page.js("document.getElementById('phase-detail').textContent"))
        await asyncio.sleep(fake.bar_s / 3)
    assert {o for o, _ in seen} >= {1, 2, 3}, seen
    assert sum(o == p for o, p in seen) >= len(seen) - 1, f"the pick lags the sound: {seen}"
    assert pills == {"Rumble drive"}, pills
    await fake.expect(is_playback("idle", 1), timeout=15)
    assert await page.js(f"document.querySelector('{card(seq)}').dataset.pick") == "3", "the last option heard"
