// The phone's speaker: one AudioContext and one queue that plays items one after another.
//
// Items are the Mac's speech streams and `play` commands, and the bubbles the user taps. The Mac's
// items are counted: `done` is how many of them this page has finished or dropped since it last sent
// `start` or received `stop_audio`, and it travels in every `playback` message, so the Mac opens the
// mic only once the phone has played (or dropped) everything it was sent. A tapped bubble plays at
// once (dropping whatever was queued) and is not counted.
import { normaliseAb } from './ab.js';
import { BufferCache } from './buffers.js';
import { Clip } from './clip.js';
import { Emitter } from './emitter.js';
import { SpeechStream } from './speech-stream.js';

const LOG_LENGTH = 50;

export class AudioEngine extends Emitter {
  #ctx = null;
  #out = null;
  #queue = [];
  #current = null;
  #streams = new Map();      // stream id -> SpeechStream, from its begin until its end
  #epoch = 0;
  #done = 0;
  #busy = false;
  log = [];                  // the last items: what played, how, and how it ended

  /** `lookup(seq)` gives a message: from the chat window, or fetched from the Mac. */
  constructor({ session, timing, lookup }) {
    super();
    this.session = session;
    this.timing = timing;
    this.lookup = lookup;
    this.buffers = new BufferCache(() => this.#ctx);
  }

  /** Call inside a tap: mobile browsers only let a page start audio from a gesture. */
  unlock() {
    if (!this.#ctx) {
      this.#ctx = new AudioContext({ latencyHint: 'interactive' });
      this.#out = this.#ctx.createGain();
      this.#out.connect(this.#ctx.destination);
      this.#ctx.addEventListener('statechange', () => this.emit('context', this.#ctx.state));
    }
    if (this.#ctx.state !== 'running') this.#ctx.resume().catch(() => {});
    // Older iOS unlocks output only once a source has started inside the gesture.
    const blip = this.#ctx.createBufferSource();
    blip.buffer = this.#ctx.createBuffer(1, 1, this.#ctx.sampleRate);
    blip.connect(this.#ctx.destination);
    blip.start();
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
    const item = new Clip({
      seq, kind: 'music', loops: Math.max(1, loops | 0),
      load: () => this.#load(seq),
      onFirstSound: (lead) => this.timing.mark('music_first_play', performance.now() - asked + this.#heardIn(lead), { seq }, turn),
    });
    this.#enqueue(item, true);
  }

  // --- the user's taps --------------------------------------------------------------------------------

  /** A bubble's play: now, dropping the queue. `msg` is the bubble's message. */
  playNow(msg, loops = 1) {
    this.#clear();
    this.#enqueue(new Clip({ seq: msg.seq, kind: msg.kind, loops, load: () => this.#load(msg.seq, msg) }), false);
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

  /** The music playing now: {seq, t (s into the pass), duration, pass, loops, ab}, or null. */
  position() {
    const item = this.#current;
    if (!(item instanceof Clip) || !this.#ctx) return null;
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
    else this.#setBusy(false);
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
    const msg = known ?? (await this.lookup(seq));
    const url = msg?.data?.audio?.url;
    if (!url) throw new Error(`message ${seq} has no audio`);
    return { buffer: await this.buffers.load(url, seq), ab: normaliseAb(msg.data.ab) };
  }

  #outputLatency() {
    return this.#ctx.outputLatency || this.#ctx.baseLatency || 0;
  }

  /** From now until the first sample reaches the ears: the scheduling lead plus the output latency. */
  #heardIn(leadSeconds) {
    return (leadSeconds + this.#outputLatency()) * 1000;
  }
}
