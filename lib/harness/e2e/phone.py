"""The virtual user and their phone: the studio page in an iPhone-sized browser, instrumented.

Three scripts go into the page before its own code runs:
- the ear (tests/ui/heard.py, MUTE): records everything the page sends to its speakers;
- VOICE: getUserMedia gives the page a stream the user's lines are played into (window.__voice.say), keeps when
  each stream was open, can fail on demand, and can end every capture track as iOS does when the page goes to the
  background; it also owns document.visibilityState, so a run can switch apps;
- WIRE: every WebSocket message both ways, with the page's clock, and when mic frames and speech frames went by.

The user behaves like Anthony: speaks only once the page says the mic is listening, waits for the answer to finish,
taps what is on the screen, and taps the page again when it asks for a tap after an app switch.
"""

from __future__ import annotations

import asyncio
import json
import secrets
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import voice
from .record import Recording

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tests" / "ui"))
from heard import MUTE  # noqa: E402

IPHONE = {"viewport": {"width": 393, "height": 659}, "screen": {"width": 393, "height": 852},
          "device_scale_factor": 3, "is_mobile": True, "has_touch": True}

VOICE = """
(() => {
  const Real = window.AudioContext || window.webkitAudioContext;
  // delayMs: how long getUserMedia takes. An iPhone takes about 3 s to give the page its mic (studio's timings).
  const v = (window.__voice = { streams: [], spans: [], said: [], fail: [], delayMs: 3000 });
  let ctx = null;
  let bus = null;
  const ensure = async () => {
    if (!ctx) { ctx = new Real(); bus = ctx.createGain(); }
    if (ctx.state !== 'running') await ctx.resume().catch(() => {});
    return ctx;
  };
  const enabled = Object.getOwnPropertyDescriptor(MediaStreamTrack.prototype, 'enabled');
  // On the prototype: WebKit can hand the page a new navigator.mediaDevices, which would lose an own property.
  MediaDevices.prototype.getUserMedia = async function () {
    if (v.fail.length) {
      const f = v.fail.shift();
      throw new DOMException(f.message || 'failed on purpose', f.name || 'NotReadableError');
    }
    await new Promise((resolve) => setTimeout(resolve, v.delayMs));
    await ensure();
    const dest = ctx.createMediaStreamDestination();
    bus.connect(dest);
    const stream = dest.stream;
    v.streams.push(stream);
    let span = { open: performance.now(), close: null };
    v.spans.push(span);
    for (const track of stream.getTracks()) {
      const stop = track.stop.bind(track);
      track.stop = () => { span.close ??= performance.now(); stop(); };
      Object.defineProperty(track, 'enabled', {
        get() { return enabled.get.call(this); },
        set(on) {
          if (!on) span.close ??= performance.now();
          else if (span.close !== null) v.spans.push(span = { open: performance.now(), close: null });
          enabled.set.call(this, on);
        },
      });
    }
    return stream;
  };
  // A line, played into every stream the page has; resolves when it has been said.
  v.say = async (url) => {
    await ensure();
    const buf = await ctx.decodeAudioData(await (await fetch(url)).arrayBuffer());
    const src = ctx.createBufferSource();
    src.buffer = buf;
    src.connect(bus);
    v.said.push({ url, at: performance.now(), ms: buf.duration * 1000 });
    src.start();
    return new Promise((resolve) => { src.onended = () => resolve(buf.duration); });
  };
  // iOS ends every capture track of a page that goes to the background.
  v.kill = () => {
    for (const s of v.streams) for (const t of s.getTracks()) {
      if (t.readyState === 'live') { t.stop(); t.dispatchEvent(new Event('ended')); }
    }
  };
  let visibility = 'visible';
  Object.defineProperty(Document.prototype, 'visibilityState', { configurable: true, get: () => visibility });
  Object.defineProperty(Document.prototype, 'hidden', { configurable: true, get: () => visibility === 'hidden' });
  v.setVisible = (on) => {
    visibility = on ? 'visible' : 'hidden';
    document.dispatchEvent(new Event('visibilitychange'));
    window.dispatchEvent(new Event(on ? 'pageshow' : 'pagehide'));
  };
})();
"""

