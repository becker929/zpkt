"""A turn, end to end against the scripted Mac: the mic, Claude working, speech, music, and the turn coming back."""

import asyncio

import numpy as np
import pytest

from conftest import PHONE, Page, open_page

pytestmark = pytest.mark.ui

MIC_RATE = 16_000
FRAME_BYTES = 1 + 320 * 2          # the channel byte, then 20 ms of s16le at 16 kHz


def mic_pcm(frames: list[bytes]) -> np.ndarray:
    return np.frombuffer(b"".join(f[1:] for f in frames), dtype="<i2").astype(np.float64) / 32768


def dominant_hz(samples: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.fft.rfftfreq(len(samples), 1 / rate)[np.argmax(spectrum[1:]) + 1])


def kinds(fake, kind, since=0):
    return fake.sent_of(kind, since)


async def test_a_whole_spoken_turn(phone, fake):
    page = phone
    fake.turn_frames = 100                                      # two seconds of talk, then "tomato"
    fake.speech_s = 1.5
    assert await page.js("!document.getElementById('empty').hidden"), "an empty chat invites you to start"

    # Start: the Mac offers the mic, the phone opens it and says how long that took.
    await page.page.click("#turn")
    await fake.expect(lambda m: m["type"] == "start")
    opened = await fake.expect(lambda m: m["type"] == "mic" and m["state"] == "open")
    assert opened["turn"] == "t1" and isinstance(opened["open_ms"], int)
    await page.wait("() => document.getElementById('turn').dataset.mode === 'listen'")      # drawn at the next frame
    assert await page.js("document.getElementById('phase').dataset.phase") == "listening"

    # The mic streams 20 ms frames: 0x01, then signed 16-bit little-endian PCM at 16 kHz.
    await fake.until(lambda: len(fake.mic_frames) >= 100)
    frames = fake.mic_frames[:100]
    assert all(f[0] == 0x01 and len(f) == FRAME_BYTES for f in frames)
    elapsed = fake.mic_times[99] - fake.mic_times[0]
    assert 99 * 0.020 * 0.75 < elapsed < 99 * 0.020 * 1.4, f"100 frames took {elapsed:.2f} s; 16 kHz needs about 2 s"
    pcm = mic_pcm(frames[20:])                                  # past the start, where the filter has settled
    assert np.sqrt(np.mean(pcm ** 2)) > 0.01, "the frames carry the tone, not silence"
    assert abs(dominant_hz(pcm, MIC_RATE) - 1000) < 15, "a 1 kHz tone reads as 1 kHz at 16 kHz"

    # Live captions follow the voice.
    await page.wait("() => document.getElementById('live-caption').textContent.startsWith('make the kick')")

    # "Tomato": the Mac unlistens; the phone closes the mic, keeping its one stream for the next turn, disabled.
    await fake.expect(lambda m: m["type"] == "mic" and m["state"] == "closed")
    await page.wait("() => window.__captured.length === 1 && window.__captured[0].getTracks().every("
                    "(t) => t.readyState === 'live' && !t.enabled)")

    # Claude works: its thinking, three tool calls and a screenshot fold into one trace; the narration arrives.
    await page.wait("() => document.querySelector('.trace .trace-meta')?.textContent === '3 steps · 1 shot'")
    assert await page.js("document.querySelector('.trace').dataset.status") in ("running", "ok")
    await page.wait("() => document.querySelector('.msg--narration .inline-text')?.textContent.includes('two levels')")
    await page.wait("() => document.querySelector('.ti--shots img')?.getAttribute('src')")

    # Claude answers: the speech stream plays (the reply's bubble animates), then the A/B's intro, then it plays twice.
    busy = await fake.expect(lambda m: m["type"] == "playback" and m["state"] == "busy")
    assert busy["done"] == 0
    await page.wait("() => document.querySelector('.msg--agent:not(.msg--narration).is-playing')")
    await page.wait("() => document.getElementById('phase').dataset.phase === 'speaking'")
    sides = set()
    for _ in range(100):                                       # the A/B lights A and B in turn, every bar
        side, pill = await page.js("[document.querySelector('.msg--music.is-playing')?.dataset.side ?? null, "
                                   "document.getElementById('phase').dataset.side ?? null]")
        if side and side == pill:
            sides.add(side)
        if sides == {"A", "B"}:
            break
        await asyncio.sleep(0.04)
    assert sides == {"A", "B"}

    # Everything played: idle, with all three items counted, and the mic is offered again.
    idle = await fake.expect(lambda m: m["type"] == "playback" and m["state"] == "idle" and m["done"] == 3, timeout=15)
    assert idle
    log = await page.js("window.studio.engine.log")
    speech, intro, music = [e for e in log if e["counted"]][:3]
    assert speech["kind"] == "speech" and speech["outcome"] == "played"
    assert intro["kind"] == "speech" and intro["seq"] == music["seq"] and intro["outcome"] == "played"
    assert music["kind"] == "music" and music["outcome"] == "played" and music["loops"] == 2
    assert abs(music["stopAt"] - music["t0"] - 2 * music["duration"]) < 1e-6, "exactly two passes, sample-accurate"
    assert music["endedAt"] - music["t0"] >= 2 * music["duration"] - 0.01
    reopened = await fake.expect(lambda m: m["type"] == "mic" and m["state"] == "open" and m["turn"] == "t2")
    assert reopened
    # ...on the kept stream: no second getUserMedia, so no second permission prompt.
    await fake.until(lambda: sum(m["name"] == "mic_open" for m in fake.marks) == 2)
    assert [m["kept"] for m in fake.marks if m["name"] == "mic_open"] == [False, True]
    assert await page.js("window.__captured.length") == 1

    # The phone timed its part of the turn.
    names = {m["name"] for m in fake.marks}
    assert {"mic_open", "first_speech_audio", "music_first_play", "route_settle"} <= names
    assert {m["mode"] for m in fake.marks if m["name"] == "route_settle"} == {"playback", "play-and-record"}
    assert all(m["turn"] for m in fake.marks)


