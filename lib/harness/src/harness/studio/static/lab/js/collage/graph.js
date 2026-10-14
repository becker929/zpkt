// The collage's sound: its own buses on the engine, its own effects, and the col.* sketches.
//
//   player -> engine.bus('col-src-N')  (the Channel: level, the clip's EQ, COLDFIRE / Overdrive, AutoFilter)
//          -> dry (Supermassive mix) -> the tape            (SFX and perc sources)
//                                    -> the Break bus        (Break group sources: COLDFIRE fold, Hybrid)
//          \-> Supermassive send, FlexVerb send (post-fader taps)
//   the tape (wow, flutter, stop and start) -> collage out -> the engine's master
//
// These sources are played fresh here (they are not in the stems on their own), so the sketches use each knob's
// full value, not its change from the set. Everything is undone by dispose(): the buses go back to the master.

import { Hybrid, Massive, Room, Tape, hold } from './fx.js';
import { BUTTERWORTH } from '../audio/channel.js';

const dbToGain = (db) => Math.pow(10, db / 20);
let current = null;              // the graph in charge of the buses (a remount replaces it)

export function buildGraph(engine, sources) {
  const ctx = engine.ctx, master = engine.master;
  const owned = [], taps = [], rerouted = new Set();
  const n = (node) => { owned.push(node); return node; };
  const gain = (v = 1) => { const g = n(ctx.createGain()); g.gain.value = v; return g; };
  const ramp = (param, v, t = 0.03) => param.setTargetAtTime(v, ctx.currentTime, t);
  const reroute = (ch, to) => { ch.output.disconnect(); ch.output.connect(to); rerouted.add(ch); };
  const tap = (from, to) => { from.connect(to); taps.push([from, to]); };

  const G = { ctx, engine, strips: new Map(), pitch: {}, speed: 1, disposed: false };
  current = G;

  G.tape = new Tape(ctx);
  G.out = gain(1);
  G.tape.out.connect(G.out);
  G.out.connect(master.input);
  G.meter = n(ctx.createAnalyser()); G.meter.fftSize = 1024;
  G.out.connect(G.meter);
  G.sum = G.tape.in;
  G.massive = new Massive(ctx); G.massive.out.connect(G.sum);
  G.room = new Room(ctx); G.room.out.connect(G.sum);
  G.hybrid = new Hybrid(ctx); G.hybrid.out.connect(G.sum);

  // --- the Break bus: Eq8 > COLDFIRE (colour tilt, fold) > Hybrid > Compressor2 ------------------------------------
  const brk = G.breakCh = engine.bus('col-break');
  G.breakIn = gain(1);
  G.breakIn.connect(brk.input);
  G.massiveB = new Massive(ctx); G.massiveB.out.connect(G.breakIn);
  G.breakDry = gain(Math.SQRT1_2);
  G.hybridSend = gain(Math.SQRT1_2);
  // COLDFIRE's colour is a tilt on what comes out (batch 8.7 measured it there): a shelf pair after the fold, so the
  // Hybrid hears it too. A little of it goes in front of the fold as well (in the Channel's shelves).
  const shelf = (type, f) => { const b = n(ctx.createBiquadFilter()); b.type = type; b.frequency.value = f; b.gain.value = 0; return b; };
  G.tiltLo = shelf('lowshelf', 250);
  G.tiltHi = shelf('highshelf', 2500);
  reroute(brk, G.tiltLo);
  G.tiltLo.connect(G.tiltHi);
  G.tiltHi.connect(G.breakDry).connect(G.sum);
  G.tiltHi.connect(G.hybridSend).connect(G.hybrid.in);
  brk.set('lowFreq', 250); brk.set('highFreq', 2500); brk.set('driveType', 'fold');
  brk.set('compThreshold', -14); brk.set('compRatio', 2.5); brk.set('compAttack', 8); brk.set('compRelease', 140);
  brk.set('compMakeup', 1.5); brk.set('compMix', 1);

  G.breakColour = (c) => {
    brk.set('highGain', 4 * (c - 0.7));
    ramp(G.tiltHi.gain, 2 + 12 * (c - 0.7));
    ramp(G.tiltLo.gain, -5 * (c - 0.7));
  };
  G.breakFold = (f) => { brk.set('driveType', 'fold'); brk.set('drive', 0.04 + 0.52 * f); brk.set('driveMix', 0.15 + 0.65 * f); };
  G.breakSpace = (w) => { ramp(G.breakDry.gain, Math.cos(w * Math.PI / 2)); ramp(G.hybridSend.gain, Math.sin(w * Math.PI / 2) * 1.15); };

  // --- a strip per bus ------------------------------------------------------------------------------------------
  G.strip = (busName, toBreak = false) => {
    if (G.strips.has(busName)) return G.strips.get(busName);
    const ch = engine.bus(busName);
    const s = { ch, name: busName, brk: toBreak };
    s.dry = gain(1);
    s.send = gain(0);
    s.massIn = gain(1);
    reroute(ch, s.dry);
    s.dry.connect(toBreak ? G.breakIn : G.sum);
    tap(ch.mute, s.send);
    s.send.connect(s.massIn).connect((toBreak ? G.massiveB : G.massive).in);

    /** Supermassive mix, 0..1: equal power between the dry strip and the hall. */
    s.space = (m) => { ramp(s.dry.gain, Math.cos(m * Math.PI / 2)); ramp(s.send.gain, Math.sin(m * Math.PI / 2)); };
    /** Supermassive's delay (the ARC track): an echo in front of the hall. */
    s.echoTime = (x) => {
      if (!s.echo) {
        s.echo = n(ctx.createDelay(2)); s.echoFb = gain(0.38);
        s.send.disconnect(s.massIn);
        s.send.connect(s.echo).connect(s.massIn);
        s.echo.connect(s.echoFb).connect(s.echo);
        s.send.connect(gain(0.35)).connect(s.massIn);
      }
      ramp(s.echo.delayTime, 0.03 + x * 0.97, 0.06);
    };
    /** FlexVerb wet: a send into the room. */
    s.verb = (x) => {
      if (!s.room) { s.room = gain(0); tap(ch.mute, s.room); s.room.connect(G.room.in); }
      ramp(s.room.gain, x * 1.1);
    };
    /** COLDFIRE colour (the chord loop) or Overdrive (the synth). */
    s.drive = (x, id = '') => {
      if (/colour|color/i.test(id)) {
        ch.set('lowFreq', 220); ch.set('lowGain', 3 - 7 * x);
        ch.set('highFreq', 3000); ch.set('highGain', -5 + 14 * x);
        ch.set('driveType', 'tube'); ch.set('drive', 0.12 + 0.38 * x); ch.set('driveMix', 0.65);
      } else {
        ch.set('driveType', 'tanh'); ch.set('drive', 0.55 * x); ch.set('driveMix', x > 0.005 ? 1 : 0);
        ch.bandGain('od', 4 * x, 'peaking', 1100, 0.8);
      }
    };
    /** AutoFilter: a low-pass with resonance and a half-bar LFO (in octaves, on the filter's detune). A low-pass Q is
     *  in dB here (Web Audio): Butterworth (no peak) at 0 %, a 18 dB peak at Live's 100 %. */
    s.af = { hz: 18000, res: 0.3, lfo: 0 };
    s.filter = (o) => {
      Object.assign(s.af, o);
      const f = ch.band('af', 'lowpass', s.af.hz, BUTTERWORTH);
      ramp(f.frequency, s.af.hz, 0.02);
      ramp(f.Q, BUTTERWORTH + Math.pow(s.af.res, 1.2) * 21, 0.02);
      if (!s.lfo) {
        s.lfo = n(ctx.createOscillator());
        s.lfo.frequency.value = 2 / (engine.barSeconds || 1.5);
        s.lfoAmt = gain(0);
        s.lfo.connect(s.lfoAmt).connect(f.detune);
        const pos = engine.position();
        s.lfo.start(pos.playing ? engine.timeOf(Math.ceil(pos.t) * 16) : ctx.currentTime);
      }
      ramp(s.lfoAmt.gain, s.af.lfo * 3600, 0.05);
    };
    G.strips.set(busName, s);
    return s;
  };

  G.busOf = (id) => (String(id).startsWith('rs') ? 'col-rs' : `col-${id}`);
  G.stripOf = (id) => {
    if (String(id).startsWith('rs')) return G.strip('col-rs', false);
    const src = sources.find((x) => x.id === id);
    return G.strip(`col-${id}`, !!src?.brk);
  };
  G.input = (id) => G.stripOf(id).ch.input;
  G.pitchOf = (id) => G.pitch[id] ?? 0;

  // every source gets its strip now, so the buses are in place before anything plays
  for (const s of sources) G.stripOf(s.id);
  G.stripOf('rs');

  G.dispose = () => {
    if (G.disposed) return;
    G.disposed = true;
    const t = ctx.currentTime;
    hold(G.out.gain, t);
    G.out.gain.linearRampToValueAtTime(0, t + 0.03);
    setTimeout(() => {
      for (const [from, to] of taps) { try { from.disconnect(to); } catch { /* gone */ } }
      if (current === G) {
        for (const ch of rerouted) { try { ch.output.disconnect(); ch.output.connect(master.input); } catch { /* gone */ } }
        current = null;
      }
      for (const s of G.strips.values()) {
        if (s.lfo) { try { s.lfo.stop(); } catch { /* */ } try { s.lfoAmt.disconnect(); } catch { /* */ } }
      }
      for (const u of [G.tape, G.massive, G.massiveB, G.room, G.hybrid]) u.dispose();
      for (const node of owned) { try { node.disconnect(); } catch { /* */ } }
    }, 60);
  };
  return G;
}

