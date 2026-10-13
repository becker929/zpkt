// The phone's speaker: one AudioContext and one queue that plays items one after another.
//
// Items are the Mac's speech streams and `play` commands, and the bubbles the user taps. The Mac's
// items are counted: `done` is how many of them this page has finished or dropped since it last sent
// `start` or received `stop_audio`, and it travels in every `playback` message, so the Mac opens the
// mic only once the phone has played (or dropped) everything it was sent. A tapped bubble plays at
// once (dropping whatever was queued) and is not counted.
//
// A music message with `options` (options.js) plays as an OptionsClip: the Mac's play sweeps the options, a tap
// holds one, and picking another switches on the audio clock without asking the Mac.
import { normaliseAb } from './ab.js';
import { BufferCache } from './buffers.js';
import { Clip } from './clip.js';
import { Emitter } from './emitter.js';
import { OptionsClip } from './options-clip.js';
import { normaliseOptions } from './options.js';
import { SpeechStream } from './speech-stream.js';

const LOG_LENGTH = 50;
const IDLE_CAP_MS = 500;      // the longest the page waits for the output to catch up
const IDLE_MARGIN_MS = 80;    // browsers report less output latency than there is (measured: ~35 reported, ~100 real)

export class AudioEngine extends Emitter {
  #ctx = null;
  #out = null;
  #queue = [];
  #current = null;
  #streams = new Map();      // stream id -> SpeechStream, from its begin until its end
  #epoch = 0;
  #done = 0;
  #busy = false;
  #stale = false;            // the page has been in the background since the context was made
  log = [];                  // the last items: what played, how, and how it ended