WIRE = """
(() => {
  const w = (window.__wire = { log: [], micFrames: 0, lastMicFrame: 0, firstMicFrame: [], speech: {} });
  const Real = window.WebSocket;
  window.WebSocket = class extends Real {
    constructor(...args) {
      super(...args);
      this.addEventListener('message', (e) => {
        const t = performance.now();
        if (typeof e.data === 'string') {
          try { w.log.push({ dir: 'in', t, msg: JSON.parse(e.data) }); } catch {}
          return;
        }
        const head = new Uint8Array(e.data instanceof ArrayBuffer ? e.data : new ArrayBuffer(0), 0, 5);
        if (head[0] === 0x02) {
          const id = ((head[1] << 24) | (head[2] << 16) | (head[3] << 8) | head[4]) >>> 0;
          const s = (w.speech[id] ??= { first: t, last: t, frames: 0 });
          s.last = t;
          s.frames += 1;
        }
      });
    }
    send(data) {
      const t = performance.now();
      if (typeof data === 'string') {
        try { w.log.push({ dir: 'out', t, msg: JSON.parse(data) }); } catch {}
      } else {
        if (!w.micFrames || t - w.lastMicFrame > 500) w.firstMicFrame.push(t);
        w.micFrames += 1;
        w.lastMicFrame = t;
      }
      return super.send(data);
    }
  };
})();
"""

# The ear's recordings so far, handed over and dropped from the page (a long run would not fit in one transfer).
DRAIN = """() => {
  const b64 = (f32) => {
    const bytes = new Uint8Array(f32.buffer, f32.byteOffset, f32.byteLength);
    let s = '';
    for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
    return btoa(s);
  };
  return (window.__ears || []).map((ear) => {
    const chunks = ear.chunks.splice(0);
    const n = chunks.reduce((a, c) => a + c.data.length, 0);
    const all = new Float32Array(n);
    let at = 0;
    for (const c of chunks) { all.set(c.data, at); at += c.data.length; }
    return { id: ear.id, rate: ear.rate, error: ear.error, outputLatency: ear.ctx.outputLatency || ear.ctx.baseLatency || 0,
             times: chunks.map((c) => c.t), sizes: chunks.map((c) => c.data.length),
             heardAt: ear.heardAt.splice(0), now: ear.now.splice(0), samples: b64(all) };
  });
}"""


# The page says "Go ahead": the dock is in its listening mode, which it shows only once mic frames flow. The user
# starts talking then, as Anthony would; the frames check makes a dishonest "Go ahead" a lost first word.
LISTENING = """() => {
  const s = window.studio;
  return !!s && document.getElementById('turn')?.dataset.mode === 'listen'
    && performance.now() - window.__wire.lastMicFrame < 500;
}"""
SAYS_LISTENING = "() => document.getElementById('turn')?.dataset.mode === 'listen'"
NEEDS_TAP = "() => document.getElementById('turn')?.dataset.mode === 'resume'"


@dataclass
class Event:
    """Something the user did or saw, on the page's clock (ms)."""
    t: float
    what: str
    data: dict[str, Any] = field(default_factory=dict)


