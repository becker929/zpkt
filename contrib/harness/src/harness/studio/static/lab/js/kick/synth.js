// HW002's kick, made from scratch in Web Audio, in the set's own order:
//
//   drum rack:  Clubby 052 (sine body, pitch fall, click, transient shaper) + Clubby 060 (a shorter knock)
//               + the offbeat pad (a short knock on every off-8th), each at its layer level
//               -> FlexVerb (a small room, kick.verb wet)
//   rumble:     the body's tail (re-pitched by the Shifter's semitones) -> a dark room -> low-pass
//               -> Decapitator (drive, style A E N T P, tone, punish, mix; 2x oversampled) -> EQ (31 Hz, 5 kHz)
//               -> LFOTool (ducked under every kick) -> width, bass mono below 120 Hz -> level
//   kick group: EQ Eight (30 Hz shelf, 62 Hz body, 330 Hz push) -> Roar (off in the set) -> COLDFIRE (2x)
//               -> EQ Eight (35 Hz shelf, the colour bell, 5 kHz shelf) -> Compressor (parallel mix)
//   then:       the sample layer (a hit cut from the set's kick stem) -> the scoop (48 dB/oct low cut, twice:
//               one played by hand, one for the set's scooped opening bars) -> level -> out
//
// It follows every kick param at its full value (it is not on top of a stem): set(id, real) or the constructor's
// `values`. One instance per AudioContext, realtime or offline (the scope renders single hits offline).

import {
  BEAT, BW8_QDB, HEADROOM, LAYER, OFF_HZ, STYLES, ampCurve, clickBuffer, db2g, driveDb, duckShape, gritDb, pitchCurve, room, shaperCurve,
  attackGain, transientCurve,
} from './dsp.js';

// Calibration, measured against the kick stem (beats 9-95, offline renders): at the set's values a synth beat peaks
// near -6.5 dBFS (the stem -8.4) with an RMS near -15.5 (-15.6), within 0.3 LU of the stem in the mix; body (0-180 ms) and gap (200-360 ms) within 2 dB;
// the bands within a few dB up to 1 kHz (the stem has 3-7 dB more at 1-4 kHz). COLDFIRE is fed so it starts to bite
// near the 8.1 zone (about +1 dB per 10 % of heat), and the compressor sees about -9 dBFS peaks: idle, as in the set.
export const CAL = { voice: 0.225, l060: 1.4, off: 0.45, feed: 8, rumble: 0.065, verb: 0.5, comp: 0.5, out: 1.35, click: 8, cfComp: 0.3, dComp: 0.15, irCut: 300 };
const ENVELOPE = new Set(['ks.pitchStart', 'ks.pitchEnd', 'ks.pitchDecay', 'ks.ampHold', 'ks.ampDecay', 'ks.ampCurve', 'ks.grit',
  'kick.attack', 'kick.pump', 'kick.sustain', 'rumble.pitch']);

