// The mic. It is open only while the Mac has asked for it (`listen`) and nothing is playing, and it
// streams 20 ms frames: one binary WebSocket message each, 0x01 then s16le PCM at 16 kHz.
//
// Between turns the stream is kept, its tracks disabled (the `keepMic` preference, on by default): some
// browsers (Chrome on iOS) ask for permission on every getUserMedia, and a kept stream also reopens faster.
// With the preference off, closing stops the tracks, so iOS leaves its call profile and a car's Bluetooth
// returns to media quality. Opening waits for the audio route to settle first (audio-session.js).
import { Emitter } from './emitter.js';

export const MIC_RATE = 16000;
export const FRAME_MS = 20;
const MIC_CHANNEL = 0x01;
const WORKLET = new URL('./mic-worklet.js', import.meta.url);
const UNMUTE_MS = 300;   // how long a kept track may take to come back after the route switches to recording
const CONSTRAINTS = {
  audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

export class Mic extends Emitter {
  #want = null;          // the turn the Mac wants us listening for, or null
  #live = null;          // {stream, source, node, sink, turn} while open
  #adopted = null;       // a stream left open by the permission prompt, for the open that follows it
  #held = null;          // the stream kept between turns, its tracks disabled (keepMic)
  #primeWanted = false;
  #driving = false;
  #failed = null;        // the turn whose open failed: not retried until the next turn
  #wantedAt = 0;
  #worklet = null;
  state = 'closed';      // closed | opening | open
  level = 0;             // 0..1, from the last frame

  constructor({ engine, session, socket, timing, prefs }) {
    super();
    this.engine = engine;
    this.session = session;
    this.socket = socket;
    this.timing = timing;
    this.prefs = prefs;
    prefs.on('change', ({ key, value }) => {
      if (key === 'keepMic' && !value) this.#held = this.#held && stopTracks(this.#held);
    });
  }

  /** True while a stream is kept between turns. */
  get held() {
    return !!this.#held;
  }

  /** Listen for `turn`, or close (null). Closing happens at once; opening is driven asynchronously. */
  want(turn) {
    if (turn === this.#want) return;
    if (turn && !this.#want) this.#wantedAt = performance.now();
    this.#want = turn;
    if (!turn && this.#live) this.#close();
    this.#drive();
  }

  /** Ask for permission ahead of the first turn, so the prompt never interrupts one. */
  prime() {
    this.#primeWanted = true;
    this.#drive();
  }

  async #drive() {
    if (this.#driving) return;
    this.#driving = true;
    try {
      for (;;) {
        if (this.#adopted && !this.#want) {
          this.#keep(this.#adopted);
          this.#adopted = null;
        }
        if (this.#want && !this.#live && this.#want !== this.#failed) await this.#open(this.#want);
        else if (!this.#want && this.#live) this.#close();
        else if (this.#want && this.#live && this.#live.turn !== this.#want) this.#retarget(this.#want);
        else if (this.#primeWanted && !this.#live) await this.#prime();
        else break;
      }
    } finally {
      this.#driving = false;
    }
  }

  async #open(turn) {
    this.#setState('opening');
    await this.session.forInput();
    let stream = this.#adopted;
    this.#adopted = null;
    const started = performance.now();
    let kept = false;
    try {
      const ctx = this.engine.context;
      if (this.#want !== turn || !ctx) return;
      if (!stream && (stream = await this.#takeHeld())) kept = true;
      if (this.#want !== turn) return;
      stream ??= await navigator.mediaDevices.getUserMedia(CONSTRAINTS);
      if (this.#want !== turn) return;
      this.#worklet ??= ctx.audioWorklet.addModule(WORKLET).catch((err) => {
        this.#worklet = null;          // try loading it again next time
        throw err;
      });
      await this.#worklet;
      if (this.#want !== turn) return;
      if (ctx.state !== 'running') ctx.resume().catch(() => {});
      const source = ctx.createMediaStreamSource(stream);
      const node = new AudioWorkletNode(ctx, 'mic-frames', {
        numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
        processorOptions: { rate: MIC_RATE, frameMs: FRAME_MS },
      });
      const sink = ctx.createGain();        // silent, but keeps the node in the rendered graph
      sink.gain.value = 0;
      source.connect(node).connect(sink).connect(ctx.destination);
      node.port.onmessage = (e) => this.#frame(node, e.data);
      this.#live = { stream, source, node, sink, turn };
      stream = null;
      const openMs = Math.round(performance.now() - started);
      this.#setState('open');
      this.socket.send({ type: 'mic', state: 'open', turn, open_ms: openMs });
      // The input's label says which route the turn used ("iPhone Microphone", a headset's or a car's name).
      const input = this.#live.stream.getAudioTracks()[0]?.label ?? '';
      this.timing.mark('mic_open', performance.now() - this.#wantedAt, { gum_ms: openMs, input, kept }, turn);
    } catch (err) {
      this.#failed = turn;
      this.emit('error', err);
    } finally {
      if (stream) this.#keep(stream);
      if (!this.#live) this.#setState('closed');
    }
  }

  #close() {
    const live = this.#live;
    this.#live = null;
    live.node.port.onmessage = null;
    live.node.port.postMessage('stop');
    live.source.disconnect();
    live.node.disconnect();
    live.sink.disconnect();
    this.#keep(live.stream);
    this.level = 0;
    this.emit('level', 0);
    this.#setState('closed');
    this.socket.send({ type: 'mic', state: 'closed', turn: live.turn });
    // Settle toward playback now, while Claude works, rather than when its answer arrives.
    this.session.forOutput();
  }

  /** Keep a stream for the next turn (tracks disabled), or stop it when the preference is off or it has ended. */
  #keep(stream) {
    const live = stream.getAudioTracks().some((t) => t.readyState === 'live');
    if (!this.prefs.get('keepMic') || !live || (this.#held && this.#held !== stream)) {
      stopTracks(stream);
      return;
    }
    for (const track of stream.getTracks()) track.enabled = false;
    this.#held = stream;
  }

  /** The kept stream, enabled again, if its track still works; otherwise null (and it is let go). */
  async #takeHeld() {
    const stream = this.#held;
    this.#held = null;
    const track = stream?.getAudioTracks()[0];
    if (!track || track.readyState !== 'live') return stream && stopTracks(stream);
    for (const t of stream.getTracks()) t.enabled = true;
    // iOS may mute a kept track while the session plays; it comes back once the route records again.
    if (track.muted) await new Promise((resolve) => {
      track.addEventListener('unmute', resolve, { once: true });
      setTimeout(resolve, UNMUTE_MS);
    });
    if (track.muted || track.readyState !== 'live') return stopTracks(stream);
    return stream;
  }

  #retarget(turn) {
    this.#live.turn = turn;
    this.socket.send({ type: 'mic', state: 'open', turn, open_ms: 0 });
  }

  async #prime() {
    this.#primeWanted = false;
    await this.session.forInput();
    try {
      const stream = await navigator.mediaDevices.getUserMedia(CONSTRAINTS);
      if (this.#want && !this.#live) this.#adopted = stream;
      else stopTracks(stream);
    } catch (err) {
      this.emit('error', err);
    }
  }

  #frame(node, { pcm, rms }) {
    if (this.#live?.node !== node) return;
    const frame = new Uint8Array(1 + pcm.byteLength);
    frame[0] = MIC_CHANNEL;
    frame.set(new Uint8Array(pcm), 1);
    this.socket.sendBinary(frame);
    // -60 dBFS reads as silence, -10 dBFS as full.
    this.level = Math.max(0, Math.min(1, (20 * Math.log10(rms + 1e-9) + 60) / 50));
    this.emit('level', this.level);
  }

  #setState(state) {
    if (this.state === state) return;
    this.state = state;
    this.emit('state', state);
  }
}

function stopTracks(stream) {
  for (const track of stream.getTracks()) track.stop();
  return null;
}
