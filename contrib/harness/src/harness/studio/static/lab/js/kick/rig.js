// The kick surface's sound rig: the synth on its own bus, bound to the kick params through engine.sketch, played on
// the engine's grid (every beat, the offbeat pad on the off-8ths, rolls), the source switch (stem, synth, both, A/B
// a bar each), the scoop (held, latched for 4 bars on the bar, the set's scooped opening), the heat cycle (A/B/C a
// bar each) and the taps the meters read (the kick buses' waveform, the low end's correlation, gain reduction).
//
// Everything it starts is owned by the surface: on unmount the stem's kick bus is back as it was (unmuted, no scoop),
// the synth fades and disconnects, modulation is cleared.

import { BW8_QDB, OFF_HZ, db2g } from './dsp.js';
import { KickSynth } from './synth.js';
import { toNorm } from '../params.js';
import { toast } from '../ui.js';

export const MODE = { STEM: 0, SYNTH: 1, BOTH: 2, AB: 3 };
export const HEAT = { ids: ['kick.drive', 'rumble.drive'], abc: [37, 43.5, 50], zone: [37, 50] };

const scoopedCache = new WeakMap();      // stem AudioBuffer -> Set of scooped bars
const onsetCache = new WeakMap();        // sample AudioBuffer -> s before its first sound