export class KickSynth {
  /**
   * ac: an AudioContext or OfflineAudioContext; dest: where it plays. values: {id: real}. lat: seconds the
   * compressor delays the signal (hits start that much early so they land on the grid).
   */
  constructor(ac, dest, { values = {}, lat = 0.006, offline = false, cal = null } = {}) {
    this.ac = ac;
    this.cal = { ...CAL, ...cal };
    const CAL_ = this.cal;
    this.lat = lat;
    this.offline = offline;
    this.v = { ...values };
    this.dirty = true;
    this.duckEnd = 0;
    this.timers = new Map();
    const G = (v = 1) => { const g = ac.createGain(); g.gain.value = v; return g; };
    const F = (type, f, q = 0.71, gain = 0) => {
      const b = ac.createBiquadFilter(); b.type = type; b.frequency.value = f; b.Q.value = q; b.gain.value = gain; return b;
    };
    const shaper = (name) => { const s = ac.createWaveShaper(); s.curve = shaperCurve(name); s.oversample = '2x'; return s; };
    const chain = (...nodes) => { for (let i = 0; i < nodes.length - 1; i++) nodes[i].connect(nodes[i + 1]); return nodes.at(-1); };

    // ---- the drum rack ----
    this.l052 = G(); this.l060 = G(); this.loff = G();
    this.rack = G();
    for (const l of [this.l052, this.l060, this.loff]) l.connect(this.rack);
    this.verbDry = G(1); this.verbIn = G(0); this.verb = ac.createConvolver(); this.verbOut = G(1);
    this.verb.buffer = room(ac, 0.55, 2400, { seed: 7 });
    this.kickOut = G();
    this.rack.connect(this.verbDry).connect(this.kickOut);
    chain(this.rack, this.verbIn, this.verb, this.verbOut, this.kickOut);

    // ---- the rumble ----
    this.rIn = G(CAL_.feed);
    this.rConv = ac.createConvolver();
    this.rLP = F('lowpass', 180, -3);
    this.dIn = G(); this.dDry = G(0); this.dWet = G(1); this.dPre = G(1); this.dShaper = shaper('A'); this.dDC = F('highpass', 14, -3);
    this.dPost = G(1); this.dToneLo = F('lowshelf', 260); this.dToneHi = F('highshelf', 1800); this.dSum = G();
    chain(this.rIn, this.rConv, this.rLP, this.dIn);
    chain(this.dIn, this.dDry, this.dSum);
    chain(this.dIn, this.dPre, this.dShaper, this.dDC, this.dPost, this.dToneLo, this.dToneHi, this.dWet, this.dSum);
    this.rSub = F('lowshelf', 31); this.rAir = F('highshelf', 5000);
    this.rDuck = G(1);
    chain(this.dSum, this.rSub, this.rAir, this.rDuck);
    // width and bass mono, as mid/side: the side is scaled by width, and high-passed at 120 Hz when mono is on
    const split = ac.createChannelSplitter(2), merge = ac.createChannelMerger(2);
    const mid = G(1), side = G(1);
    const lm = G(0.5), rm = G(0.5), ls = G(0.5), rs = G(-0.5);
    this.rDuck.connect(split);
    split.connect(lm, 0); split.connect(rm, 1); split.connect(ls, 0); split.connect(rs, 1);
    lm.connect(mid); rm.connect(mid); ls.connect(side); rs.connect(side);
    this.sideW = G(1); this.sideFlat = G(1); this.sideHPg = G(0); const sideOut = G(1), sideInv = G(-1);
    side.connect(this.sideW);
    this.sideW.connect(this.sideFlat).connect(sideOut);
    chain(this.sideW, F('highpass', 120, -3), F('highpass', 120, -3), this.sideHPg, sideOut);
    mid.connect(merge, 0, 0); mid.connect(merge, 0, 1);
    sideOut.connect(merge, 0, 0); sideOut.connect(sideInv).connect(merge, 0, 1);
    this.rLevel = G(1);
    merge.connect(this.rLevel);

    // ---- the kick group ----
    this.group = G();
    this.kickOut.connect(this.group);
    this.rLevel.connect(this.group);
    this.gSub30 = F('lowshelf', 30); this.gBody = F('peaking', 62.5, 0.82); this.gPush = F('peaking', 330, 1.0);
    chain(this.group, this.gSub30, this.gBody, this.gPush);
    this.roarDry = G(1); this.roarWet = G(0); this.roarPre = G(db2g(9) / HEADROOM); this.roarPost = G(db2g(-6));
    this.roarSum = G();
    chain(this.gPush, this.roarDry, this.roarSum);
    chain(this.gPush, this.roarPre, shaper('roar'), F('highpass', 14, -3), this.roarPost, F('lowshelf', 60, 0.71, -2.5), this.roarWet, this.roarSum);
    this.cfPre = G(1 / HEADROOM); this.cfShaper = shaper('coldfire'); this.cfPost = G(1);
    this.gSub35 = F('lowshelf', 35); this.gColour = F('peaking', 484, 1.2); this.gAir = F('highshelf', 5000);
    chain(this.roarSum, this.cfPre, this.cfShaper, this.cfPost, this.gSub35, this.gColour, this.gAir);
    this.compIn = G(CAL_.comp);
    this.gAir.connect(this.compIn);
    this.comp = ac.createDynamicsCompressor();
    this.comp.knee.value = 6;
    this.compWet = G(1); this.compDry = G(0); this.compOut = G();
    const align = ac.createDelay(0.05); align.delayTime.value = 0.006;   // the compressor's look-ahead, for the dry path
    chain(this.compIn, this.comp, this.compWet, this.compOut);
    chain(this.compIn, align, this.compDry, this.compOut);

    // ---- after the group: the sample layer, the scoops, the level ----
    this.sampleBus = G(0);
    this.post = G();
    this.compOut.connect(this.post);
    this.sampleBus.connect(this.post);
    this.scoopA = BW8_QDB.map((q) => F('highpass', OFF_HZ, q));
    this.scoopB = BW8_QDB.map((q) => F('highpass', OFF_HZ, q));
    this.levelG = G(CAL_.out);
    this.matchG = G(1);                                   // loudness matching for A/B comparisons (the rig sets it)
    this.out = G(1);
    chain(this.post, ...this.scoopA, ...this.scoopB, this.levelG, this.matchG, this.out);
    this.out.connect(dest);

    if (offline) {
      // Offline, WebKit switches off a node whose input has gone quiet at a moment that varies from render to render
      // (the rumble's room came out up to 4 dB different). A constant -140 dB keeps every node running: renders repeat.
      const k = ac.createConstantSource(); k.offset.value = 1e-7; k.start(0);
      k.connect(this.rIn); k.connect(this.rack);
    }
    for (const id of Object.keys(this.v)) this._update(id, true);
    this._room(true);
    this._fresh();
  }

