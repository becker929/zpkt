"""The mic tells the truth and comes back: the dock says "wait" until the mic's first frame is on its way to the Mac
and "Go ahead" after (with the ready cue), and a mic the phone took away (another app, a dead context, a failed
getUserMedia, a track that ended or went quiet) opens again in the same turn, with every failure in the Mac's log."""

import asyncio

import pytest

from conftest import IPHONE_15, open_page
from heard import dominant_hz, heard
from test_turn import PILL, is_mic

pytestmark = pytest.mark.ui

DOCK = "[document.getElementById('turn').dataset.mode, document.getElementById('turn-hint').textContent]"
WAIT = ["wait", "One moment…"]
GO = ["listen", "Go ahead · say “tomato” to send"]
RESUME = ["resume", "Tap to turn the mic back on"]
CUE_HZ = (659.25, 987.77)

# What the page sends, in order (each JSON message's type and state, and its first binary frame), every mode the
# turn button shows, with its hint, and every state of the phase pill, each with when (performance clock, ms).
RECORD = """() => {
  window.__sent = [];
  const send = WebSocket.prototype.send;
  WebSocket.prototype.send = function (data) {
    if (typeof data === 'string') {
      const msg = JSON.parse(data);
      window.__sent.push([`${msg.type}:${msg.state ?? ''}`, performance.now()]);
    } else if (!window.__sent.some(([what]) => what === 'frame')) {
      window.__sent.push(['frame', performance.now()]);
    }
    return send.call(this, data);
  };
  window.__modes = [];
  const turn = document.getElementById('turn');
  const hint = document.getElementById('turn-hint');
  const note = () => {
    const mode = turn.dataset.mode;
    if (window.__modes.at(-1)?.[0] !== mode) window.__modes.push([mode, hint.textContent, performance.now()]);
  };
  new MutationObserver(note).observe(turn, { attributes: true, attributeFilter: ['data-mode'] });
  note();
  window.__pills = [];
  const pill = document.getElementById('phase');
  new MutationObserver(() => {
    if (window.__pills.at(-1)?.[0] !== pill.dataset.phase) window.__pills.push([pill.dataset.phase, performance.now()]);
  }).observe(pill, { attributes: true, attributeFilter: ['data-phase'] });
}"""

# getUserMedia, slowed down (a phone's first ask takes seconds), or failing the next calls with the errors named.
# On the prototype, as CAPTURE does (conftest.py): WebKit may forget a property set on navigator.mediaDevices.
SLOW_GUM = """(ms) => {
  const gum = MediaDevices.prototype.getUserMedia;
  MediaDevices.prototype.getUserMedia = async function (c) {
    await new Promise((r) => setTimeout(r, ms));
    return gum.call(this, c);
  };
}"""
FAIL_GUM = """(names) => {
  const gum = MediaDevices.prototype.getUserMedia;
  MediaDevices.prototype.getUserMedia = async function (c) {
    const name = names.shift();
    if (name) throw new DOMException(`the test made it fail (${name})`, name);
    return gum.call(this, c);
  };
}"""


def away(state: str) -> str:
    """The page goes to the background ('hidden') or comes back ('visible'), as far as the page can tell."""
    return f"""() => {{
  Object.defineProperty(document, 'visibilityState', {{ configurable: true, get: () => '{state}' }});
  document.dispatchEvent(new Event('visibilitychange'));
}}"""


# What iOS does to a page's capture in the background: every track it handed out ends.
END_TRACKS = """() => window.__captured.forEach((s) => s.getTracks().forEach((t) => {
  t.stop();
  t.dispatchEvent(new Event('ended'));
}))"""


def marks(fake, name: str, turn: str | None = None) -> list[dict]:
    return [m for m in fake.marks if m["name"] == name and (turn is None or m["turn"] == turn)]


def opened(fake, since: int = 0) -> list[dict]:
    return [m for m in fake.sent_of("mic", since) if m["state"] == "open"]


def logs(fake, since: int = 0) -> list[str]:
    return [m["text"] for m in fake.sent_of("log", since)]


