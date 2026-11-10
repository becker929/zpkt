"""What the page actually played: a shim that records everything it sends to its speakers, and the arithmetic to
check it (silence, pitch, where a file sits in the recording, words).

The shim (`MUTE`, added to every test page) replaces `AudioContext.destination` with a gain (the "tap"). The tap
feeds an AudioWorklet (the "ear") that copies each render quantum, downmixed to mono, with the audio-clock time of
its first sample; the ear outputs silence to the real destination, so nothing reaches the speakers and the graph
keeps running. Each context gets its own ear the first time the page asks for its destination, so a context made
after the page was in the background is heard too; one that never touches its destination (the stand-in mic's) is
not recorded. `window.__ears` holds them; `heard(page)` fetches them as `Ear`s.

The mic's open spans come from the getUserMedia shim (`window.__micSpans`, performance-clock ms), and an ear maps
its audio clock to the performance clock (`Ear.perf`), so "was anything heard while the mic was open" is a
comparison of two lists of intervals.
"""

from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field

import numpy as np

MUTE = """
(() => {
  const Real = window.AudioContext || window.webkitAudioContext;
  if (!Real) return;
  const EAR = `
    class Ear extends AudioWorkletProcessor {
      constructor() {
        super();
        this.buf = new Float32Array(2048);
        this.n = 0;
        this.t = 0;
        this.port.onmessage = () => this.flush(true);
      }
      flush(asked) {
        const data = this.buf.slice(0, this.n);
        this.port.postMessage({ t: this.t, data, asked }, [data.buffer]);
        this.n = 0;
      }
      process(inputs, outputs) {
        const input = inputs[0];
        const frames = outputs[0][0].length;
        if (this.n + frames > this.buf.length) this.flush(false);
        if (this.n === 0) this.t = currentTime;
        for (let i = 0; i < frames; i += 1) {
          let s = 0;
          for (const ch of input) s += ch[i];
          this.buf[this.n + i] = input.length ? s / input.length : 0;
        }
        this.n += frames;
        return true;
      }
    }
    registerProcessor('studio-test-ear', Ear);`;
  const url = URL.createObjectURL(new Blob([EAR], { type: 'application/javascript' }));
  const ears = (window.__ears = []);

  function listen(ctx, speakers) {
    const tap = ctx.createGain();
    const ear = { id: ears.length, rate: ctx.sampleRate, chunks: [], heardAt: [], now: [], node: null,
                  ctx, asked: null, error: null };
    ears.push(ear);
    ear.ready = ctx.audioWorklet.addModule(url).then(() => {
      const node = new AudioWorkletNode(ctx, 'studio-test-ear', {
        numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1] });
      node.port.onmessage = ({ data }) => {
        if (data.data.length) ear.chunks.push({ t: data.t, data: data.data });
        // The audio clock against the page's: where the browser says, when a sample time is heard; else now.
        const out = ctx.getOutputTimestamp?.();
        if (out && out.performanceTime > 0) ear.heardAt.push([out.contextTime, out.performanceTime / 1000]);
        ear.now.push([ctx.currentTime, performance.now() / 1000]);
        if (data.asked && ear.asked) ear.asked();
      };
      tap.connect(node);
      node.connect(speakers);             // the ear outputs silence: nothing reaches the speakers
      ear.node = node;
    }).catch((err) => { ear.error = String(err); });
    return tap;
  }

  window.AudioContext = class extends Real {
    #tap = null;
    get destination() {
      if (!this.#tap) this.#tap = listen(this, super.destination);
      return this.#tap;
    }
  };

  // Everything recorded so far, per context: Float32 samples as base64, the time of each chunk, and the clocks.
  window.__heard = async () => {
    await Promise.all(ears.map((ear) => ear.ready));
    await Promise.all(ears.map((ear) => (ear.node && ear.ctx.state === 'running')
      ? Promise.race([new Promise((resolve) => { ear.asked = resolve; ear.node.port.postMessage('flush'); }),
                      new Promise((resolve) => setTimeout(resolve, 500))])
      : null));
    const b64 = (f32) => {
      const bytes = new Uint8Array(f32.buffer, f32.byteOffset, f32.byteLength);
      let s = '';
      for (let i = 0; i < bytes.length; i += 0x8000) s += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
      return btoa(s);
    };
    return ears.map((ear) => {
      const n = ear.chunks.reduce((a, c) => a + c.data.length, 0);
      const all = new Float32Array(n);
      let at = 0;
      for (const c of ear.chunks) { all.set(c.data, at); at += c.data.length; }
      return { id: ear.id, rate: ear.rate, state: ear.ctx.state, error: ear.error,
               outputLatency: ear.ctx.outputLatency || ear.ctx.baseLatency || 0,
               times: ear.chunks.map((c) => c.t), sizes: ear.chunks.map((c) => c.data.length),
               heardAt: ear.heardAt, now: ear.now, samples: b64(all) };
    });
  };
})();
"""