export function createRig(ctx) {
  const { engine, store, params } = ctx;
  const kickIds = params.stage('kick').map((p) => p.id);
  const fns = new Set();
  const timers = new Set();
  const rig = {
    ctx, engine, store, params, kickIds,
    synth: null,
    sel: Math.round(store.real('ks.source')),     // the switch: 0 stem, 1 synth, 2 both, 3 A/B
    playing: MODE.STEM,                            // what sounds now: 0 stem, 1 synth, 2 both
    pending: null,                                 // a source waiting for the next beat
    abStart: null,
    scoop: { held: false, latch: null, armed: false },
    heat: { cycling: false, per: 1, startBar: null, idx: -1, at: 0 },
    match: { comp: new Map(), raw: new Map(), cur: null, config: '', acc: 0, n: 0, skip: false },
    roll: 0,
    kicks: [],                                     // audio times of the last kicks on the grid (some still ahead)
    samples: [],                                   // [{buf, offset}] the kick hits from the manifest
    scooped: new Set(),                            // stem bars that are scooped in the set (found by ear: no sub)
    values: () => Object.fromEntries(kickIds.map((id) => [id, store.real(id)])),
    on(fn) { fns.add(fn); return () => fns.delete(fn); },
    emit(type, data) { for (const fn of fns) { try { fn(type, data); } catch (err) { console.error(err); } } },
  };
  const later = (fn, ms) => { const t = setTimeout(() => { timers.delete(t); fn(); }, Math.max(0, ms)); timers.add(t); return t; };

  // ---- building, once the audio context exists ------------------------------------------------------------------
  const build = () => {
    if (rig.synth) return;
    const ac = engine.ctx;
    const kb = engine.bus('kick');
    rig.ac = ac;
    rig.kb = kb;
    rig.synth = new KickSynth(ac, engine.bus('kicksynth').input, { values: rig.values() });
    rig.stemScoop = BW8_QDB.map((q, i) => kb.band(`scoop${i + 1}`, 'highpass', OFF_HZ, q));
    for (const f of rig.stemScoop) { f.frequency.cancelScheduledValues(0); f.frequency.setValueAtTime(OFF_HZ, ac.currentTime); }

    // taps: what the kick buses play (both), its low end per side, the compressors' inputs
    const sum = ac.createGain();
    kb.output.connect(sum);
    rig.synth.out.connect(sum);
    rig.tap = ac.createAnalyser(); rig.tap.fftSize = 32768; rig.tap.smoothingTimeConstant = 0;
    sum.connect(rig.tap);
    rig.spec = ac.createAnalyser(); rig.spec.fftSize = 8192; rig.spec.smoothingTimeConstant = 0.55;
    sum.connect(rig.spec);
    const lp1 = ac.createBiquadFilter(), lp2 = ac.createBiquadFilter();
    for (const f of [lp1, lp2]) { f.type = 'lowpass'; f.frequency.value = 120; f.Q.value = -3; }
    const split = ac.createChannelSplitter(2);
    rig.lowL = ac.createAnalyser(); rig.lowR = ac.createAnalyser();
    rig.lowL.fftSize = rig.lowR.fftSize = 4096;
    sum.connect(lp1).connect(lp2).connect(split);
    split.connect(rig.lowL, 0); split.connect(rig.lowR, 1);
    rig.compTapSynth = ac.createAnalyser(); rig.compTapSynth.fftSize = 2048;
    rig.compTapStem = ac.createAnalyser(); rig.compTapStem.fftSize = 2048;
    rig.synth.compIn.connect(rig.compTapSynth);
    kb.compIn.connect(rig.compTapStem);
    // K-weighted (roughly: a 4 dB shelf above 1.7 kHz, a cut under 38 Hz), for matching A/B options by loudness
    const ksh = ac.createBiquadFilter(); ksh.type = 'highshelf'; ksh.frequency.value = 1681; ksh.gain.value = 4;
    const khp = ac.createBiquadFilter(); khp.type = 'highpass'; khp.frequency.value = 38; khp.Q.value = -3;
    rig.kTap = ac.createAnalyser(); rig.kTap.fftSize = 2048;
    sum.connect(ksh).connect(khp).connect(rig.kTap);
    rig.tapNodes = { sum };

    // the synth hears every kick param at its full value, through the same sketch keys the stems use
    const keys = new Set();
    for (const p of params.stage('kick')) for (const k of [].concat(p.sketch ?? [])) keys.add(k.split('@')[0]);
    for (const key of keys) ctx.own(engine.sketch(key, (_v, info) => rig.synth?.set(info.id, info.real)));

    applySource(rig.sel, true);
    applyScoop();
    rig.emit('ready');
    if (engine.manifest) loadExtras();
  };

  const loadExtras = () => {
    if (rig.extrasLoading) return;
    rig.extrasLoading = true;
    const kicks = engine.manifest?.kicks ?? [];
    Promise.all(kicks.map((k) => engine.buffer(k.id).then((buf) => ({ buf, offset: onset(buf), id: k.id, title: k.title })).catch(() => null)))
      .then((list) => { rig.samples = list.filter(Boolean); rig.emit('samples'); });
    engine.buffer('kick').then((buf) => { rig.scooped = scoopedBars(buf, engine.barSeconds); rig.emit('scooped'); }).catch(() => {});
  };

  // ---- loudness matching ------------------------------------------------------------------------------------------
  // While options take turns (heat A/B/C, stem/synth A/B), each one's K-weighted level on the kick buses is measured
  // over the bars it plays, and each gets the gain that brings it to their mean: "A/B, loudness-matched". The first
  // round plays as it is; from the second, matched. The stem's gain rides its bus's mute stage, the synth's its own.
  const M = rig.match;
  const matchKey = () => {
    const parts = [];
    if (rig.heat.cycling && rig.heat.idx >= 0) parts.push(`h${rig.heat.idx}`);
    if (rig.sel === MODE.AB) parts.push(rig.playing === MODE.STEM ? 'stem' : 'synth');
    return parts.length ? parts.join('|') : null;
  };
  const matchConfig = () => `${rig.heat.cycling ? 'heat' : ''}${rig.sel === MODE.AB ? 'ab' : ''}`;
  function applyGains(key, when) {
    if (!rig.synth) return;
    const c = (key && M.comp.get(key)) || 0;
    const t = Math.max((when ?? 0) - 0.004, rig.ac.currentTime);
    const audible = !(rig.playing === MODE.SYNTH || rig.solo);
    rig.kb.mute.gain.setTargetAtTime(audible ? Math.pow(10, c / 20) : 0, t, 0.004);
    rig.synth.matchG.gain.setTargetAtTime(Math.pow(10, c / 20), t, 0.004);
  }
  const closeBar = () => {
    if (M.cur && M.n >= 8 && !M.skip) {
      const raw = 10 * Math.log10(M.acc / M.n + 1e-12) - (M.comp.get(M.cur) ?? 0);
      M.raw.set(M.cur, M.raw.has(M.cur) ? M.raw.get(M.cur) * 0.6 + raw * 0.4 : raw);
      if (M.raw.size >= 2) {
        const target = [...M.raw.values()].reduce((a, b) => a + b, 0) / M.raw.size;
        for (const [k, r] of M.raw) M.comp.set(k, Math.max(-9, Math.min(9, target - r)));
      }
      rig.emit('match');
    }
    M.acc = 0; M.n = 0;
  };
  const matchBar = (when, bar) => {
    const cfg = matchConfig();
    if (cfg !== M.config) { M.config = cfg; M.comp.clear(); M.raw.clear(); }
    const key = matchKey();
    applyGains(key, when);
    // a bar with a scoop in it (the set's scooped opening, a latch) does not count
    const seq = engine.stems.sequence;
    const src = seq.length ? seq[bar % seq.length]?.kick ?? bar : bar;
    const S = rig.scoop;
    const skip = rig.scooped.has(src) || !!S.latch || S.armed;
    later(() => { closeBar(); M.cur = key; M.skip = skip; }, (when - rig.ac.currentTime) * 1000);
  };
  const meter = setInterval(() => {
    if (!M.cur || !rig.kTap || !engine.playing) return;
    if (rig.scoop.held || rig.roll || rig.solo) { M.skip = true; return; }   // played with: this bar does not count
    const buf = rig._kbuf ??= new Float32Array(rig.kTap.fftSize);
    rig.kTap.getFloatTimeDomainData(buf);
    let ss = 0;
    for (const x of buf) ss += x * x;
    M.acc += ss / buf.length; M.n++;
  }, 40);
  ctx.own(() => clearInterval(meter));
  rig.matchComp = (key) => (M.comp.has(key) ? M.comp.get(key) : null);

  // ---- the source switch ----------------------------------------------------------------------------------------
  /** Make `m` (0 stem, 1 synth, 2 both) sound from audio time `when`. */
  const sound = (m, when) => {
    rig.playing = m;
    const t = Math.max(when - 0.004, rig.ac.currentTime);
    applyGains(rig.match.cur, when);
    if (m === MODE.STEM) for (const f of rig.synth.scoopB) f.frequency.setTargetAtTime(OFF_HZ, t, 0.003);
    rig.emit('playing', { mode: m, when });
  };

  const applySource = (sel, now = false) => {
    rig.sel = sel;
    if (!rig.synth) return;
    if (sel === MODE.AB) { rig.abStart = null; if (!engine.playing || now) sound(MODE.STEM, rig.ac.currentTime); return; }
    if (!engine.playing || now) { rig.pending = null; sound(sel, rig.ac.currentTime); return; }
    rig.pending = sel;                                      // on the next beat
  };

  ctx.own(store.on('ks.source', (v) => {
    const sel = Math.round(store.real('ks.source'));
    if (sel === rig.sel && rig.synth) return;
    applySource(sel);
    rig.emit('source', sel);
  }, { now: false }));

  // ---- the scoop ------------------------------------------------------------------------------------------------
  const applyScoop = () => {
    if (!rig.synth) return;
    const now = rig.ac.currentTime, F = store.real('kick.scoopFreq'), S = rig.scoop;
    const latchOn = S.latch && now >= S.latch.start && now < S.latch.end;
    const on = S.held || latchOn;
    for (const f of [...rig.stemScoop, ...rig.synth.scoopA]) {
      const fr = f.frequency;
      fr.cancelScheduledValues(now);
      fr.setTargetAtTime(on ? F : OFF_HZ, now, 0.004);
      if (S.latch && S.latch.start > now) fr.setTargetAtTime(F, S.latch.start - 0.006, 0.002);
      if (S.latch && S.latch.end > now && !S.held) fr.setTargetAtTime(OFF_HZ, S.latch.end - 0.004, 0.003);
    }
  };
  rig.scoopHold = (held) => {
    rig.scoop.held = held;
    applyScoop();
    rig.emit('scoop');
  };
  /** Latch: the scoop for the next 4 bars, from the next bar line. Again: cancel. */
  rig.scoopLatch = () => {
    const S = rig.scoop;
    if (S.armed || S.latch) { S.armed = false; S.latch = null; applyScoop(); rig.emit('scoop'); return false; }
    if (!engine.playing) { S.armed = true; rig.emit('scoop'); return true; }
    S.armed = true;
    rig.emit('scoop');
    return true;
  };
  rig.scoopOn = () => {
    const S = rig.scoop, now = rig.ac?.currentTime ?? 0;
    return S.held || !!(S.latch && now >= S.latch.start && now < S.latch.end);
  };
  ctx.own(store.on('kick.scoopFreq', () => applyScoop(), { now: false }));

  // ---- heat: A / B / C a bar (or two) each ----------------------------------------------------------------------
  const heatTo = (pct) => {
    for (const id of HEAT.ids) {
      const p = params.get(id);
      store.modulate(id, toNorm(p, pct) - store.get(id), 'heat');
    }
  };
  rig.heatCycle = (on, per = rig.heat.per) => {
    const H = rig.heat;
    H.cycling = on; H.per = per; H.startBar = null; H.idx = -1;
    if (!on) for (const id of HEAT.ids) store.modulate(id, 0, 'heat');
    if (rig.synth && !engine.playing) { M.cur = null; applyGains(null, 0); }
    rig.emit('heat', { idx: -1, when: 0 });
  };

  // ---- the grid -------------------------------------------------------------------------------------------------
  const onBarStart = (bar, when) => {
    if (!rig.extrasLoading && engine.manifest) loadExtras();
    // A/B: the stem, then the synth, a bar each
    if (rig.sel === MODE.AB) {
      if (rig.abStart == null) rig.abStart = bar;
      sound((bar - rig.abStart) % 2 === 0 ? MODE.STEM : MODE.SYNTH, when);
    }
    // the latch
    const S = rig.scoop;
    if (S.latch && when >= S.latch.end - 0.01) { S.latch = null; later(() => rig.emit('scoop'), (when - rig.ac.currentTime) * 1000); }
    if (S.armed) {
      S.armed = false;
      S.latch = { start: when, end: when + 4 * engine.barSeconds, bar };
      applyScoop();
      later(() => rig.emit('scoop'), (when - rig.ac.currentTime) * 1000);
    }
    // the set's scooped opening, on the synth (the stem has it in its audio)
    if (rig.playing !== MODE.STEM) {
      const seq = engine.stems.sequence;
      const src = seq.length ? seq[bar % seq.length]?.kick ?? bar : bar;
      const on = store.real('kick.scoop') > 0.5 && rig.scooped.has(src);
      const F = on ? store.real('kick.scoopFreq') : OFF_HZ;
      for (const f of rig.synth.scoopB) f.frequency.setTargetAtTime(F, Math.max(when - 0.006, rig.ac.currentTime), 0.002);
    }
    // heat
    const H = rig.heat;
    if (H.cycling) {
      if (H.startBar == null) H.startBar = bar;
      const idx = Math.floor((bar - H.startBar) / H.per) % 3;
      if (idx !== H.idx) {
        H.idx = idx;
        H.at = when;
        later(() => heatTo(HEAT.abc[idx]), (when - rig.ac.currentTime) * 1000 - 30);
        rig.emit('heat', { idx, when });
      }
    }
    matchBar(when, bar);
  };

  const step = (stepNo, when, bar) => {
    if (!rig.synth) return;
    if (stepNo % 16 === 0) onBarStart(bar, when);
    const seq = engine.stems.sequence;
    const entry = seq.length ? seq[bar % seq.length] : null;
    const kickOn = !entry || (entry.kick ?? 0) >= 0;
    if (stepNo % 4 === 0 && rig.pending != null) { const m = rig.pending; rig.pending = null; sound(m, when); }
    if (stepNo % 4 === 0 && rig.queued) { rig.queued = false; if (rig.playing === MODE.STEM && !rig.solo) { rig.synth.kick(when); rig.synth.duck(when); rig.lastAudition = when; } }
    if (!kickOn || engine.stems.useMix) return;
    const synthOn = rig.playing !== MODE.STEM || rig.solo;
    const s = rig.synth;
    if (stepNo % 4 === 0) {
      rig.kicks.push(when); if (rig.kicks.length > 3) rig.kicks.shift();
      if (synthOn) { s.kick(when); s.duck(when); }
      if (store.real('ks.sample') > 0.5) {
        const hit = pickSample();
        if (hit) s.sample(when, hit.buf, hit.offset);
      }
      rig.emit('beat', { when, step: stepNo });
    } else if (stepNo % 4 === 2 && synthOn && store.real('ks.offbeatOn') > 0.5) {
      s.off(when);
    }
    if (rig.roll) {
      const dt = engine.stepSeconds;
      if (stepNo % 4 !== 0) s.kick(when, { l060: false, rumble: false, vel: 0.85 });
      if (rig.roll === 2) s.kick(when + dt / 2, { l060: false, rumble: false, vel: 0.7 });
    }
  };

  const pickSample = () => {
    if (!rig.samples.length) return null;
    return rig.samples[Math.min(rig.samples.length - 1, Math.round(store.real('ks.sampleHit')))];
  };
  rig.pickSample = pickSample;

  /** Hold: the synth's rumble alone (the stem and the kick's layers muted). */
  rig.soloRumble = (on) => {
    if (!rig.synth) return;
    rig.solo = on;
    rig.synth.soloRumble(on);
    rig.kb.mute.gain.cancelScheduledValues(rig.ac.currentTime);
    applyGains(M.cur, rig.ac.currentTime);
    rig.emit('solo', on);
  };

  /** Hear one layer now: 'kick' (all), '052', '060', 'off', 'sample'. */
  rig.audition = (what) => {
    if (!rig.synth) return;
    if (rig.ac.state !== 'running') rig.ac.resume();
    const t = rig.ac.currentTime + 0.03 + rig.synth.lat;
    const s = rig.synth;
    if (what === 'kick') { s.kick(t); s.duck(t); }
    else if (what === '052') s.kick(t, { l060: false });
    else if (what === '060') s.kick(t, { main: false, rumble: false });
    else if (what === 'off') s.off(t);
    else if (what === 'sample') {
      if (!rig.samples.length) loadExtras();
      const hit = pickSample();
      if (hit) s.sample(t - s.lat, hit.buf, hit.offset, db2g(store.real('ks.sampleLevel')));
    }
    rig.lastAudition = t;
    rig.emit('audition', { what, when: t });
  };

  // The synth's own controls are silent while the stem plays: a change plays one synth hit on the next beat.
  const SYNTH_ONLY = (id) => id.startsWith('ks.') && !['ks.source', 'ks.sample', 'ks.sampleHit', 'ks.sampleLevel'].includes(id);
  let hinted = false, auditionTimer = 0;
  ctx.own(store.onAny((id, _v, source) => {
    if (!SYNTH_ONLY(id) || source === 'init' || !rig.synth || rig.playing !== MODE.STEM || rig.solo) return;
    if (engine.playing) rig.queued = true;
    else { clearTimeout(auditionTimer); auditionTimer = setTimeout(() => rig.audition('kick'), 160); }
    if (!hinted) { hinted = true; toast('Stem is playing: the synth answers with one hit. Synth plays it every beat.', 2600); }
  }));
  ctx.own(() => clearTimeout(auditionTimer));

  // ---- meters ---------------------------------------------------------------------------------------------------
  /** Gain reduction (dB, <= 0) of the compressor that is sounding. */
  rig.reduction = () => {
    if (!rig.synth) return 0;
    const c = rig.playing === MODE.STEM ? rig.kb.comp : rig.synth.comp;
    const r = c.reduction;
    return typeof r === 'number' ? r : r?.value ?? 0;
  };
  /** Peak level (dBFS) going into that compressor over the last ~40 ms. */
  rig.compInput = () => {
    if (!rig.synth) return -90;
    const a = rig.playing === MODE.STEM ? rig.compTapStem : rig.compTapSynth;
    const buf = rig._cbuf ??= new Float32Array(a.fftSize);
    a.getFloatTimeDomainData(buf);
    let pk = 0;
    for (const x of buf) { const y = Math.abs(x); if (y > pk) pk = y; }
    return 20 * Math.log10(pk + 1e-9);
  };
  /** Correlation of left and right below 120 Hz (1 = mono), or null when silent. */
  rig.lowCorrelation = () => {
    if (!rig.synth) return null;
    const L = rig._lb ??= new Float32Array(rig.lowL.fftSize), R = rig._rb ??= new Float32Array(rig.lowR.fftSize);
    rig.lowL.getFloatTimeDomainData(L); rig.lowR.getFloatTimeDomainData(R);
    let lr = 0, ll = 0, rr = 0;
    for (let i = 0; i < L.length; i++) { lr += L[i] * R[i]; ll += L[i] * L[i]; rr += R[i] * R[i]; }
    if (ll + rr < 1e-6) return null;
    return lr / Math.sqrt(ll * rr + 1e-12);
  };
  /** Seconds since the last kick (on the grid, or an audition), for playheads. */
  rig.sinceKick = () => {
    if (!rig.ac) return Infinity;
    const now = rig.ac.currentTime;
    const ts = [...rig.kicks, rig.lastAudition ?? -1].filter((t) => t >= 0 && t <= now);
    return ts.length ? now - Math.max(...ts) : Infinity;
  };

  // ---- the engine -----------------------------------------------------------------------------------------------
  ctx.own(engine.onReady(build));
  ctx.own(engine.onStep(step));
  ctx.own(engine.onStop(() => {
    if (!rig.synth) return;
    rig.synth.panic();
    rig.scoop.latch = null; rig.scoop.armed = false;
    applyScoop();
    for (const f of rig.synth.scoopB) { f.frequency.cancelScheduledValues(0); f.frequency.setValueAtTime(OFF_HZ, rig.ac.currentTime); }
    if (rig.pending != null) { sound(rig.pending, rig.ac.currentTime); rig.pending = null; }
    if (rig.sel === MODE.AB) sound(MODE.STEM, rig.ac.currentTime);
    rig.heat.startBar = null; rig.heat.idx = -1;
    closeBar(); M.cur = null; applyGains(null, rig.ac.currentTime);
    rig.emit('scoop');
  }));

  ctx.own(() => {
    for (const t of timers) clearTimeout(t);
    timers.clear();
    fns.clear();
    for (const id of HEAT.ids) store.modulate(id, 0, 'heat');
    if (!rig.synth) return;
    if (rig.solo) rig.synth.soloRumble(false);
    const now = rig.ac.currentTime;
    rig.kb.mute.gain.cancelScheduledValues(now);
    rig.kb.set('mute', 0);
    for (const f of rig.stemScoop) { f.frequency.cancelScheduledValues(0); f.frequency.setTargetAtTime(OFF_HZ, now, 0.004); }
    try { rig.kb.output.disconnect(rig.tapNodes.sum); } catch { /* gone */ }
    try { rig.kb.compIn.disconnect(rig.compTapStem); } catch { /* gone */ }
    rig.synth.dispose();
    rig.synth = null;
  });
  return rig;
}