async def frames_flow(fake, n: int = 10, timeout: float = 10) -> None:
    """`n` more mic frames reach the Mac."""
    have = len(fake.mic_frames)
    await fake.until(lambda: len(fake.mic_frames) >= have + n, timeout)


def device(either):
    return IPHONE_15 if either.browser_type.name == "webkit" else None


async def test_the_dock_waits_for_the_first_frame_then_says_go_ahead_with_the_cue(either, fake):
    page = await open_page(either, fake, device=device(either), ready_cue=True)
    fake.turn_frames = 0
    await page.js(RECORD)
    await page.js(SLOW_GUM, 700)                            # the ask takes a while, as a phone's does
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await frames_flow(fake)
    await page.wait(f"() => {DOCK}[0] === 'listen'")
    assert await page.js(DOCK) == GO

    # "One moment…" for as long as nothing reached the Mac; "Go ahead" from the first frame on, not before.
    modes = await page.js("window.__modes")
    sent = await page.js("window.__sent")
    first_frame = next(t for what, t in sent if what == "frame")
    go = next(i for i, m in enumerate(modes) if m[0] == "listen")
    waited = [m for m in modes[:go] if m[0] == "wait"]
    assert waited and waited[0][1] == WAIT[1], modes
    assert modes[go][2] - waited[0][2] > 500, f"the wait showed for only {modes[go][2] - waited[0][2]:.0f} ms"
    assert modes[go][2] >= first_frame, "it said go ahead before the mic was heard"
    pills = await page.js("window.__pills")
    assert "waiting" in [p for p, _ in pills], pills
    assert next(t for p, t in pills if p == "listening") >= first_frame, "it said listening before the mic was heard"
    order = [what for what, _ in sent]
    assert order.index("frame") < order.index("mic:open"), "the Mac hears the mic is open with its first frame"

    # The ready cue: once, at the switch, two soft notes rising, about 150 ms in all.
    await asyncio.sleep(0.4)
    ears = [e for e in await heard(page.page) if e.loud()]
    assert len(ears) == 1, "only the engine's context made a sound"
    ear = ears[0]
    (start, end), = ear.loud()
    assert 0.1 < end - start < 0.2, f"the cue lasted {end - start:.3f} s"
    assert abs(dominant_hz(ear.between(start, start + 0.05), ear.rate) - CUE_HZ[0]) < 25
    assert abs(dominant_hz(ear.between(start + 0.07, start + 0.14), ear.rate) - CUE_HZ[1]) < 25
    assert ear.perf(start) * 1000 > first_frame - 15, "the cue sounded before the mic was heard"
    assert len(marks(fake, "ready_cue", "t1")) == 1 and len(marks(fake, "mic_ready", "t1")) == 1
    assert marks(fake, "ready_cue", "t1")[0]["ms"] >= marks(fake, "mic_ready", "t1")[0]["ms"]
    # It is not one of the engine's items: nothing was counted or played, and the Mac never heard 'busy'.
    assert await page.js("window.studio.engine.log.length") == 0
    assert not fake.sent_of("playback")
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_with_the_ready_sound_off_the_mic_opens_in_silence(chromium, fake):
    page = await open_page(chromium, fake, ready_cue=True)
    fake.turn_frames = 0
    await page.page.click("#menu-open")
    assert await page.js("document.getElementById('ready-sound').getAttribute('aria-checked')") == "true"
    await page.page.click("#ready-sound")
    assert await page.js("document.getElementById('ready-sound').getAttribute('aria-checked')") == "false"
    assert await page.js("window.studio.prefs.get('readySound')") is False
    await page.page.click("#menu [data-close]")
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await frames_flow(fake)
    await asyncio.sleep(0.4)
    assert not any(e.loud() for e in await heard(page.page)), "nothing sounds while the mic is open"
    assert marks(fake, "mic_ready", "t1") and not marks(fake, "ready_cue")
    assert not fake.sent_of("prefs"), "the ready sound is the phone's own business"
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_after_another_app_the_tap_it_asks_for_brings_the_mic_back(either, fake):
    page = await open_page(either, fake, device=device(either), ready_cue=True)
    fake.turn_frames = 0
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await frames_flow(fake)

    # Away, as iOS does it: the page is hidden, every capture track ends, the context is suspended. The mic closes
    # cleanly (the Mac hears so) and lets the kept stream go.
    mark = len(fake.inbox)
    await page.js(away("hidden"))
    await page.js(END_TRACKS)
    await page.js("window.studio.engine.context.suspend()")
    await fake.expect(is_mic("closed", "t1"), since=mark)
    assert not await page.js("window.studio.mic.held")

    # Back, still t1: the context needs a tap before it can be trusted (audio.js), and the page asks for one. It
    # says nowhere that it is listening, and nothing reaches the Mac.
    mark = len(fake.inbox)
    await page.js("() => { window.__before = window.studio.engine.context; }")
    await page.js(away("visible"))
    await page.wait(f"() => {DOCK}[0] === 'resume'")
    assert await page.js(DOCK) == RESUME
    assert await page.js(PILL) == ["paused", "Mic off", "tap to turn it back on"]
    assert any("waits for a tap: the page was away" in text for text in logs(fake, mark)), logs(fake, mark)
    heard_before = len(fake.mic_frames)
    await asyncio.sleep(0.5)
    assert len(fake.mic_frames) == heard_before and not opened(fake, mark)

    # The tap it asks for makes a new context, and the mic opens on it (worklet and all) in the same turn. The
    # turn is not ended.
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"), since=mark)
    await frames_flow(fake)
    await page.wait(f"() => {DOCK}[0] === 'listen'")
    assert await page.js(PILL) == ["listening", "Listening", ""]
    assert not fake.sent_of("end_turn", mark)
    assert await page.js("window.studio.engine.context !== window.__before && window.__before.state === 'closed'")
    assert marks(fake, "mic_worklet", "t1")[-1]["loaded"] is True, "the new context loads the worklet"
    assert marks(fake, "mic_gum", "t1"), "the kept stream was let go, so it asked afresh"
    assert marks(fake, "mic_ready", "t1")[-1]["after"] == "tap"
    assert len(marks(fake, "ready_cue", "t1")) == 2                  # the cue says it hears again

    # Away again, and meanwhile the Mac moves on (as after "I didn't catch anything"): the new turn's listen finds
    # the context needing a tap and says so. Any tap will do.
    await page.js(away("hidden"))
    mark = len(fake.inbox)
    await fake.next_turn()
    await page.js(away("visible"))
    await page.wait(f"() => {DOCK}[0] === 'resume'")
    assert not opened(fake, mark)
    await page.page.click("#phase")
    await fake.expect(is_mic("open", "t2"), since=mark)
    await frames_flow(fake)
    await page.wait(f"() => {DOCK}[0] === 'listen'")
    assert not fake.sent_of("end_turn", mark)
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_an_interrupted_context_stops_the_mic_until_it_resumes_and_a_dead_one_until_a_tap(either, fake):
    page = await open_page(either, fake, device=device(either))
    fake.turn_frames = 0
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await frames_flow(fake)

    # A call interrupts the context while the page is in view: at once the page stops saying go ahead.
    mark = len(fake.inbox)
    await page.js("window.studio.engine.context.suspend()")
    await page.wait(f"() => {DOCK}[0] === 'resume'")
    await fake.expect(is_mic("closed", "t1"), since=mark)
    assert any("stopped hearing (paused)" in text for text in logs(fake, mark)), logs(fake, mark)
    # The call ends and the context resumes by itself: so does the mic, with no tap, on the stream it kept.
    await page.js("window.studio.engine.context.resume()")
    await fake.expect(is_mic("open", "t1"), since=mark)
    await frames_flow(fake)
    await page.wait(f"() => {DOCK}[0] === 'listen'")
    assert marks(fake, "mic_held", "t1")[-1]["kept"] is True

    # The context dies: the page asks for a tap, which makes a new one, and the mic opens on it.
    mark = len(fake.inbox)
    await page.js("window.studio.engine.context.close()")
    await page.wait(f"() => {DOCK}[0] === 'resume'")
    assert any("stopped hearing (context)" in text for text in logs(fake, mark)), logs(fake, mark)
    assert any("waits for a tap: the audio context is closed" in text for text in logs(fake, mark)), logs(fake, mark)
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"), since=mark)
    await frames_flow(fake)
    await page.wait(f"() => {DOCK}[0] === 'listen'")
    assert await page.js("window.studio.engine.context.state") == "running"
    assert not fake.sent_of("end_turn")
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_a_mic_that_fails_once_is_tried_again_and_the_turn_is_heard(either, fake):
    page = await open_page(either, fake, device=device(either))
    fake.turn_frames = 0
    await page.js("window.studio.prefs.set('keepMic', false)")    # every open asks getUserMedia
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await page.js(FAIL_GUM, ["NotReadableError"])                # the device was busy for a moment
    mark = len(fake.inbox)
    await fake.next_turn()
    await fake.expect(is_mic("open", "t2"), since=mark)
    await frames_flow(fake)
    failed = [text for text in logs(fake, mark) if "NotReadableError" in text]
    assert len(failed) == 1, logs(fake, mark)
    assert "mic t2: didn't open (gum)" in failed[0] and "trying again" in failed[0]
    assert "page visible" in failed[0] and "context running" in failed[0]
    assert marks(fake, "mic_ready", "t2")[-1]["after"] == "retry"
    assert not await page.js("document.querySelector('.toast[data-key=\"mic\"]')"), "a retry that works is no news"
    assert page.errors == [], f"console errors: {page.errors}"
    await page.page.context.close()


