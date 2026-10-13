// The mic. It is open only while the Mac has asked for it (`listen`) and nothing is playing, and it
// streams 20 ms frames: one binary WebSocket message each, 0x01 then s16le PCM at 16 kHz.
//
// It counts as open (state 'open', the dock's "Go ahead") only once its frames are on their way to the Mac from a
// track that is not muted; that is when it tells the Mac (`mic open`) and plays the ready cue (cue.js). Until the
// first frame the route is settling, getUserMedia is asking or the worklet is loading, and anything said is lost,
// so the dock says to wait. Each stage of an open is a timing mark (docs/studio.md, "A turn").
//
// It records from the phone's own mic where there is one (the `phoneMic` preference, on by default), so a car's or
// headset's Bluetooth is only ever used for playback and stays in its media profile.
//
// Between turns the stream is kept, its tracks disabled (the `keepMic` preference, on by default): some
// browsers (Chrome on iOS) ask for permission on every getUserMedia, and a kept stream also reopens faster.
// With the preference off, closing stops the tracks, so iOS leaves its call profile and a car's Bluetooth
// returns to media quality. Opening waits for the audio route to settle first (audio-session.js).
//
// Phones take the mic away behind the page's back: iOS ends or mutes the tracks of a page in the background, and
// leaves its audio context interrupted, or running but silent, until a tap replaces it (audio.js). So the mic
// closes while the page is hidden; back, it is 'stuck' (the dock asks for a tap) until that tap, and opens on the
// new context. A context interrupted while the page is in view (a call) stops it the same way, and if it resumes
// by itself the mic opens again by itself. A track that ends or stays muted is let go and the mic opens afresh.
// An open that fails is tried again once by itself when the error looks passing, and again after any tap or
// return to the page. Every failure goes to the Mac's log as well as to the page.
import { playReadyCue } from './cue.js';
import { sleep } from './dom.js';
import { Emitter } from './emitter.js';