SILENT = 1e-3          # below this (-60 dBFS) a sample is silence


@dataclass
class Ear:
    """One context's output: mono samples from audio-clock time `t0`, at `rate`."""

    id: int
    rate: int
    t0: float
    samples: np.ndarray
    clock: np.ndarray               # rows of (audio-clock s, performance-clock s when that sample is heard)
    state: str = ""
    # Where a chunk did not follow on from the one before: (audio-clock time, samples missing). Chromium skips a
    # quantum or two while a context first starts its worklet thread, before anything plays; nothing else should.
    gaps: list[tuple[float, int]] = field(default_factory=list)

    def time(self, i: float) -> float:
        return self.t0 + i / self.rate

    def index(self, t: float) -> int:
        return int(round((t - self.t0) * self.rate))

    def between(self, t1: float, t2: float) -> np.ndarray:
        return self.samples[max(0, self.index(t1)):max(0, self.index(t2))]

    def perf(self, t: float) -> float:
        """When the sample at audio-clock time `t` reached the speakers, on the page's performance clock (s). The
        two clocks drift apart (a muted headless browser renders on a timer), so this follows the nearest
        readings."""
        ctx, perf = self.clock[:, 0], self.clock[:, 1]
        return float(t + np.interp(t, ctx, perf - ctx))

    def loud(self, hold: float = 0.05) -> list[tuple[float, float]]:
        """The spans (audio-clock seconds) with sound in them; silences shorter than `hold` do not split a span."""
        idx = np.flatnonzero(np.abs(self.samples) > SILENT)
        if not len(idx):
            return []
        cuts = np.flatnonzero(np.diff(idx) > hold * self.rate)
        starts = np.concatenate([[idx[0]], idx[cuts + 1]])
        ends = np.concatenate([idx[cuts], [idx[-1]]])
        return [(self.time(a), self.time(b + 1)) for a, b in zip(starts, ends)]


async def heard(page) -> list[Ear]:
    """Every context's recording so far. `page` is a Playwright page."""
    out = []
    for raw in await page.evaluate("window.__heard()"):
        assert raw["error"] is None, f"the ear did not start: {raw['error']}"
        rate = int(raw["rate"])
        chunk = np.frombuffer(base64.b64decode(raw["samples"]), dtype="<f4")
        times, sizes = raw["times"], raw["sizes"]
        if not times:
            out.append(Ear(raw["id"], rate, 0.0, np.zeros(0, np.float32), np.zeros((0, 2)), raw["state"], []))
            continue
        # Place every chunk at its own time (they follow on exactly unless the context stopped running).
        t0 = times[0]
        end = int(round((times[-1] - t0) * rate)) + sizes[-1]
        samples = np.zeros(end, np.float32)
        at, expected, gaps = 0, 0, []
        for i, (t, n) in enumerate(zip(times, sizes)):
            pos = int(round((t - t0) * rate))
            if i and pos != expected:
                gaps.append((t, pos - expected))
            samples[pos:pos + n] = chunk[at:at + n]
            at += n
            expected = pos + n
        if raw["heardAt"]:
            clock = np.array(raw["heardAt"])
        else:                                    # no output timestamps: now, plus the output's latency
            clock = np.array(raw["now"]) + [0.0, raw["outputLatency"]]
        out.append(Ear(raw["id"], rate, t0, samples, clock, raw["state"], gaps))
    return out


