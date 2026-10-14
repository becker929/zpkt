// The one-hit scope: whenever a kick param moves, the synth renders four beats offline (OfflineAudioContext) and the
// last one is drawn: its waveform and its spectrum, over the set's own kick hit (cut from the stem) in acid. Two
// meters put it against the references: the 31.6 Hz band (HW002 -34.4 dB, the references -27.6 to -22.6) and the
// crest (HW002 8.7 dB, the references 4.4 to 6.6: denser is lower). Both move by what the synth's change moves:
// "HW002 + your change", an estimate, since the kick is most of the mix's sub and most of its peaks.

import { h } from '../ui.js';
import { setNorm, toReal } from '../params.js';
import { BEAT, REF, g2db, noteName, spectrum } from './dsp.js';
import { renderBeats } from './synth.js';
import { C, MONO, canvas, logAxis, panel, rgba } from './util.js';

const AX = logAxis(20, 16000);

/** Mono of `buf` from `at` s for one beat. */
function beatOf(buf, at, offset = 0) {
  const fs = buf.sampleRate, n = Math.round(BEAT * fs), i0 = Math.round((at + offset) * fs);
  const L = buf.getChannelData(0), R = buf.numberOfChannels > 1 ? buf.getChannelData(1) : L;
  const x = new Float32Array(n);
  for (let i = 0; i < n; i++) { const j = i0 + i; x[i] = j < L.length ? (L[j] + R[j]) * 0.5 : 0; }
  return x;
}

function analyse(x, fs) {
  const spec = spectrum(x, fs, 32768);
  let pk = 0, ss = 0;
  for (const v of x) { const a = Math.abs(v); if (a > pk) pk = a; ss += v * v; }
  const rms = Math.sqrt(ss / x.length);
  const curve = [];
  for (let i = 0; i <= 180; i++) { const f = AX.f(i / 180, 1); curve.push([f, spec.at(f, 6)]); }
  return { x, sub: spec.bandDb(28.2, 35.5), peak: g2db(pk), rms: g2db(rms), crest: g2db(pk) - g2db(rms), curve };
}