/** Bars of the kick stem that are scooped (their sub under 60 Hz well below the stem's usual share). */
function scoopedBars(buf, barSeconds) {
  if (scoopedCache.has(buf)) return scoopedCache.get(buf);
  const fs = buf.sampleRate, n = Math.round(barSeconds * fs), d = buf.getChannelData(0);
  const a = 1 - Math.exp((-2 * Math.PI * 60) / fs);
  const ratios = [];
  let l1 = 0, l2 = 0;
  for (let b = 0; (b + 1) * n <= d.length; b++) {
    let lo = 0, all = 0;
    for (let i = b * n; i < (b + 1) * n; i += 2) { const x = d[i]; l1 += (x - l1) * a * 2; l2 += (l1 - l2) * a * 2; lo += l2 * l2; all += x * x; }
    ratios.push(all > 1e-9 ? lo / all : 1);
  }
  const sorted = [...ratios].sort((x, y) => x - y);
  const median = sorted[Math.floor(sorted.length / 2)] ?? 1;
  const out = new Set(ratios.map((r, i) => (r < median * 0.6 ? i : -1)).filter((i) => i >= 0));
  scoopedCache.set(buf, out);
  return out;
}

/** Seconds before a hit's first sound (an MP3 decoder's padding), less 1 ms. */
function onset(buf) {
  if (onsetCache.has(buf)) return onsetCache.get(buf);
  const d = buf.getChannelData(0);
  let peak = 0;
  for (let i = 0; i < Math.min(d.length, buf.sampleRate * 0.1); i++) peak = Math.max(peak, Math.abs(d[i]));
  let i = 0;
  while (i < d.length && Math.abs(d[i]) < peak * 0.05) i++;
  const s = Math.max(0, i / buf.sampleRate - 0.001);
  onsetCache.set(buf, s);
  return s;
}