  /** A param moved: its full value, in its unit. */
  set(id, real) {
    if (this.v[id] === real) return;
    this.v[id] = real;
    this._update(id, false);
  }

  _p(param, x, now) {
    if (now || this.offline) { param.value = x; return; }
    param.setTargetAtTime(x, this.ac.currentTime, 0.015);
  }

  _later(key, fn, ms = 110) {
    if (this.offline) { fn(); return; }
    clearTimeout(this.timers.get(key));
    this.timers.set(key, setTimeout(fn, ms));
  }

  _update(id, now) {
    const CAL = this.cal;
    const v = this.v, p = (param, x) => this._p(param, x, now), x = v[id];
    if (x === undefined) return;
    if (ENVELOPE.has(id)) { this.dirty = true; return; }
    switch (id) {
      case 'kick.l052': return p(this.l052.gain, db2g(x) * CAL.voice);
      case 'kick.l060': return p(this.l060.gain, db2g(x) * CAL.voice * CAL.l060);
      case 'kick.offbeat': return p(this.loff.gain, db2g(x) * CAL.voice * CAL.off);
      case 'kick.verb': { const w = x / 100; p(this.verbIn.gain, w * CAL.verb); return p(this.verbDry.gain, 1 - w * 0.45); }
      case 'kick.sub30': return p(this.gSub30.gain, x);
      case 'kick.body': return p(this.gBody.gain, x);
      case 'kick.push': return p(this.gPush.gain, x);
      case 'kick.roar': p(this.roarWet.gain, x > 0.5 ? 1 : 0); return p(this.roarDry.gain, x > 0.5 ? 0 : 1);
      case 'kick.drive': { const d = driveDb(x); p(this.cfPre.gain, db2g(d) / HEADROOM); return p(this.cfPost.gain, db2g(-CAL.cfComp * d)); }
      case 'kick.sub35': return p(this.gSub35.gain, x);
      case 'kick.colour': return p(this.gColour.gain, x);
      case 'kick.colourFreq': return p(this.gColour.frequency, x);
      case 'kick.air': return p(this.gAir.gain, x);
      case 'kick.thresh': return p(this.comp.threshold, x);
      case 'kick.ratio': return p(this.comp.ratio, Math.min(20, Math.max(1, x)));
      case 'kick.cattack': return p(this.comp.attack, Math.min(1, x / 1000));
      case 'kick.release': return p(this.comp.release, Math.min(1, Math.max(0.001, x / 1000)));
      case 'kick.cmix': p(this.compWet.gain, x / 100); return p(this.compDry.gain, 1 - x / 100);
      case 'rumble.drive': case 'rumble.punish': {
        const d = driveDb(v['rumble.drive'] ?? 27) + ((v['rumble.punish'] ?? 0) > 0.5 ? 20 : 0);
        p(this.dPre.gain, db2g(d) / HEADROOM); return p(this.dPost.gain, db2g(-CAL.dComp * d));
      }
      case 'rumble.style': this.dShaper.curve = shaperCurve(STYLES[Math.round(x)] ?? 'A'); return undefined;
      case 'rumble.tone': { const t = (x - 50) / 50; p(this.dToneHi.gain, t * 9); return p(this.dToneLo.gain, -t * 3); }
      case 'rumble.mix': p(this.dWet.gain, x / 100); return p(this.dDry.gain, 1 - x / 100);
      case 'rumble.sub': return p(this.rSub.gain, x);
      case 'rumble.air': return p(this.rAir.gain, x);
      case 'rumble.mono': p(this.sideFlat.gain, x > 0.5 ? 0 : 1); return p(this.sideHPg.gain, x > 0.5 ? 1 : 0);
      case 'rumble.width': return p(this.sideW.gain, x / 100);
      case 'rumble.level': return p(this.rLevel.gain, db2g(x) * CAL.rumble);
      case 'ks.level': return p(this.levelG.gain, db2g(x) * CAL.out);
      case 'ks.sample': case 'ks.sampleLevel':
        return p(this.sampleBus.gain, (v['ks.sample'] ?? 0) > 0.5 ? db2g(v['ks.sampleLevel'] ?? -6) : 0);
      case 'ks.click': case 'ks.clickTone': this.dirtyClick = true; this.dirty = true; return undefined;
      case 'ks.tail': return now ? undefined : this._later('room', () => this._room(false));
      case 'ks.rumbleTone': return p(this.rLP.frequency, x);
      case 'ks.duck': this.dirtyDuck = true; this.dirty = true; return undefined;
      default: return undefined;
    }
  }