class Phone:
    def __init__(self, browser, base: str, run: Path, stack) -> None:
        self.browser, self.base, self.run, self.stack = browser, base, run, stack
        self.page = None
        self.events: list[Event] = []
        self.errors: list[str] = []
        self.shots = run / "screens"
        self.shots.mkdir(parents=True, exist_ok=True)
        self._n = 0
        self.recording = Recording()
        self._poll: asyncio.Task | None = None

    # --- the phone ------------------------------------------------------------------------------------------------
    async def open(self) -> None:
        context = await self.browser.new_context(permissions=["microphone"], color_scheme="dark", **IPHONE)
        for script in (MUTE, VOICE, WIRE):
            await context.add_init_script(script)
        pw = secrets.token_urlsafe(18)
        r = await context.request.post(f"{self.base}/login", form={"password": pw, "confirm": pw, "next": "/"})
        assert r.ok, f"login: {r.status}"
        page = await context.new_page()
        page.on("pageerror", lambda e: self.errors.append(f"page error: {e}"))
        page.on("console", lambda m: self.errors.append(m.text) if m.type == "error" else None)
        await page.goto(f"{self.base}/studio/")
        await page.wait_for_function("() => window.studio && window.studio.socket.state === 'open'", timeout=30_000)
        self.page = page
        self._poll = asyncio.create_task(self._keep())
        await self.note("opened")

    async def _keep(self) -> None:
        """Every two seconds: take the ear's recordings and the engine's log off the page (it keeps only 50 items)."""
        while True:
            await asyncio.sleep(2)
            try:
                await self.drain()
            except Exception:              # noqa: BLE001 - the page may be busy or closing; the next pass catches up
                pass

    async def drain(self, flush: bool = False) -> None:
        if flush:
            await self.js("() => (window.__ears || []).forEach((e) => e.node?.port.postMessage('flush'))")
            await asyncio.sleep(0.3)
        self.recording.add_ears(await self.js(DRAIN))
        self.recording.add_engine(await self.js("window.studio.engine.log"))

    async def close(self) -> None:
        if self._poll:
            self._poll.cancel()
        await self.drain(flush=True)
        await self.page.context.close()

    async def js(self, expr: str, arg: Any = None) -> Any:
        return await self.page.evaluate(expr, arg)

    async def now(self) -> float:
        return await self.js("performance.now()")

    async def note(self, what: str, **data: Any) -> Event:
        e = Event(await self.now(), what, data)
        self.events.append(e)
        print(f"  [{e.t / 1000:7.1f}s] {what} {json.dumps(data)[:160] if data else ''}", flush=True)
        return e

    async def shot(self, name: str) -> None:
        self._n += 1
        await self.page.screenshot(path=str(self.shots / f"{self._n:02d}-{name}.png"))

    async def wait(self, expr: str, timeout: float, what: str) -> None:
        try:
            await self.page.wait_for_function(expr, timeout=timeout * 1000, polling=50)
        except Exception as exc:                  # noqa: BLE001 - the report says what was being waited for
            await self.shot(f"timeout-{what}")
            raise TimeoutError(f"waited {timeout:.0f} s for {what}") from exc

    # --- what the user does ---------------------------------------------------------------------------------------
    async def start(self) -> None:
        await self.page.tap("#turn")
        await self.note("tap start")

    async def say(self, text: str, *, listen_timeout: float = 180) -> str:
        """Wait until the page says it is listening, say `text` and the stop word, and return what the Mac heard."""
        url = self.stack.studio.store.put_media(voice.line(f"{text} Tomato.").read_bytes(), "wav").url
        before = await self.js("window.__wire.log.length")
        asked = await self.js("""() => {
          const l = window.__wire.log.filter((e) => e.dir === 'in' && e.msg.type === 'listen');
          return l.length ? l[l.length - 1].t : null; }""")
        await self.wait(SAYS_LISTENING, listen_timeout, "the page to say Go ahead")
        lost = await self.js(f"({LISTENING})() ? null : performance.now() - window.__wire.lastMicFrame")
        if lost is not None:
            await self.note("Go ahead with no mic frames", ms_since_last_frame=round(lost))
        ready = await self.note("listening", since_listen_ms=round(await self.now() - asked) if asked else None)
        await self.js("(url) => window.__voice.say(url)", url)
        await self.note("said", text=text)
        heard = await self.wait_user_message(since=before, timeout=60)
        await self.note("heard", text=heard, from_ready_ms=round(await self.now() - ready.t))
        return heard

    async def type(self, text: str) -> None:
        await self.page.tap("#keyboard")
        await self.page.fill("#composer-input", text)
        await self.page.press("#composer-input", "Enter")
        await self.note("typed", text=text)

    async def tap(self, selector: str, what: str = "") -> None:
        await self.page.tap(selector)
        await self.note(f"tap {what or selector}")

    async def tap_option(self, seq: int, index: int) -> None:
        """A tap on a slider's tick, or on an option's button."""
        sel = f'#messages [data-seq="{seq}"]'
        loc = self.page.locator(f"{sel} .opt-tick[data-index='{index}'], {sel} .opt-button[data-index='{index}']").first
        await loc.scroll_into_view_if_needed()
        box = await loc.bounding_box()
        await self.page.touchscreen.tap(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        await self.note("tap option", seq=seq, index=index)

    async def switch_apps(self, away_s: float) -> None:
        """Leave for another app, as iOS does it: hidden, the capture tracks ended, the audio interrupted."""
        await self.js("""() => {
          window.__voice.setVisible(false);
          window.__voice.kill();
          window.studio.engine.context?.suspend();
        }""")
        await self.note("switched away", seconds=away_s)
        await asyncio.sleep(away_s)
        await self.js("() => window.__voice.setVisible(true)")
        await self.note("came back")
        await asyncio.sleep(0.6)
        mode = await self.js("() => document.getElementById('turn')?.dataset.mode")
        await self.shot("came-back")
        if mode == "resume":
            # The page asks for a tap to bring the mic back; Anthony taps the big button.
            await self.page.tap("#turn")
            await self.note("tap to resume")
        else:
            await self.note("no tap asked", mode=mode)

    # --- what the user sees ---------------------------------------------------------------------------------------
    async def wait_user_message(self, since: int, timeout: float) -> str:
        await self.wait(f"""() => window.__wire.log.slice({since}).some((e) => e.dir === 'in' && e.msg.type === 'upsert'
            && e.msg.message.kind === 'user' && (e.msg.message.data.text || '').trim())""", timeout, "the Mac to hear it")
        return await self.js(f"""() => window.__wire.log.slice({since}).filter((e) => e.dir === 'in'
            && e.msg.type === 'upsert' && e.msg.message.kind === 'user').map((e) => e.msg.message.data.text).pop()""")

    async def wait_card(self, test: str, since: int, timeout: float, what: str) -> dict:
        """The first music message after `since` (a wire index) whose data passes `test` (a JS expression on `d`)."""
        expr = f"""() => window.__wire.log.slice({since}).map((e) => e.msg).find((m) => m.type === 'upsert'
            && m.message.kind === 'music' && ((d) => {test})(m.message.data))?.message ?? null"""
        await self.wait(f"() => ({expr})() !== null", timeout, what)
        msg = await self.js(expr)
        await self.note("card", seq=msg["seq"], title=msg["data"].get("title"))
        return msg

    async def wait_turn_done(self, timeout: float = 300) -> None:
        """Until Claude's turn is over, everything has played, and the Mac offers the mic again."""
        n = await self.js("window.__wire.log.filter((e) => e.dir === 'in' && e.msg.type === 'listen').length")
        await self.wait(f"""() => window.__wire.log.filter((e) => e.dir === 'in' && e.msg.type === 'listen').length > {n}
            && !window.studio.engine.busy""", timeout, "the turn to end")
        await self.note("turn done")

    async def mark(self) -> int:
        return await self.js("window.__wire.log.length")

    async def collect(self) -> dict[str, Any]:
        """Everything the page kept (the ear and the engine's log are taken as the run goes), for the checks."""
        return await self.js("""() => ({
          wire: window.__wire.log, speech: window.__wire.speech, firstMicFrame: window.__wire.firstMicFrame,
          micSpans: window.__voice.spans, said: window.__voice.said, now: performance.now(),
        })""")