export function hitScope(ctx, rig, painter) {
  const { store, params } = ctx;
  const cvWave = canvas('kx-scope-wave');
  const cvSpec = canvas('kx-scope-spec');
  const subRead = h('span', { class: 'kx-meter-read' });
  const crestRead = h('span', { class: 'kx-meter-read' });
  const subBar = meterBar();
  const crestBar = meterBar();
  const info = h('div', { class: 'kx-scope-info' });
  const busy = h('i', { class: 'kx-scope-busy' });
  const el = panel('One hit', { sub: 'the synth, rendered on every change', cls: 'kx-scope' },
    h('div', { class: 'kx-scope-screen' }, cvWave, h('span', { class: 'kx-scope-tag', text: 'WAVE · ONE BEAT' }), busy),
    h('div', { class: 'kx-scope-screen is-spec' }, cvSpec, h('span', { class: 'kx-scope-tag', text: 'SPECTRUM' }),
      h('span', { class: 'kx-scope-key' }, h('i', { class: 'is-synth' }), 'synth ', h('i', { class: 'is-set' }), 'the set\'s kick')),
    info,
    h('div', { class: 'kx-meter' }, h('div', { class: 'kx-meter-head' }, h('b', { text: 'DEEP SUB · 31.6 Hz' }), subRead), subBar.el),
    h('div', { class: 'kx-meter' }, h('div', { class: 'kx-meter-head' }, h('b', { text: 'DENSITY · CREST' }), crestRead), crestBar.el),
    h('p', { class: 'rack-note', text: 'Raise the 30 Hz and 35 Hz shelves, the rumble\'s sub, or drop the pitch end, and the sub needle moves towards the references. More heat and compression lower the crest: a denser kick.' }));

  const S = { now: null, base: null, ghost: null, busy: false, again: false };
  const kickIds = params.stage('kick').map((p) => p.id);
  const setValues = () => Object.fromEntries(params.stage('kick').map((p) => [p.id, toReal(p, setNorm(p))]));
  const fsNow = () => rig.ac?.sampleRate ?? 44100;

  const run = async () => {
    if (S.busy) { S.again = true; return; }
    S.busy = true; el.classList.add('is-busy');
    try {
      const fs = fsNow();
      if (!S.base || S.base.fs !== fs) {
        const b = await renderBeats(setValues(), { sampleRate: fs });
        S.base = { ...analyse(beatOf(b.buffer, b.at), fs), fs };
      }
      const r = await renderBeats(rig.values(), { sampleRate: fs });
      if (!alive) return;
      S.now = analyse(beatOf(r.buffer, r.at), fs);
      S.now.full = r.buffer;
      update();
    } catch (err) {
      console.error(err);
    } finally {
      S.busy = false; el.classList.remove('is-busy');
      if (S.again && alive) { S.again = false; schedule(); }
    }
  };
  let timer = 0, alive = true;
  const schedule = () => { clearTimeout(timer); timer = setTimeout(run, 140); };
  ctx.own(() => { alive = false; clearTimeout(timer); });
  ctx.own(store.onAny((id) => { if (kickIds.includes(id) && !id.startsWith('ks.source') && !id.startsWith('ks.sample')) schedule(); }));

  const ghost = () => {
    const hit = rig.samples[0];
    if (!hit || S.ghost) return;
    S.ghost = analyse(beatOf(hit.buf, 0, hit.offset), hit.buf.sampleRate);
    update();
  };
  ctx.own(rig.on((type) => { if (type === 'samples') ghost(); if (type === 'ready') schedule(); }));
  ghost();

  const redrawWave = painter.add(cvWave.parentNode, () => drawWave(cvWave, S));
  const redrawSpec = painter.add(cvSpec.parentNode, () => drawSpec(cvSpec, S));
  function update() {
    redrawWave(); redrawSpec();
    if (!S.now || !S.base) return;
    const dSub = S.now.sub - S.base.sub;
    const est = REF.sub.hw + dSub;
    subRead.textContent = `${est.toFixed(1)} dB  (${dSub >= 0 ? '+' : ''}${dSub.toFixed(1)})`;
    subBar.set({ lo: -42, hi: -18, set: REF.sub.hw, now: est, zone: [REF.sub.lo, REF.sub.hi], labels: ['HW002', 'REFS'] });
    const dCrest = S.now.crest - S.base.crest;
    const cest = REF.crest.hw + dCrest;
    crestRead.textContent = `${cest.toFixed(1)} dB  (${dCrest >= 0 ? '+' : ''}${dCrest.toFixed(1)})`;
    crestBar.set({ lo: 14, hi: 2, set: REF.crest.hw, now: cest, zone: [REF.crest.hi, REF.crest.lo], labels: ['HW002', 'REFS'] });
    const end = store.real('ks.pitchEnd');
    info.replaceChildren(
      cell('PEAK', `${S.now.peak.toFixed(1)} dB`), cell('RMS', `${S.now.rms.toFixed(1)} dB`),
      cell('LANDS ON', `${Math.round(end)} Hz ${noteName(end)}`),
      S.ghost ? cell('SET PK/RMS', `${S.ghost.peak.toFixed(1)}/${S.ghost.rms.toFixed(1)}`) : cell('SET PK/RMS', '...'));
  }
  schedule();
  return el;
}

const cell = (k, v) => h('div', { class: 'kx-cell' }, h('span', { text: k }), h('b', { text: v }));

/** A horizontal meter: a scale from lo to hi, the references' zone, HW002's mark and the estimate's needle. */
function meterBar() {
  const zone = h('i', { class: 'kx-mb-zone' }), set = h('i', { class: 'kx-mb-set' }), now = h('i', { class: 'kx-mb-now' });
  const fill = h('i', { class: 'kx-mb-fill' });
  const zl = h('span', { class: 'kx-mb-zl', text: 'REFS' }), sl = h('span', { class: 'kx-mb-sl', text: 'HW002' });
  const el = h('div', { class: 'kx-mb' }, h('div', { class: 'kx-mb-track' }, zone, fill, set, now), zl, sl);
  return {
    el,
    set({ lo, hi, set: sv, now: nv, zone: [z0, z1] }) {
      const x = (v) => `${Math.max(0, Math.min(1, (v - lo) / (hi - lo))) * 100}%`;
      const a = (v) => Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
      zone.style.left = `${Math.min(a(z0), a(z1)) * 100}%`;
      zone.style.width = `${Math.abs(a(z1) - a(z0)) * 100}%`;
      zl.style.left = `${((a(z0) + a(z1)) / 2) * 100}%`;
      set.style.left = x(sv); sl.style.left = x(sv);
      now.style.left = x(nv);
      fill.style.left = `${Math.min(a(sv), a(nv)) * 100}%`;
      fill.style.width = `${Math.abs(a(nv) - a(sv)) * 100}%`;
      const inZone = a(nv) >= Math.min(a(z0), a(z1)) && a(nv) <= Math.max(a(z0), a(z1));
      el.classList.toggle('is-in', inZone);
      el.classList.toggle('is-better', a(nv) > a(sv) + 0.005);
    },
  };
}