  _room() {
    this.rConv.buffer = room(this.ac, this.v['ks.tail'] ?? 1.2, this.cal.irCut, { seed: 3, pre: 0.008 });
  }

  /** Recompute the curves a hit plays (only when something they depend on moved). */
  _fresh() {
    if (!this.dirty) return;
    this.dirty = false;
    const v = this.v;
    const shift = Math.pow(2, (v['rumble.pitch'] ?? 0) / 12);
    this.c = {
      main: { pitch: pitchCurve(v, LAYER.main), amp: ampCurve(v, LAYER.main), shape: transientCurve(v), grit: db2g(gritDb(v)) / HEADROOM },
      l060: { pitch: pitchCurve(v, LAYER.l060), amp: ampCurve(v, LAYER.l060) },
      off: { pitch: pitchCurve(v, LAYER.off), amp: ampCurve(v, LAYER.off) },
      feed: pitchCurve(v, LAYER.main, shift),
    };
    if (this.dirtyClick || !this.clickBuf) { this.clickBuf = clickBuffer(this.ac, v['ks.clickTone'] ?? 3200); this.dirtyClick = false; }
    if (this.dirtyDuck || !this.duckCurve) { this.duckCurve = duckShape((v['ks.duck'] ?? 85) / 100); this.dirtyDuck = false; }
  }

  _voice(t, c, bus, { type = 'sine', click = 0, feed = null, vel = 1 } = {}) {
    const ac = this.ac;
    const osc = ac.createOscillator();
    osc.type = type;
    const env = ac.createGain();
    env.gain.value = 0;
    osc.frequency.setValueCurveAtTime(c.pitch.curve, t, c.pitch.len);
    env.gain.setValueCurveAtTime(c.amp.curve, t, c.amp.len);
    osc.connect(env);
    const nodes = [osc, env];
    // the main layer: its own COLDFIRE (grit), then the transient shaper's gain over time
    let last = env;
    if (c.shape) {
      const pre = ac.createGain(); pre.gain.value = c.grit;
      const sh = ac.createWaveShaper(); sh.curve = shaperCurve('grit'); sh.oversample = '2x';
      const ts = ac.createGain(); ts.gain.value = c.shape.curve[0];
      ts.gain.setValueCurveAtTime(c.shape.curve, t, c.shape.len);
      env.connect(pre).connect(sh).connect(ts);
      last = ts;
      nodes.push(pre, sh, ts);
    }
    let out = last;
    if (vel !== 1) { out = ac.createGain(); out.gain.value = vel; last.connect(out); nodes.push(out); }
    out.connect(bus);
    const end = t + c.amp.len + 0.02;
    osc.start(t); osc.stop(end);
    if (click > 0) {
      const src = ac.createBufferSource(); src.buffer = this.clickBuf;
      const g = ac.createGain(); g.gain.value = click * vel * (c.shape ? attackGain(this.v) : 1);
      src.connect(g).connect(bus);
      src.start(t);
      nodes.push(src, g);
    }
    if (feed) {
      const o2 = ac.createOscillator(), e2 = ac.createGain();
      e2.gain.value = 0;
      o2.frequency.setValueCurveAtTime(feed.curve, t, feed.len);
      e2.gain.setValueCurveAtTime(c.amp.curve, t, c.amp.len);
      o2.connect(e2).connect(this.rIn);
      o2.start(t); o2.stop(end);
      nodes.push(o2, e2);
    }
    if (!this.offline) osc.onended = () => { for (const n of nodes) n.disconnect(); };
  }