async def mic_spans(page) -> list[tuple[float, float]]:
    """When the page's mic was open (performance-clock seconds); a mic still open ends at infinity."""
    spans = await page.evaluate("window.__micSpans")
    return [(s["open"] / 1000, s["close"] / 1000 if s["close"] is not None else float("inf")) for s in spans]


def overlaps(a: list[tuple[float, float]], b: list[tuple[float, float]]) -> list[tuple[float, float]]:
    return [(max(x1, y1), min(x2, y2)) for x1, x2 in a for y1, y2 in b if max(x1, y1) < min(x2, y2)]


def dominant_hz(samples: np.ndarray, rate: int) -> float:
    spectrum = np.abs(np.fft.rfft(samples * np.hanning(len(samples))))
    return float(np.fft.rfftfreq(len(samples), 1 / rate)[np.argmax(spectrum[1:]) + 1])


def resample(x: np.ndarray, src: int, dst: int) -> np.ndarray:
    """Band-limited resampling by FFT (fine for the few seconds a test hears)."""
    if src == dst:
        return np.asarray(x, np.float64)
    n = int(round(len(x) * dst / src))
    spectrum = np.fft.rfft(x)
    keep = min(len(spectrum), n // 2 + 1)
    out = np.zeros(n // 2 + 1, complex)
    out[:keep] = spectrum[:keep]
    return np.fft.irfft(out, n) * (n / len(x))


def correlate(signal: np.ndarray, ref: np.ndarray) -> np.ndarray:
    """Normalised cross-correlation of `ref` at every offset into `signal` (1.0: an exact copy)."""
    n = len(signal) + len(ref)
    size = 1 << (n - 1).bit_length()
    raw = np.fft.irfft(np.fft.rfft(signal, size) * np.conj(np.fft.rfft(ref, size)), size)[:len(signal) - len(ref) + 1]
    energy = np.concatenate([[0.0], np.cumsum(signal.astype(np.float64) ** 2)])
    local = energy[len(ref):] - energy[:-len(ref)]
    return raw / (np.sqrt(np.maximum(local, 1e-12)) * np.sqrt(np.sum(ref.astype(np.float64) ** 2)))


@dataclass
class Passes:
    starts: list[int] = field(default_factory=list)      # sample index of each pass in the recording
    scores: list[float] = field(default_factory=list)


def find_passes(signal: np.ndarray, ref: np.ndarray, threshold: float = 0.9) -> Passes:
    """Every place `ref` plays, whole, in `signal`: peaks of the correlation at least one file length apart."""
    c = correlate(signal, ref)
    found = Passes()
    order = np.argsort(c)[::-1]
    for i in order:
        if c[i] < threshold:
            break
        if all(abs(int(i) - s) >= len(ref) * 0.9 for s in found.starts):
            found.starts.append(int(i))
            found.scores.append(float(c[i]))
        if len(found.starts) > 16:
            break
    pairs = sorted(zip(found.starts, found.scores))
    return Passes([p for p, _ in pairs], [s for _, s in pairs])


def words(text: str) -> list[str]:
    return re.sub(r"[^a-z0-9' ]+", " ", text.lower().replace("-", " ")).split()


def wer(reference: str, hypothesis: str) -> float:
    """Word error rate: edits (substitutions, insertions, deletions) per reference word."""
    ref, hyp = words(reference), words(hypothesis)
    d = list(range(len(hyp) + 1))
    for i, r in enumerate(ref, 1):
        prev, d[0] = d[0], i
        for j, h in enumerate(hyp, 1):
            prev, d[j] = d[j], min(d[j] + 1, d[j - 1] + 1, prev + (r != h))
    return d[len(hyp)] / max(1, len(ref))