def is_mic(state, turn=None):
    return lambda m: m["type"] == "mic" and m["state"] == state and (turn is None or m["turn"] == turn)


def is_playback(state, done=None):
    return lambda m: m["type"] == "playback" and m["state"] == state and (done is None or m["done"] == done)


async def test_a_typed_turn(phone, fake):
    page = phone
    fake.turn_frames = 0                                        # only a typed turn ends this one
    await page.page.click("#turn")
    await fake.expect(is_mic("open"))
    await page.page.click("#keyboard")
    assert await page.js("document.activeElement.id") == "composer-input"
    await page.page.fill("#composer-input", "Try the kick at minus two dB")
    await page.page.press("#composer-input", "Enter")
    said = await fake.expect(lambda m: m["type"] == "say")
    assert said["text"] == "Try the kick at minus two dB"
    assert await page.js("document.getElementById('composer').hidden")
    # A typed turn shows its words as they are: no recording, nothing folded.
    await page.wait("() => document.querySelector('.msg--user.is-typed .inline-text')?.textContent"
                    " === 'Try the kick at minus two dB'")
    assert await page.js("document.querySelector('.msg--user.is-typed .voice').hidden")
    assert await page.js("document.querySelector('.msg--user.is-typed .caption').hidden")
    # The Mac took the turn, so the mic closed; Claude's answer plays and the turn comes back.
    await fake.expect(is_mic("closed"))
    await fake.expect(is_playback("idle", 3), timeout=15)
    await fake.expect(is_mic("open", "t2"))


async def test_interrupting_claude_while_it_works(phone, fake):
    page = phone
    never = asyncio.Event()

    async def long_render(_text):
        await fake.set_phase("working", "Render the A/B in Live")
        await fake.upsert("activity", tool="Bash", title="Render the A/B in Live", status="running", detail="render.py")
        await never.wait()

    fake.script, fake.turn_frames = long_render, 10
    await page.page.click("#turn")
    await page.wait("() => document.getElementById('turn').dataset.mode === 'work'")
    await page.wait("() => document.getElementById('phase-detail').textContent === 'Render the A/B in Live'")
    assert await page.js("document.getElementById('phase').dataset.phase") == "working"
    assert await page.js("document.querySelector('.act').dataset.status") == "running"
    await page.page.click("#turn")
    await fake.expect(lambda m: m["type"] == "interrupt")
    await fake.expect(is_mic("open", "t2"))                     # the turn is Anthony's again
    await page.wait("() => document.getElementById('turn').dataset.mode === 'listen'")