function drawWave(cv, S) {
  const { g, W, H, k } = cv.fit();
  g.fillStyle = '#050606'; g.fillRect(0, 0, W, H);
  g.fillStyle = 'rgba(255,255,255,0.05)';
  g.fillRect(0, H / 2, W, k);
  for (let i = 1; i < 4; i++) g.fillRect((i / 4) * W, 0, k, H);
  g.font = `600 ${8.5 * k}px ${MONO}`; g.fillStyle = C.text3; g.textAlign = 'center';
  g.fillText('OFF', W / 2, H - 4 * k);
  const plot = (x, color, fill) => {
    const n = x.length, cols = Math.floor(W / k);
    g.beginPath();
    const lows = [];
    for (let c = 0; c < cols; c++) {
      const i0 = Math.floor((c / cols) * n), i1 = Math.floor(((c + 1) / cols) * n);
      let lo = 0, hi = 0;
      for (let i = i0; i < i1; i++) { if (x[i] < lo) lo = x[i]; if (x[i] > hi) hi = x[i]; }
      const xx = (c / cols) * W;
      g.lineTo(xx, H / 2 - hi * H * 0.47);
      lows.push([xx, H / 2 - lo * H * 0.47]);
    }
    for (let i = lows.length - 1; i >= 0; i--) g.lineTo(lows[i][0], lows[i][1]);
    g.closePath();
    if (fill) { g.fillStyle = fill; g.fill(); }
    g.strokeStyle = color; g.lineWidth = k; g.stroke();
  };
  if (S.ghost) plot(S.ghost.x, rgba(C.acid, 0.55), null);
  if (S.now) { g.shadowColor = C.hazard; g.shadowBlur = 6 * k; plot(S.now.x, C.hazard, rgba(C.hazard, 0.35)); g.shadowBlur = 0; }
  g.fillStyle = 'rgba(0,0,0,0.2)';
  for (let y = 0; y < H; y += 3 * k) g.fillRect(0, y, W, k);
}

function drawSpec(cv, S) {
  const { g, W, H, k } = cv.fit();
  const top = 0, bot = -84;
  const y = (db) => ((top - db) / (top - bot)) * (H - 14 * k);
  g.fillStyle = '#050606'; g.fillRect(0, 0, W, H);
  // the sub the references have: 25-60 Hz
  g.fillStyle = rgba(C.cold, 0.08);
  g.fillRect(AX.x(25, W), 0, AX.x(60, W) - AX.x(25, W), H);
  g.fillStyle = rgba(C.cold, 0.5);
  g.fillRect(AX.x(31.6, W), 0, k, H - 14 * k);
  g.font = `600 ${8.5 * k}px ${MONO}`; g.textAlign = 'center';
  for (const f of [20, 50, 100, 200, 500, 1000, 2000, 5000, 10000]) {
    const x = AX.x(f, W);
    g.fillStyle = 'rgba(255,255,255,0.06)'; g.fillRect(x, 0, k, H - 14 * k);
    g.fillStyle = C.text3; g.fillText(f >= 1000 ? `${f / 1000}k` : String(f), x, H - 3 * k);
  }
  for (let db = -12; db > bot; db -= 12) { g.fillStyle = 'rgba(255,255,255,0.04)'; g.fillRect(0, y(db), W, k); }
  g.fillStyle = rgba(C.cold, 0.85); g.textAlign = 'left'; g.fillText('SUB', AX.x(25, W) + 3 * k, H - 18 * k);
  const line = (curve, color, fill, dash) => {
    g.beginPath();
    curve.forEach(([f, db], i) => { const xx = AX.x(f, W), yy = y(Math.max(bot, db)); if (i === 0) g.moveTo(xx, yy); else g.lineTo(xx, yy); });
    if (fill) {
      g.save(); g.lineTo(W, H - 14 * k); g.lineTo(0, H - 14 * k); g.closePath();
      const grd = g.createLinearGradient(0, 0, 0, H); grd.addColorStop(0, rgba(color, 0.45)); grd.addColorStop(1, rgba(color, 0.02));
      g.fillStyle = grd; g.fill(); g.restore();
      g.beginPath();
      curve.forEach(([f, db], i) => { const xx = AX.x(f, W), yy = y(Math.max(bot, db)); if (i === 0) g.moveTo(xx, yy); else g.lineTo(xx, yy); });
    }
    g.setLineDash(dash ? [4 * k, 3 * k] : []);
    g.strokeStyle = color; g.lineWidth = 1.5 * k; g.stroke(); g.setLineDash([]);
  };
  if (S.ghost) line(S.ghost.curve, C.acid, false, true);
  if (S.now) line(S.now.curve, C.hazard, true, false);
}