  /** One kick (the drawn body, the 060 knock, the rumble's feed) landing at `when`. */
  kick(when, { main = true, l060 = true, rumble = true, vel = 1 } = {}) {
    this._fresh();
    const t = Math.max(when - this.lat, this.ac.currentTime);
    const v = this.v;
    if (main) this._voice(t, this.c.main, this.l052, { click: db2g(v['ks.click'] ?? -16) * this.cal.click, feed: rumble ? this.c.feed : null, vel });
    if (l060) this._voice(t, this.c.l060, this.l060, { type: 'triangle', vel });
  }

  /** The offbeat pad's knock. */
  off(when, vel = 1) {
    this._fresh();
    const t = Math.max(when - this.lat, this.ac.currentTime);
    this._voice(t, this.c.off, this.loff, { click: db2g((this.v['ks.click'] ?? -16) - 10) * this.cal.click, vel });
  }

  /** A sample hit (an AudioBuffer from the set's kick stem), after the group's chain. */
  sample(when, buf, offset = 0, level = null) {
    if (!buf) return;
    const src = this.ac.createBufferSource();
    src.buffer = buf;
    let g = null;
    if (level == null) src.connect(this.sampleBus);
    else { g = this.ac.createGain(); g.gain.value = level; src.connect(g).connect(this.post); }   // an audition
    src.start(Math.max(when, this.ac.currentTime), offset);
    if (!this.offline) src.onended = () => { src.disconnect(); g?.disconnect(); };
  }

  /** LFOTool: the rumble dips under the kick at `when` and swells back over the beat. */
  duck(when, beat = BEAT) {
    this._fresh();
    const t = Math.max(when - this.lat - 0.002, this.ac.currentTime);
    if (t < this.duckEnd - 1e-4) return;
    const dur = beat * 0.96;
    try { this.rDuck.gain.setValueCurveAtTime(this.duckCurve, t, dur); this.duckEnd = t + dur; } catch { /* overlapping: skip a beat */ }
  }

  /** The rumble alone: the drum rack's layers silent (the rumble still hears their tail). */
  soloRumble(on) {
    this.kickOut.gain.setTargetAtTime(on ? 0 : 1, this.ac.currentTime, 0.01);
  }

  /** Clear the duck's schedule (the transport stopped). */
  panic() {
    const g = this.rDuck.gain;
    g.cancelScheduledValues(0);
    g.setValueAtTime(1, this.ac.currentTime);
    this.duckEnd = 0;
  }

  dispose() {
    for (const t of this.timers.values()) clearTimeout(t);
    if (this.offline) return;
    const now = this.ac.currentTime;
    this.out.gain.cancelScheduledValues(0);
    this.out.gain.setTargetAtTime(0, now, 0.01);
    setTimeout(() => { try { this.out.disconnect(); } catch { /* gone */ } }, 120);
  }
}

/**
 * Render `beats` kicks offline at the set's tempo and return {buffer, at}: the AudioBuffer and the time (s) the
 * last beat starts in it. The scope looks at that last beat (by then the rumble is as it is in the track).
 */
export async function renderBeats(values, { sampleRate = 44100, beats = 4, offbeat = true, cal = null } = {}) {
  const OAC = window.OfflineAudioContext || window.webkitOfflineAudioContext;
  const t0 = 0.02;
  const len = Math.ceil((t0 + beats * BEAT + 0.01) * sampleRate);
  const oc = new OAC(2, len, sampleRate);
  const s = new KickSynth(oc, oc.destination, { values, offline: true, cal });
  for (let i = 0; i < beats; i++) {
    const w = t0 + i * BEAT;
    s.kick(w);
    s.duck(w);
    if (offbeat && (values['ks.offbeatOn'] ?? 1) > 0.5) s.off(w + BEAT / 2);
  }
  const buffer = await oc.startRendering();
  return { buffer, at: t0 + (beats - 1) * BEAT };
}