  /** `lookup(seq)` gives a message: from the chat window, or fetched from the Mac. */
  constructor({ session, timing, lookup }) {
    super();
    this.session = session;
    this.timing = timing;
    this.lookup = lookup;
    this.buffers = new BufferCache(() => this.#ctx);
    document.addEventListener('visibilitychange', () => {
      if (document.visibilityState === 'hidden') this.#stale = true;
      else if (this.#ctx) this.emit('context', 'stale');      // back: it needs a tap before it can be trusted
    });
  }

  /** Call inside a tap: mobile browsers only let a page start audio from a gesture.
   *
   * After the page has been in the background (another app, the lock screen), iOS often leaves the context
   * interrupted, or "running" but silent, and resume() does not bring it back; decoding on it fails too. So
   * the first tap after that replaces it: what was playing is dropped (it was not being heard), decoded
   * buffers are kept (they work in any context), and the audio session is asked for again. */
  unlock() {
    if (this.#ctx && (this.#stale || this.#ctx.state === 'closed')) this.#replaceContext();
    this.#stale = false;
    if (!this.#ctx) {
      const ctx = new AudioContext({ latencyHint: 'interactive' });
      this.#ctx = ctx;
      this.#out = ctx.createGain();
      this.#out.connect(ctx.destination);
      ctx.addEventListener('statechange', () => {
        if (ctx === this.#ctx) this.emit('context', ctx.state);
      });
      this.buffers.decodeAhead();
    }
    if (this.#ctx.state !== 'running') this.#ctx.resume().catch(() => {});
    // Older iOS unlocks output only once a source has started inside the gesture.
    const blip = this.#ctx.createBufferSource();
    blip.buffer = this.#ctx.createBuffer(1, 1, this.#ctx.sampleRate);
    blip.connect(this.#ctx.destination);
    blip.start();
    this.emit('unlock');           // a tap: the mic moves to a new context, or opens if it waited for one (mic.js)
  }

  #replaceContext() {
    this.#clear();
    this.#idleIfEmpty();
    this.endStreams();
    const old = this.#ctx;
    this.#ctx = null;
    this.#out = null;
    old.close().catch(() => {});
    this.session.reset();
  }

  /** True when the next tap should call unlock(): no context yet, or the page has been away. */
  get needsUnlock() {
    return !this.#ctx || this.#stale || this.#ctx.state !== 'running';
  }

  get context() {
    return this.#ctx;
  }

  get busy() {
    return this.#busy;
  }

  get done() {
    return this.#done;
  }

  /** {seq, kind} of what is playing (or waiting for its route), or null. */
  get nowPlaying() {
    const item = this.#current;
    return item ? { seq: item.seq, kind: item.kind } : null;
  }

  // --- the Mac's items -------------------------------------------------------------------------------

  speechBegin({ stream, seq, rate }) {
    if (this.#streams.has(stream)) return;
    const began = performance.now();
    const turn = this.timing.turn;
    const item = new SpeechStream({
      stream, seq, rate,
      onFirstSound: (lead) => this.timing.mark('first_speech_audio', performance.now() - began + this.#heardIn(lead), {}, turn),
    });
    this.#streams.set(stream, item);
    this.#enqueue(item, true);
  }

  speechData(stream, pcm) {
    this.#streams.get(stream)?.push(pcm);
  }

  speechEnd(stream) {
    const item = this.#streams.get(stream);
    this.#streams.delete(stream);
    item?.end();
  }

  /** `play`: a music message, `loops` times, after whatever is queued. */
  play(seq, loops) {
    const asked = performance.now();
    const turn = this.timing.turn;
    const known = this.lookup(seq);
    const Kind = known?.data?.options ? OptionsClip : Clip;      // a message still being fetched plays as a file
    const item = new Kind({
      seq, kind: 'music', loops: Math.max(1, loops | 0),
      load: () => this.#load(seq, known),
      onFirstSound: (lead) => this.timing.mark('music_first_play', performance.now() - asked + this.#heardIn(lead), { seq }, turn),
    });
    this.#enqueue(item, true);
  }

  // --- the user's taps --------------------------------------------------------------------------------

  /** A bubble's play: now, dropping the queue. `msg` is the bubble's message; a card of options holds `pick`. */
  playNow(msg, loops = 1, { pick = null, match = false } = {}) {
    this.#clear();
    const load = () => this.#load(msg.seq, msg);
    const item = msg.data?.options
      ? new OptionsClip({ seq: msg.seq, kind: msg.kind, mode: 'hold', pick, match, load })
      : new Clip({ seq: msg.seq, kind: msg.kind, loops, load });
    this.#enqueue(item, false);
  }

  /** Switch the options playing now (if they are this card's) to `index`. False when they are not playing. */
  pickOption(seq, index) {
    const item = this.#current;
    if (!(item instanceof OptionsClip) || item.seq !== seq) return false;
    item.setPick(index);
    return true;
  }

  setMatch(seq, on) {
    const item = this.#current;
    if (item instanceof OptionsClip && item.seq === seq) item.setMatch(on);
  }

  /** Fetch a card's options now, and decode them as soon as there is a context, so its first pick plays at once.
   * Resolves when they are in memory. */
  preload(msg) {
    const url = msg.data?.audio?.url;
    return url ? this.buffers.preload(url, msg.seq) : Promise.resolve();
  }

  /** Stop and drop everything (a tap on stop, or an interrupt). */
  stop() {
    this.#clear();
    this.#idleIfEmpty();
  }

  /** The Mac's stop_audio: stop, drop everything, and count from zero again (the Mac does too). */
  stopAudio() {
    this.#clear();
    this.resetCount();
    this.#idleIfEmpty();
  }

  /** Sending `start` begins a new count. */
  resetCount() {
    this.#epoch += 1;
    this.#done = 0;
  }

  /** A new conversation: nothing of the old one plays or stays decoded. */
  reset() {
    this.stop();
    this.buffers.clear();
  }

  /** The socket closed: the streams in flight will get no more audio, so play what came and end them. */
  endStreams() {
    for (const item of this.#streams.values()) item.end();
    this.#streams.clear();
  }

  setLoops(seq, loops) {
    if (this.#current instanceof Clip && this.#current.seq === seq) this.#current.setLoops(loops);
  }

  /** The music playing now: {seq, t (s into the pass), duration, pass, loops, ab, option}, or null. */
  position() {
    const item = this.#current;
    if (!(item instanceof Clip || item instanceof OptionsClip) || !this.#ctx) return null;
    const pos = item.position(this.#ctx.currentTime - this.#outputLatency());
    return pos && { seq: item.seq, kind: item.kind, ...pos, duration: item.duration, loops: item.loops, ab: item.ab };
  }

  /** Warm the cache for a render that will probably be played. */
  prefetch(msg) {
    if (this.#ctx && msg.data?.audio?.url) this.buffers.load(msg.data.audio.url, msg.seq).catch(() => {});
  }

  /** These messages left the chat window. */
  release(seqs) {
    if (seqs.length) this.buffers.release(seqs);
  }

  // --- the queue -------------------------------------------------------------------------------------

  #enqueue(item, counted) {
    // A held option gives way to what the Mac sends, at the next bar line.
    if (counted && this.#current instanceof OptionsClip && !this.#current.counted) this.#current.yieldAtBar();
    item.counted = counted;
    item.epoch = this.#epoch;
    if (!this.#ctx) {
      // Nothing can play before the first tap: drop it, and say so, or the Mac would wait forever.
      item.stop();
      this.#finish(item, 'dropped');
      this.emit('idle', { done: this.#done });
      return;
    }
    this.#queue.push(item);
    item.prepare?.();
    if (!this.#current) {
      this.#setBusy(true);
      this.#advance();
    }
  }

  #advance() {
    const item = this.#queue.shift() ?? null;
    this.#current = item;
    this.emit('nowplaying', this.nowPlaying);
    if (item) this.#run(item);
    else this.#idleWhenHeard();
  }

  /** The queue ran dry on the audio clock, but the end of the sound is still on its way to the speakers. The page
   * counts as idle (and the mic may open) only once the output has played up to now on the audio clock
   * (getOutputTimestamp, where there is one) and the reported output latency plus a margin has passed; never
   * longer than a cap. Phones wait out a route settle after this anyway; a desktop browser waits only this. */
  #idleWhenHeard() {
    const ctx = this.#ctx;
    if (!ctx || ctx.state !== 'running') {
      this.#setBusy(false);
      return;
    }
    const end = ctx.currentTime;
    const started = performance.now();
    const check = () => {
      if (this.#current || this.#queue.length) return;            // something new started meanwhile
      const out = ctx.getOutputTimestamp?.();
      const waited = performance.now() - started;
      const heard = (out?.contextTime > 0 ? out.contextTime >= end : true)
        && waited >= this.#outputLatency() * 1000 + IDLE_MARGIN_MS;
      if (heard || performance.now() - started >= IDLE_CAP_MS) this.#setBusy(false);
      else setTimeout(check, 10);
    };
    check();
  }

  async #run(item) {
    await this.session.forOutput();
    if (this.#current !== item) return;              // dropped while the route settled
    if (this.#ctx.state !== 'running') this.#ctx.resume().catch(() => {});
    item.start(this.#ctx, this.#out);
    const outcome = await item.done;
    this.#finish(item, outcome);
    if (this.#current === item) this.#advance();
  }

  #clear() {
    const items = [this.#current, ...this.#queue].filter(Boolean);
    this.#queue = [];
    this.#current = null;
    for (const item of items) {
      item.stop();
      this.#finish(item, 'stopped');
    }
    if (items.length) this.emit('nowplaying', null);
  }

  #idleIfEmpty() {
    if (!this.#current && !this.#queue.length) this.#setBusy(false);
  }

  #setBusy(busy) {
    if (this.#busy === busy) return;
    this.#busy = busy;
    this.emit(busy ? 'busy' : 'idle', { done: this.#done });
  }

  #finish(item, outcome) {
    if (item.finished) return;
    item.finished = true;
    if (item.counted && item.epoch === this.#epoch) this.#done += 1;
    this.log.push({
      seq: item.seq, kind: item.kind, counted: item.counted, outcome,
      loops: item.loops ?? null, duration: item.duration ?? null, t0: item.t0 ?? null,
      stopAt: item.stopAt ?? null, endedAt: this.#ctx?.currentTime ?? null,
    });
    if (this.log.length > LOG_LENGTH) this.log.shift();
    if (outcome === 'failed') this.emit('error', { seq: item.seq, error: item.error });
  }

  async #load(seq, known = null) {
    const msg = await (known ?? this.lookup(seq));
    const url = msg?.data?.audio?.url;
    if (!url) throw new Error(`message ${seq} has no audio`);
    return {
      buffer: await this.buffers.load(url, seq), ab: normaliseAb(msg.data.ab), length: msg.data.duration,
      options: normaliseOptions(msg.data.options),
    };
  }

  #outputLatency() {
    return this.#ctx.outputLatency || this.#ctx.baseLatency || 0;
  }

  /** From now until the first sample reaches the ears: the scheduling lead plus the output latency. */
  #heardIn(leadSeconds) {
    return (leadSeconds + this.#outputLatency()) * 1000;
  }
}