async def test_a_blocked_mic_is_in_the_macs_log_and_waits_for_a_tap(phone, fake):
    page = phone
    fake.turn_frames = 0
    await page.js("window.studio.prefs.set('keepMic', false)")
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await page.js(FAIL_GUM, ["NotAllowedError"])                 # not passing: no retry by itself
    mark = len(fake.inbox)
    await fake.next_turn()
    await page.wait(f"() => {DOCK}[0] === 'resume'")
    failed = [text for text in logs(fake, mark) if "NotAllowedError" in text]
    assert len(failed) == 1 and "didn't open (gum)" in failed[0] and "trying again" not in failed[0], failed
    await page.wait("() => document.querySelector('.toast[data-key=\"mic\"]')?.textContent.includes('blocked')")
    await asyncio.sleep(0.6)
    assert not opened(fake, mark), "no retry without a tap"

    await page.page.click("#turn")                              # allowed again: the tap tries once more
    await fake.expect(is_mic("open", "t2"), since=mark)
    await frames_flow(fake)


async def test_a_track_that_ends_or_goes_quiet_mid_turn_is_noticed_and_reopened(phone, fake):
    page = phone
    fake.turn_frames = 0
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await frames_flow(fake)

    # The track ends under the page (a call, another app taking the mic): it is let go and the mic opens afresh.
    mark = len(fake.inbox)
    await page.js(END_TRACKS)
    await fake.expect(is_mic("closed", "t1"), since=mark)
    await fake.expect(is_mic("open", "t1"), since=mark)
    await frames_flow(fake)
    assert any("stopped hearing (ended)" in text for text in logs(fake, mark)), logs(fake, mark)
    assert marks(fake, "mic_ready", "t1")[-1]["after"] == "ended"

    # The track is muted: at once the dock stops saying go ahead; after a second muted, the mic opens afresh.
    mark = len(fake.inbox)
    await page.js("""() => {
      const track = window.__captured.at(-1).getAudioTracks()[0];
      Object.defineProperty(track, 'muted', { configurable: true, get: () => true });
      track.dispatchEvent(new Event('mute'));
    }""")
    await page.wait(f"() => {DOCK}[0] === 'wait'")
    await fake.expect(is_mic("open", "t1"), since=mark)
    await frames_flow(fake)
    await page.wait(f"() => {DOCK}[0] === 'listen'")
    assert any("stopped hearing (muted)" in text for text in logs(fake, mark)), logs(fake, mark)
