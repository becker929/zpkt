"""What came out of the page's speakers, recorded by the ear (heard.py) and checked against what the Mac sent: the
speech tone, the A/B file pass by pass, silence after stop_audio, and nothing while the mic is open."""

import asyncio
import io

import numpy as np
import pytest
import soundfile as sf

import studio_media as media
from conftest import open_page
from heard import Ear, dominant_hz, find_passes, heard, mic_spans, overlaps, resample
from test_turn import BACKGROUND, is_mic, is_playback

pytestmark = pytest.mark.ui


def render(fake, ear: Ear) -> np.ndarray:
    """The A/B file the fake serves, decoded and downmixed as the ear hears it, at the ear's rate."""
    x, rate = sf.read(io.BytesIO(media.ab_wav(fake.bar_s, fake.bars)), dtype="float64")
    return resample(x.mean(axis=1), rate, ear.rate)


STARTUP_S = 0.1
CLOCK_SLACK_MS = 10      # how closely the audio clock maps onto the page's (render blocks, timer granularity)


def the_ear(ears: list[Ear]) -> Ear:
    """The context that played: the page makes one (and another only after being away)."""
    playing = [e for e in ears if e.loud()]
    assert len(playing) == 1, f"{len(ears)} contexts, {len(playing)} with sound"
    ear = playing[0]
    # Chromium skips a block or two while the recorder's worklet thread starts (the first ~0.1 s of a context);
    # after that, a hole would be a real dropout.
    assert all(t < max(STARTUP_S, ear.loud()[0][0]) for t, _ in ear.gaps), f"the recording has holes: {ear.gaps}"
    return ear


async def nothing_while_listening(page, ear: Ear) -> None:
    """No sound reached the speakers while the mic was open (on the page's clock, with the output's latency)."""
    sound = [(ear.perf(a), ear.perf(b)) for a, b in ear.loud()]
    spans = await mic_spans(page.page)
    assert spans, "the mic was never open"
    both = overlaps(sound, spans)
    ms = sum(b - a for a, b in both) * 1000
    assert ms <= CLOCK_SLACK_MS, f"heard {ms:.0f} ms of sound with the mic open"


@pytest.fixture
async def listener(chromium, fake):
    """The phone with no route settle at all, as on a desktop browser: the page waits out its output latency
    (~35 ms here) before it counts as idle, so the mic still never opens over the end of the sound."""
    page = await open_page(chromium, fake, query="settle=0")
    yield page
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_the_answer_is_heard_speech_then_music_and_never_over_the_open_mic(listener, fake):
    page = listener
    fake.turn_frames, fake.speech_s = 25, 1.0
    await page.page.click("#turn")
    await fake.expect(is_playback("idle", 2), timeout=15)
    await fake.expect(is_mic("open", "t2"))
    await asyncio.sleep(0.3)                                   # the reopened mic, a while, in silence
    ear = the_ear(await heard(page.page))
    _speech, music = [e for e in (await page.js("window.studio.engine.log")) if e["counted"]]

    # First the reply: a 220 Hz tone, about as long as the Mac said it, all of it before the music.
    spans = ear.loud(hold=0.01)
    said = [(a, b) for a, b in spans if b <= music["t0"]]
    assert said, f"no speech before the music: {spans}"
    start, end = said[0][0], said[-1][1]
    assert abs((end - start) - fake.speech_s) < 0.05, f"heard {end - start:.3f} s of a {fake.speech_s} s reply"
    assert abs(dominant_hz(ear.between(start, end), ear.rate) - 220) < 3

    # Then the A/B, twice, each pass the file itself, starting where the page scheduled it.
    ref = render(fake, ear)
    passes = find_passes(ear.samples, ref)
    assert len(passes.starts) == 2, passes
    assert min(passes.scores) > 0.99
    assert abs(ear.time(passes.starts[0]) - music["t0"]) < 1.5 / ear.rate
    assert passes.starts[1] - passes.starts[0] == len(ref)
    assert not np.any(np.abs(ear.samples[passes.starts[1] + len(ref):]) > 1e-3), "only silence after the second pass"

    await nothing_while_listening(page, ear)


async def test_loop_that_three_times_is_heard_three_times_to_the_sample(listener, fake):
    page = listener
    fake.turn_frames = 0                                       # listening, until the Mac plays something
    music = await fake.present_music()
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    mark = len(fake.inbox)
    await fake.play(music["seq"], 3)                           # "loop that three times"
    await fake.expect(is_mic("closed", "t1"), since=mark)
    await fake.expect(is_playback("idle", 1), since=mark, timeout=15)
    await fake.expect(is_mic("open", "t1"), since=mark)
    await asyncio.sleep(0.3)
    ear = the_ear(await heard(page.page))
    entry = (await page.js("window.studio.engine.log"))[-1]

    # Three passes of the file, back to back with no sample lost or repeated, from the scheduled start...
    ref = render(fake, ear)
    passes = find_passes(ear.samples, ref)
    assert len(passes.starts) == 3, passes
    assert min(passes.scores) > 0.99
    assert np.diff(passes.starts).tolist() == [len(ref), len(ref)], "each repeat starts where the last one ended"
    assert abs(ear.time(passes.starts[0]) - entry["t0"]) < 1.5 / ear.rate
    # ...and that is all there is: about three file lengths of sound, then silence.
    (_, end), = ear.loud()                                      # one span (its start is where the file gets loud)
    assert abs((end - ear.time(passes.starts[0])) - 3 * len(ref) / ear.rate) < 1.5 / ear.rate
    assert abs(end - entry["stopAt"]) < 1.5 / ear.rate

    await nothing_while_listening(page, ear)


async def test_stop_audio_is_silence_at_once(phone, fake):
    page = phone

    async def long_answer(_text):
        reply = await fake.upsert("agent", text="A long answer.", role="reply", audio=None, duration=None,
                                  streaming=False)
        await fake.speak(reply, 4.0)

    fake.script, fake.turn_frames = long_answer, 10
    await page.page.click("#turn")
    await fake.expect(is_playback("busy"))
    await asyncio.sleep(0.6)                                   # well into the answer
    await fake.stop_audio()
    await fake.expect(is_playback("idle"))
    await asyncio.sleep(0.5)
    ear = the_ear(await heard(page.page))
    entry = next(e for e in await page.js("window.studio.engine.log") if e["kind"] == "speech")
    assert entry["outcome"] == "stopped"

    # The sound ends within a render quantum (128 samples, ~3 ms) of the page stopping it, and stays ended.
    (start, end), = ear.loud()
    assert end - start > 0.3, "the answer was playing"
    assert end - entry["endedAt"] < 0.01, f"sound went on {1000 * (end - entry['endedAt']):.1f} ms after the stop"
    assert ear.time(len(ear.samples)) - end > 0.4, "the recording runs on, silent"


async def test_a_context_made_after_the_page_was_away_is_heard_too(phone, fake):
    page = phone
    fake.turn_frames = 10
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t2"), timeout=15)
    await page.js(BACKGROUND)
    mark = len(fake.inbox)
    await page.page.click(".msg--agent:not(.msg--narration) .play")
    await fake.expect(is_playback("idle"), since=mark, timeout=15)
    old, new = await heard(page.page)
    assert old.state == "closed" and new.state == "running"
    # The tapped reply (a 220 Hz tone) is heard on the new context.
    assert the_ear([new]) is new
    (start, end), = new.loud()
    assert abs((end - start) - fake.speech_s) < 0.03            # a replay is an MP3: its codec pads up to ~25 ms
    assert abs(dominant_hz(new.between(start, end), new.rate) - 220) < 3