async def test_cutting_into_the_answer(phone, fake):
    page = phone
    fake.turn_frames, fake.speech_s = 10, 4.0                   # a long answer, still playing when Claude is done
    await page.page.click("#turn")
    await fake.expect(is_playback("busy"))
    await page.wait("() => document.getElementById('turn').dataset.mode === 'answer'")
    mark = len(fake.inbox)
    await page.page.click("#turn")
    # Silence at once, and all three items count as done: the speech that was cut, and the render's intro and the
    # render still queued.
    idle = await fake.expect(is_playback("idle"), since=mark)
    assert idle["done"] == 3
    await fake.expect(lambda m: m["type"] == "interrupt", since=mark)
    log = await page.js("window.studio.engine.log")
    assert [(e["kind"], e["outcome"]) for e in log] == [("speech", "stopped"), ("speech", "stopped"),
                                                        ("music", "stopped")]
    await fake.expect(is_mic("open", "t2"))


async def test_autoplay_off_still_plays_what_is_asked_for(phone, fake):
    page = phone
    fake.turn_frames = 10
    await page.page.click("#autoplay")
    prefs = await fake.expect(lambda m: m["type"] == "prefs")
    assert prefs["prefs"] == {"autoplay": False, "shots": "major", "handsfree": True}
    await page.wait("() => document.getElementById('autoplay').getAttribute('aria-checked') === 'false'")

    # Nothing is streamed or played by itself: the turn comes straight back, the bubbles wait to be tapped.
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t2"), timeout=15)
    assert await page.js("window.studio.engine.log.length") == 0
    await page.wait("() => document.querySelector('.msg--agent:not(.msg--narration)[data-audio] .play:not([hidden])')")

    # "Loop that three times": an explicit play still plays, exactly three times, with the mic closed meanwhile.
    music = next(m for m in fake.messages if m["kind"] == "music")
    mark = len(fake.inbox)
    await fake.play(music["seq"], 3)
    await fake.expect(is_mic("closed"), since=mark)
    await fake.expect(is_playback("idle", 1), since=mark, timeout=15)
    entry = (await page.js("window.studio.engine.log"))[-1]
    assert entry["loops"] == 3 and entry["outcome"] == "played"
    assert abs(entry["stopAt"] - entry["t0"] - 3 * entry["duration"]) < 1e-6
    await fake.expect(is_mic("open"), since=mark)

    # A tapped bubble plays at once and is not counted.
    mark = len(fake.inbox)
    await page.page.click(".msg--agent:not(.msg--narration) .play")
    await fake.expect(is_playback("busy"), since=mark)
    idle = await fake.expect(is_playback("idle"), since=mark)
    assert idle["done"] == 1


async def test_tapping_play_while_listening_closes_the_mic_until_it_is_done(phone, fake):
    page = phone
    fake.turn_frames = 0
    music = await fake.present_music()
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    card = f'[data-seq="{music["seq"]}"]'
    await page.page.click(f"{card} [data-action='loops-up']")
    assert await page.js(f"document.querySelector('{card} .loops-value').textContent") == "×2"
    mark = len(fake.inbox)
    await page.page.click(f"{card} .play")
    await fake.expect(is_mic("closed", "t1"), since=mark)
    busy = await fake.expect(is_playback("busy"), since=mark)
    assert busy["done"] == 0
    await page.wait("() => document.getElementById('turn').dataset.mode === 'playback'")
    idle = await fake.expect(is_playback("idle"), since=mark, timeout=10)
    assert idle["done"] == 0                                    # a tap is not one of the Mac's items
    entry = (await page.js("window.studio.engine.log"))[-1]
    assert entry["counted"] is False and entry["loops"] == 2 and entry["outcome"] == "played"
    await fake.expect(is_mic("open", "t1"), since=mark)        # still listening: the mic opens again


async def test_typing_without_start_takes_the_speaker(phone, fake):
    # Typing is the first tap: the page never pressed Start, and the answer still plays here.
    page = phone
    await page.page.click("#keyboard")
    await page.page.fill("#composer-input", "Render the C section as it is")
    await page.page.press("#composer-input", "Enter")
    await fake.expect(lambda m: m["type"] == "say")
    assert not any(m["type"] == "start" for m in fake.inbox)
    await fake.expect(is_playback("idle", 3), timeout=15)
    log = await page.js("window.studio.engine.log")
    assert [(e["kind"], e["outcome"]) for e in log] == [("speech", "played"), ("speech", "played"), ("music", "played")]
    await fake.expect(is_mic("open", "t2"))                    # then the turn comes round, as after Start