/** The col.* sketches, on this graph. Returns the remover. */
export function collageSketches(engine, G, ids) {
  const rm = [];
  const on = (key, fn) => rm.push(engine.sketch(key, (v, i) => { if (!G.disposed) fn(v, i); }));
  for (const id of [...ids, 'rs']) {
    const S = () => G.stripOf(id);
    on(`col.${id}.gain`, (_v, i) => S().ch.set('gain', i.real));
    on(`col.${id}.pitch`, (_v, i) => { G.pitch[id] = i.real; G.onPitch?.(id); });
    on(`col.${id}.space`, (_v, i) => S().space(i.norm));
    on(`col.${id}.delay`, (_v, i) => S().echoTime(i.norm));
    on(`col.${id}.verb`, (_v, i) => S().verb(i.norm));
    on(`col.${id}.tone`, (_v, i) => S().ch.bandGain('shine', i.real, 'highshelf', 1200, 0.7));
    on(`col.${id}.drive`, (_v, i) => S().drive(i.norm, i.id));
    on(`col.${id}.filter`, (_v, i) => S().filter({ hz: i.real }));
    on(`col.${id}.res`, (_v, i) => S().filter({ res: i.norm }));
    on(`col.${id}.lfo`, (_v, i) => S().filter({ lfo: i.norm }));
  }
  on('col.wash', (_v, i) => G.stripOf('rs').space(i.norm));
  on('col.breakSpace', (_v, i) => G.breakSpace(i.norm));
  on('col.breakColour', (_v, i) => G.breakColour(i.norm));
  on('col.breakFold', (_v, i) => G.breakFold(i.norm));
  on('col.breakDecay', (_v, i) => G.hybrid.setDecay(i.real));       // the Break bus's Hybrid
  on('col.out', (_v, i) => G.out.gain.setTargetAtTime(dbToGain(i.real), G.ctx.currentTime, 0.03));
  return () => { for (const f of rm) f(); };
}