export const MIC_RATE = 16000;
export const FRAME_MS = 20;
const MIC_CHANNEL = 0x01;
const WORKLET = new URL('./mic-worklet.js', import.meta.url);
const BUILT_IN = /iphone|ipad|built-in|macbook/i;   // the phone's own mic, as getUserMedia labels it
const UNMUTE_MS = 300;   // how long a kept track may take to come back after the route switches to recording
const MUTED_MS = 1000;   // an open track muted this long has been taken away: open afresh
const QUIET_MS = 2000;   // no frame this long (none yet, or none since the last one): the context is not running
const STALL_MS = 500;    // no frame for this long and the mic no longer counts as hearing
const WATCH_MS = 250;    // how often an open mic checks on itself
const RESUME_MS = 500;   // how long a suspended context gets to resume before the mic asks for a tap
const RETRY_MS = 400;    // the pause before a failed open is tried again
// Errors that pass: the session was still switching, the device was busy for a moment, the context was not ready.
const PASSING = new Set(['InvalidStateError', 'AbortError', 'NotReadableError']);
const CONSTRAINTS = {
  audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

// A worklet module belongs to the context it was added to, and the engine makes a new context after the page has
// been away (audio.js), so each context loads it once.
const worklets = new WeakMap();      // AudioContext -> the promise of its 'mic-frames' module

export class Mic extends Emitter {
  #want = null;          // the turn the Mac wants us listening for, or null
  #live = null;          // the open mic (#build), or null
  #adopted = null;       // a stream left open by the permission prompt, for the open that follows it
  #held = null;          // the stream kept between turns, its tracks disabled (keepMic)
  #primeWanted = false;
  #driving = false;
  #hidden = document.visibilityState === 'hidden';
  #away = this.#hidden;  // the page has been in the background since the last tap: the context needs one (audio.js)
  #stuck = null;         // why it waits for a tap (or a return to the page): 'tap' | 'failed' | 'blocked'
  #retry = 0;            // the timer of the one automatic retry
  #failures = 0;         // failed opens since the last good one, the last tap or the return to the page
  #wantedAt = 0;         // when this wait for the mic began: the Mac's listen, or what made it reopen
  #after = null;         // what the wait is a reopen after (away, ended, context, tap...), for the marks
  state = 'closed';      // closed | opening | open (hearing: frames are on their way to the Mac) | stuck
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
    document.addEventListener('visibilitychange', () => this.#visibility());
    // A tap may have made a new context (the open mic moves to it), or be the gesture a stuck mic waits for. The
    // page unlocks before the tapped control's own handler runs (main.js), so this waits for the tap to finish:
    // a tap on "Send" still sends, rather than finding the mic reopening.
    engine.on('unlock', () => {
      this.#away = false;
      setTimeout(() => this.retry());
    });
    engine.on('context', (state) => {
      if (state === 'running' && this.#stuck === 'tap') this.retry();
      else this.#check();
    });
  }

  /** True while a stream is kept between turns. */
  get held() {
    return !!this.#held;
  }

  /** Listen for `turn`, or close (null). Closing happens at once; opening is driven asynchronously. */
  want(turn) {
    if (turn === this.#want) return;
    if (turn && !this.#want) this.#since(null);
    this.#want = turn;
    this.#fresh();
    if (!turn && this.#live) this.#close();
    this.#drive();
    this.#syncState();
  }

  /** Ask for permission ahead of the first turn, so the prompt never interrupts one. */
  prime() {
    this.#primeWanted = true;
    this.#drive();
  }

  /** A tap (or the page coming back): whatever failed is tried again now, and an open mic checks its context. */
  retry() {
    if (this.#stuck || this.#retry) {
      this.#fresh();
      if (this.#want) this.#since('tap');
    }
    this.#drive();
    this.#syncState();
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
        if (this.#live) this.#check();           // a replaced context or an ended track closes it here
        if (this.#want && !this.#live && this.#mayOpen()) await this.#open(this.#want);
        else if (!this.#want && this.#live) this.#close();
        else if (this.#want && this.#live && this.#live.turn !== this.#want) this.#retarget(this.#want);
        else if (this.#primeWanted && !this.#live && !this.#hidden) await this.#prime();
        else break;
      }
    } finally {
      this.#driving = false;
      this.#syncState();
    }
  }

  #mayOpen() {
    return !this.#stuck && !this.#retry && !this.#hidden;
  }

  /** Open for `turn`, marking each stage: the kept stream taken back, its input checked, getUserMedia (when there
   * is no good kept stream), the worklet, and the graph. The mic counts as open only at its first frame (#check). */
  async #open(turn) {
    // What only a tap can mend is known at once: say so now, not after the route has settled.
    if (this.#tapFirst(this.engine.context)) {
      this.#waitForTap(turn);
      return;
    }
    this.#syncState();
    await this.session.forInput();
    let stream = this.#adopted;
    this.#adopted = null;
    const started = performance.now();
    let stage = 'context';
    let t = started;
    let kept = false;
    try {
      if (this.#gone(turn)) return;
      const ctx = this.engine.context;
      if (!(await this.#runs(ctx))) {
        this.#waitForTap(turn);
        return;
      }
      if (this.#gone(turn)) return;
      let builtIn;               // the phone's own mic's device id, once it has been looked up
      if (!stream && this.#held) {
        stage = 'held';
        t = performance.now();
        const muted = !!this.#held.getAudioTracks()[0]?.muted;
        stream = await this.#takeHeld();
        kept = !!stream;
        this.#mark('mic_held', t, { kept, muted }, turn);
      }
      if (stream) {
        stage = 'check';
        t = performance.now();
        const input = await this.#input(stream);
        builtIn = input.builtIn;
        this.#mark('mic_check', t, { listed: input.listed, wrong: input.wrong }, turn);
        if (input.wrong) {
          stream = stopTracks(stream);
          kept = false;
        }
      }
      if (this.#gone(turn)) return;
      if (!stream) {
        stage = 'gum';
        t = performance.now();
        const asked = await this.#ask(builtIn);
        stream = asked.stream;
        this.#mark('mic_gum', t, { exact: asked.exact }, turn);
      }
      if (this.#gone(turn)) return;
      stage = 'worklet';
      t = performance.now();
      const loaded = await loadWorklet(ctx);
      this.#mark('mic_worklet', t, { loaded }, turn);
      if (this.#gone(turn)) return;
      stage = 'graph';
      const live = this.#build(ctx, stream, turn, started);
      stream = null;
      // The input's label says which route the turn used ("iPhone Microphone", a headset's or a car's name).
      // `kept`: the stream kept from the last turn was used, with no getUserMedia.
      this.timing.mark('mic_open', performance.now() - this.#wantedAt, {
        gum_ms: Math.round(performance.now() - started), input: live.track?.label ?? '', kept, ...this.#afterMark(),
      }, turn);
    } catch (err) {
      if (stream) stream = stopTracks(stream);       // the next try asks afresh
      this.#fail(turn, stage, err);
    } finally {
      if (stream) this.#keep(stream);
    }
  }

  /** The Mac no longer wants this turn, or the page went to the background, while the open waited. */
  #gone(turn) {
    return this.#want !== turn || this.#hidden;
  }

  /** Whether the mic can run on `ctx` without a tap. After the page has been in the background it cannot: iOS
   * leaves the context interrupted, or running but silent, and the next tap replaces it (audio.js), so the mic
   * waits for that tap rather than open on a context about to go. Otherwise a context that is not running gets
   * RESUME_MS to resume by itself (a new one starts suspended for a moment; one a call interrupted does not). */
  async #runs(ctx) {
    if (this.#tapFirst(ctx)) return false;
    if (ctx.state !== 'running') await Promise.race([ctx.resume().catch(() => {}), sleep(RESUME_MS)]);
    return ctx.state === 'running';
  }

  #tapFirst(ctx) {
    return !ctx || ctx.state === 'closed' || this.#away;
  }

  #waitForTap(turn) {
    this.#stuck = 'tap';
    const state = this.engine.context?.state ?? 'missing';
    this.#report(`waits for a tap: ${this.#away ? 'the page was away' : `the audio context is ${state}`}`, turn);
    this.#syncState();
  }

  /** The graph: the stream into the worklet, which posts frames, and the worklet into a silent gain to the
   * speakers, which keeps it rendering. The track's events and a timer (#check) watch it from then on. */
  #build(ctx, stream, turn, started) {
    const source = ctx.createMediaStreamSource(stream);
    const node = new AudioWorkletNode(ctx, 'mic-frames', {
      numberOfInputs: 1, numberOfOutputs: 1, outputChannelCount: [1],
      processorOptions: { rate: MIC_RATE, frameMs: FRAME_MS },
    });
    const sink = ctx.createGain();        // silent, but keeps the node in the rendered graph
    sink.gain.value = 0;
    source.connect(node).connect(sink).connect(ctx.destination);
    const track = stream.getAudioTracks()[0];
    const now = performance.now();
    const live = {
      stream, track, source, node, sink, turn, ctx, started, built: now, frames: 0, lastFrame: 0,
      mutedAt: track.muted ? now : 0, announced: false, events: new AbortController(), watch: 0,
    };
    node.port.onmessage = (e) => this.#frame(live, e.data);
    const { signal } = live.events;
    track.addEventListener('ended', () => this.#check(), { signal });
    track.addEventListener('mute', () => {
      live.mutedAt = performance.now();
      this.#check();
    }, { signal });
    track.addEventListener('unmute', () => this.#check(), { signal });
    live.watch = setInterval(() => this.#check(), WATCH_MS);
    this.#live = live;
    return live;
  }

  /** Is the open mic hearing? Checked at every frame until it is, on its track's and the context's events, and
   * every WATCH_MS: what took it away closes it and opens it again (#lost). */
  #check() {
    const live = this.#live;
    if (!live) return;
    const why = this.#trouble(live);
    if (why) {
      this.#lost(why);
      return;
    }
    if (live.frames && !live.announced && !live.track.muted) this.#announce(live);
    this.#syncState();
  }

  #trouble(live) {
    const now = performance.now();
    if (live.ctx !== this.engine.context || live.ctx.state === 'closed') return 'context';
    if (live.ctx.state !== 'running') return 'paused';           // a call or Siri interrupted it: no frames now
    if (live.track.readyState === 'ended') return 'ended';
    if (live.track.muted && now - live.mutedAt > MUTED_MS) return 'muted';
    if (now - (live.lastFrame || live.built) > QUIET_MS) return 'quiet';
    return null;
  }

  /** The first frame is on its way, from a live track: from now on what is said is heard. Tell the Mac, mark how
   * long the wait was, and play the ready cue. */
  #announce(live) {
    live.announced = true;
    this.#failures = 0;
    const now = performance.now();
    const after = this.#afterMark();
    this.#after = null;
    this.socket.send({ type: 'mic', state: 'open', turn: live.turn, open_ms: Math.round(now - live.started) });
    this.timing.mark('mic_ready', now - this.#wantedAt, after, live.turn);
    if (!this.prefs.get('readySound')) return;
    try {
      const heardIn = playReadyCue(live.ctx) * 1000;
      this.timing.mark('ready_cue', now - this.#wantedAt + heardIn, after, live.turn);
    } catch (err) {
      this.#report(`the ready cue didn't play: ${describe(err)}`, live.turn);
    }
  }

  /** The open mic stopped hearing (`why`: context, paused, ended, muted, quiet). Say so to the Mac's log, close it,
   * and open it again. A context that stopped running waits for a tap, or for resuming by itself; a track lost
   * twice running is a failure. */
  #lost(why) {
    const live = this.#live;
    const paused = why === 'paused' || why === 'quiet';
    this.#report(`stopped hearing (${why}) after ${live.frames} frames`, live.turn);
    // A new context or a stopped one leaves the stream as good as it was; an ended or muted track is let go.
    this.#close({ keep: paused || why === 'context', settle: false });
    if (paused) this.#stuck = 'tap';
    else if (why !== 'context' && ++this.#failures > 1) {
      this.#stuck = 'failed';
      this.emit('error', new Error(`it keeps stopping (${why})`));
    }
    this.#since(why);
    this.#syncState();
    this.#drive();
  }

  /** An open failed at `stage`. Say so to the Mac's log; try once more by itself if the error looks passing,
   * otherwise wait for a tap (or a return to the page) and tell the page. One that failed because the page went
   * to the background waits for its return, which tries again anyway. */
  #fail(turn, stage, err) {
    this.#failures += 1;
    const again = PASSING.has(err?.name) && this.#failures === 1 && !this.#hidden;
    this.#report(`didn't open (${stage}): ${describe(err)}${again ? '; trying again' : ''}`, turn);
    if (this.#hidden) return;
    if (again) {
      this.#after = 'retry';
      this.#retry = setTimeout(() => {
        this.#retry = 0;
        this.#drive();
      }, RETRY_MS);
      return;
    }
    this.#stuck = err?.name === 'NotAllowedError' || err?.name === 'SecurityError' ? 'blocked' : 'failed';
    this.emit('error', err);
  }

  #close({ keep = true, settle = true } = {}) {
    const live = this.#live;
    this.#live = null;
    clearInterval(live.watch);
    live.events.abort();
    live.node.port.onmessage = null;
    live.node.port.postMessage('stop');
    try {
      live.source.disconnect();
      live.node.disconnect();
      live.sink.disconnect();
    } catch {
      // A closed context's nodes went with it.
    }
    if (keep) this.#keep(live.stream);
    else stopTracks(live.stream);
    this.level = 0;
    this.emit('level', 0);
    if (live.announced) this.socket.send({ type: 'mic', state: 'closed', turn: live.turn });
    // Settle toward playback now, while Claude works, rather than when its answer arrives.
    if (settle) this.session.forOutput();
    this.#syncState();
  }

  /** In the background iOS ends or mutes the page's tracks, so the mic closes cleanly (the Mac hears it closed) and
   * lets the kept stream go. Back, if the Mac still wants it, it waits for the tap the context needs (#runs), with
   * whatever failed before forgotten and the wait timed from now. */
  #visibility() {
    const hidden = document.visibilityState === 'hidden';
    if (hidden === this.#hidden) return;
    this.#hidden = hidden;
    if (hidden) {
      this.#away = true;
      if (this.#live) this.#close({ keep: false, settle: false });
      this.#held = this.#held && stopTracks(this.#held);
      this.#adopted = this.#adopted && stopTracks(this.#adopted);
      this.#fresh();
    } else {
      this.#fresh();
      if (this.#want) this.#since('away');
      this.#drive();
    }
    this.#syncState();
  }

  /** getUserMedia, for the phone's own mic when `phoneMic` is on and the phone has one (it is known by name only
   * once the mic has been allowed). A Bluetooth headset or car records only in its call profile, which takes its
   * playback down to phone quality too; the phone's mic leaves it in its media profile. `builtIn` is that mic's
   * id when it has been looked up already. Returns {stream, exact: whether it asked for the phone's mic}. */
  async #ask(builtIn) {
    if (builtIn === undefined) builtIn = await this.#builtIn();
    if (builtIn) {
      try {
        const audio = { ...CONSTRAINTS.audio, deviceId: { exact: builtIn } };
        return { stream: await navigator.mediaDevices.getUserMedia({ audio }), exact: true };
      } catch (err) {
        if (err?.name !== 'OverconstrainedError' && err?.name !== 'NotFoundError') throw err;
      }
    }
    return { stream: await navigator.mediaDevices.getUserMedia(CONSTRAINTS), exact: false };
  }

  /** The phone's own mic's device id, when `phoneMic` is on and it is listed; otherwise null. */
  async #builtIn() {
    if (!this.prefs.get('phoneMic')) return null;
    try {
      const inputs = (await navigator.mediaDevices.enumerateDevices()).filter((d) => d.kind === 'audioinput');
      return inputs.find((d) => BUILT_IN.test(d.label))?.deviceId || null;
    } catch {
      return null;
    }
  }

  /** Whether `stream` records from the wrong input: `phoneMic` wants the phone's own mic, the phone has one, and
   * this is something else. A track already labelled as the phone's mic is right as it is, so the devices are
   * listed (enumerateDevices) only when it is not. Returns {wrong, listed, builtIn (undefined: not looked up)}. */
  async #input(stream) {
    const track = stream.getAudioTracks()[0];
    if (!this.prefs.get('phoneMic')) return { wrong: false, listed: false, builtIn: null };
    if (BUILT_IN.test(track?.label ?? '')) return { wrong: false, listed: false, builtIn: undefined };
    const builtIn = await this.#builtIn();
    return { wrong: !!builtIn && track?.getSettings?.().deviceId !== builtIn, listed: true, builtIn };
  }

  /** Keep a stream for the next turn (tracks disabled), or stop it when the preference is off, it has ended, or
   * the page is in the background. */
  #keep(stream) {
    const live = stream.getAudioTracks().some((t) => t.readyState === 'live');
    if (!this.prefs.get('keepMic') || !live || this.#hidden || (this.#held && this.#held !== stream)) {
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
    if (this.#live.announced) this.socket.send({ type: 'mic', state: 'open', turn, open_ms: 0 });
  }

  async #prime() {
    this.#primeWanted = false;
    await this.session.forInput();
    try {
      const { stream } = await this.#ask();
      if (this.#want && !this.#live && !this.#hidden) this.#adopted = stream;
      else stopTracks(stream);
    } catch (err) {
      this.#report(`the permission ask failed: ${describe(err)}`);
      this.emit('error', err);
    }
  }

  #frame(live, { pcm, rms }) {
    if (this.#live !== live) return;
    const frame = new Uint8Array(1 + pcm.byteLength);
    frame[0] = MIC_CHANNEL;
    frame.set(new Uint8Array(pcm), 1);
    this.socket.sendBinary(frame);
    live.frames += 1;
    live.lastFrame = performance.now();
    if (live.frames === 1) this.timing.mark('mic_frame', live.lastFrame - live.built, {}, live.turn);
    // -60 dBFS reads as silence, -10 dBFS as full.
    this.level = Math.max(0, Math.min(1, (20 * Math.log10(rms + 1e-9) + 60) / 50));
    this.emit('level', this.level);
    if (this.state !== 'open') this.#check();
  }

  /** Start over: no failures counted, nothing stuck, no retry pending. */
  #fresh() {
    this.#stuck = null;
    this.#failures = 0;
    clearTimeout(this.#retry);
    this.#retry = 0;
  }

  /** A new wait for the mic starts now; `why` is what it reopens after (null: the Mac's listen). */
  #since(why) {
    this.#wantedAt = performance.now();
    this.#after = why;
  }

  #afterMark() {
    return this.#after ? { after: this.#after } : {};
  }

  #mark(name, since, extra, turn) {
    this.timing.mark(name, performance.now() - since, extra, turn);
  }

  /** What went wrong, for the harness log (the page shows it too): the turn, the page's and the context's state,
   * and how many opens have failed in a row. */
  #report(what, turn = this.#want) {
    const ctx = this.engine.context;
    const state = [`page ${document.visibilityState}`, `context ${ctx?.state ?? 'none'}`,
      this.engine.needsUnlock ? 'needs a tap' : '', `failures ${this.#failures}`].filter(Boolean).join(', ');
    this.socket.send({ type: 'log', text: `mic ${turn ?? '(no turn)'}: ${what} [${state}]` });
  }

  #syncState() {
    const live = this.#live;
    const hearing = !!live?.announced && !live.track.muted && performance.now() - live.lastFrame < STALL_MS;
    this.#setState(!this.#want || this.#hidden ? 'closed' : hearing ? 'open' : this.#stuck ? 'stuck' : 'opening');
  }

  #setState(state) {
    if (this.state === state) return;
    this.state = state;
    this.emit('state', state);
  }
}

/** Load the mic's worklet into `ctx`, once per context. True when it was loaded just now. */
async function loadWorklet(ctx) {
  let loading = worklets.get(ctx);
  const fresh = !loading;
  if (fresh) {
    loading = ctx.audioWorklet.addModule(WORKLET);
    worklets.set(ctx, loading);
    loading.catch(() => worklets.delete(ctx));         // try loading it again next time
  }
  await loading;
  return fresh;
}

function describe(err) {
  return `${err?.name ?? 'Error'}: ${err?.message ?? err}`;
}

function stopTracks(stream) {
  for (const track of stream.getTracks()) track.stop();
  return null;
}