async def test_with_keep_the_mic_off_each_turn_stops_its_tracks_and_asks_again(phone, fake):
    page = phone
    fake.turn_frames = 25
    await page.js("window.studio.prefs.set('keepMic', false)")
    await page.page.click("#turn")
    await fake.expect(is_mic("closed", "t1"))
    await page.wait("() => window.__captured.length > 0 && window.__captured.every("
                    "(s) => s.getTracks().every((t) => t.readyState === 'ended'))")
    await fake.expect(is_mic("open", "t2"), timeout=15)
    assert await page.js("window.__captured.length") == 2      # a new getUserMedia: a prompt, where a browser asks
    assert not await page.js("window.studio.mic.held")

PILL = "[document.getElementById('phase').dataset.phase, document.getElementById('phase-text').textContent, document.getElementById('phase-detail').textContent]"


async def test_a_second_page_says_the_mic_is_on_another_page_and_can_take_it(phone, chromium, fake):
    fake.turn_frames = 0                                       # listening until a page ends the turn
    other = await open_page(chromium, fake)
    await phone.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await other.wait("() => document.getElementById('phase-detail').textContent")
    assert await other.js(PILL) == ["paused", "Listening", "on another page"]
    await phone.wait("() => document.getElementById('phase').dataset.phase === 'listening'")     # the next frame
    assert await phone.js(PILL) == ["listening", "Listening", ""]

    # The other page takes it: the first one closes its mic and says where it went.
    mark = len(fake.inbox)
    await other.page.click("#turn")
    await fake.expect(is_mic("closed", "t1"), since=mark)
    await phone.wait("() => document.getElementById('phase-detail').textContent")
    assert await phone.js(PILL) == ["paused", "Listening", "on another page"]
    assert await phone.js("window.studio.turn.mode") == "start"                    # a tap takes it back
    assert other.errors == []
    await other.page.context.close()

BACKGROUND = """() => {
  window.__before = window.studio.engine.context;
  for (const state of ['hidden', 'visible']) {
    Object.defineProperty(document, 'visibilityState', { configurable: true, get: () => state });
    document.dispatchEvent(new Event('visibilitychange'));
  }
}"""


async def test_audio_comes_back_after_the_page_was_away(phone, fake):
    page = phone
    fake.turn_frames = 10
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t2"), timeout=15)
    # Another app, then back: the context can't be trusted, and the page says so.
    await page.js(BACKGROUND)
    await page.wait("() => [...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('paused'))")
    # The next tap replaces it, and a tapped bubble plays on the new one.
    mark = len(fake.inbox)
    await page.page.click(".msg--agent:not(.msg--narration) .play")
    await fake.expect(is_playback("idle"), since=mark, timeout=15)
    assert await page.js("window.studio.engine.context !== window.__before")
    assert await page.js("window.__before.state") == "closed"
    assert (await page.js("window.studio.engine.log"))[-1]["outcome"] == "played"
    await page.wait("() => ![...document.querySelectorAll('.toast')].some((t) => t.textContent.includes('paused'))")


# A phone with its own mic and a car's: getUserMedia records which device each call asked for.
TWO_MICS = """(() => {
  const list = navigator.mediaDevices.enumerateDevices.bind(navigator.mediaDevices);
  navigator.mediaDevices.enumerateDevices = async () => [
    ...(await list()),
    { kind: 'audioinput', label: 'Car Kit Hands-Free', deviceId: 'car', groupId: 'c' },
    { kind: 'audioinput', label: 'iPhone Microphone', deviceId: 'phone', groupId: 'p' },
  ];
  const gum = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
  window.__asked = [];
  navigator.mediaDevices.getUserMedia = async (c) => {
    const id = c.audio?.deviceId?.exact ?? null;
    window.__asked.push(id);
    const stream = await gum({ audio: true });
    for (const t of stream.getAudioTracks()) {
      const settings = t.getSettings.bind(t);
      t.getSettings = () => ({ ...settings(), deviceId: id ?? 'car' });
    }
    return stream;
  };
})();"""


async def test_the_studio_mic_records_from_the_phone_so_bluetooth_only_plays(chromium, fake):
    fake.turn_frames = 25
    context = await chromium.new_context(permissions=["microphone"], **PHONE)
    await context.add_init_script(TWO_MICS)
    page = Page(await context.new_page(), fake)
    await page.open()
    await page.page.click("#turn")
    await fake.expect(is_mic("open", "t1"))
    await fake.expect(is_mic("open", "t2"), timeout=15)
    # The first ask can't name a device (names come with permission); after it, every stream is the phone's own,
    # and the kept one is reused.
    asked = await page.js("window.__asked")
    assert asked[-1] == "phone" and asked.count("phone") == 1, asked
    assert page.errors == []
    await context.close()
