// RACK: each tape's chain as a rack of the set's own knobs (Live's devices, as the inspector names them), the Break
// bus as an FX unit the break sources pass through (with a scope of its wavefolder and the signal going through it),
// and the collage console: a fader and an LED ladder per bus.

import { h, haptic } from '../ui.js';
import { fader } from '../widgets/fader.js';
import { control, rack } from '../surfaces/racks.js';
import { state } from './state.js';
import { fit, icon } from './bits.js';

const clamp = (x, a = 0, b = 1) => Math.min(b, Math.max(a, x));

export default function rackPanel(C) {
  const { store } = C;
  const params = C.ctx.params;
  const stage = params.stage('collage');
  const keysOf = (p) => [].concat(p.sketch ?? []).map((k) => k.split('@')[0]);
  const paramsFor = (id) => stage.filter((p) => keysOf(p).some((k) => k.startsWith(`col.${id}.`)) || (id === 'rs' && keysOf(p).includes('col.wash')));
  const levelOf = (id) => paramsFor(id).find((p) => keysOf(p).includes(`col.${id}.gain`));

  const racks = h('div', { class: 'cr-racks' });
  const meters = [];
  const ledMeter = (busName, getLevel) => {
    const cv = h('canvas', { class: 'cr-led' });
    meters.push({ cv, busName, getLevel, F: null, hold: -60, holdT: 0 });
    return cv;
  };

  const sourceRack = (src) => {
    const ps = paramsFor(src.kind === 'rs' ? 'rs' : src.id);
    const hear = h('button', { type: 'button', class: 'cl-push cr-hear', 'aria-label': `Hear ${src.name}` }, icon('ear'));
    hear.addEventListener('click', () => { haptic(); C.select(src.id); C.audition(src.id); });
    const route = h('span', { class: `cr-route${src.brk ? ' is-brk' : ''}`, text: src.brk ? 'BREAK BUS' : 'TAPE' });
    const r = rack(src.name, { sub: src.long, note: ps.length ? null : 'No knob of its own in the set: its level sits in the console below.', cls: 'cr-rack' },
      ...ps.map((p) => control(C.ctx, p.id, { size: 68 })));
    r.style.setProperty('--tc', src.color);
    r.dataset.src = src.id;
    r.querySelector('.rack-head').append(route, ledMeter(src.bus), hear);
    return r;
  };

  // --- the Break bus FX unit -------------------------------------------------------------------------------------
  const scope = h('canvas', { class: 'cr-scope' });
  const decay = h('canvas', { class: 'cr-decay' });
  const breakIds = ['col.breakColour', 'col.breakFold', 'col.breakSpace', 'col.breakDecay'];
  const brk = rack('Break bus', { sub: 'COLDFIRE (colour, wavefold) > Hybrid > Compressor', cls: 'cr-fx', note: 'The synth, the horn, the 10-07 recording and the beatbox pass through it. Fold: more drive into the wavefolder. Space: the Hybrid reverb\'s wet; decay its length.' },
    h('div', { class: 'cr-fx-screens' }, h('div', { class: 'cr-screen' }, scope, h('span', { text: 'FOLD' })), h('div', { class: 'cr-screen' }, decay, h('span', { text: 'HYBRID' }))),
    ...breakIds.map((id) => control(C.ctx, id, { size: 72 })));
  const brkMeter = ledMeter('col-break');
  const brkMeterEntry = meters.pop();
  brk.querySelector('.rack-head').append(brkMeter);

  // --- the console ---------------------------------------------------------------------------------------------------
  const strips = h('div', { class: 'cr-console' });
  const consoleRack = rack('Collage console', { sub: 'every tape\'s level, and the collage out', cls: 'cr-con' }, strips);

  let lastCount = -1;
  const build = () => {
    lastCount = C.ready ? C.sources.length : -1;
    racks.replaceChildren();
    strips.replaceChildren();
    meters.length = 0;
    const list = C.ready ? C.sources : [];
    const order = [...list].sort((a, b) => (a.id === state.sel ? -1 : b.id === state.sel ? 1 : 0));
    const clips = order.filter((s) => s.kind === 'clip');
    for (const s of clips) racks.append(sourceRack(s));
    if (list.some((s) => s.kind === 'rs')) racks.append(sourceRack(list.find((s) => s.kind === 'rs')));
    racks.append(brk);
    meters.push(brkMeterEntry);
    for (const s of [...list.filter((x) => x.kind === 'clip'), { id: 'rs', name: 'Resample', bus: 'col-rs', color: '#f2ecdf' }]) {
      const p = levelOf(s.id);
      if (!p) continue;
      strips.append(h('div', { class: 'cr-strip', style: { '--tc': s.color } }, fader(C.ctx, p.id, { length: 150, thin: true, label: s.name }), ledMeter(s.bus)));
    }
    strips.append(h('div', { class: 'cr-strip is-out' }, fader(C.ctx, 'col.out', { length: 150, thin: true, label: 'Out' }), ledMeter('out', () => C.G?.meter)));
    racks.append(consoleRack);
    if (!list.length) racks.prepend(h('p', { class: 'rack-note', text: 'Start the engine to load the tapes and their chains.' }));
  };
  // Racks are rebuilt only when the tapes change (their widgets follow the store themselves). Widgets register their
  // store listeners with the surface; a rebuild leaves the old ones listening until the tab closes, so it is rare.
  C.own(C.ev.on('ready', build));
  C.own(C.ev.on('sources', () => { if (C.sources.length !== lastCount) build(); }));
  build();

  const el = h('section', { class: 'cl-panel cr', 'aria-label': 'Rack' }, racks);

  // --- drawing ---------------------------------------------------------------------------------------------------
  const tbuf = new Float32Array(1024);
  let S = null, D = null;
  const drawScope = () => {
    S ??= fit(scope);
    const g = S.g, W = scope.width, H = scope.height, d = S.dpr;
    g.fillStyle = '#060807'; g.fillRect(0, 0, W, H);
    g.strokeStyle = 'rgba(224,183,255,0.12)'; g.lineWidth = d;
    g.beginPath(); g.moveTo(W / 2, 0); g.lineTo(W / 2, H); g.moveTo(0, H / 2); g.lineTo(W, H / 2); g.stroke();
    // the transfer curve the fold knob makes
    const f = store.live('col.breakFold');
    const drive = 0.04 + 0.52 * f, mix = 0.15 + 0.65 * f;
    const pre = Math.pow(10, (drive * 36) / 20), post = Math.pow(10, -(drive * 36 * 0.72) / 20);
    g.strokeStyle = '#e0b7ff'; g.lineWidth = 2 * d; g.shadowColor = '#e0b7ff'; g.shadowBlur = 6 * d;
    g.beginPath();
    for (let i = 0; i <= 120; i++) {
      const x = i / 60 - 1;
      const folded = Math.sin(clamp(x * pre, -1, 1) * Math.PI * 1.5) * 0.9;
      const y = (1 - mix) * x + mix * post * folded * 3;
      const px = (i / 120) * W, py = H / 2 - clamp(y, -1, 1) * H * 0.42;
      if (i) g.lineTo(px, py); else g.moveTo(px, py);
    }
    g.stroke(); g.shadowBlur = 0;
    // the signal through the Break bus now
    if (C.ready) {
      const m = C.engine.bus('col-break').meter;
      m.getFloatTimeDomainData(tbuf);
      g.strokeStyle = 'rgba(198,255,61,0.8)'; g.lineWidth = 1.2 * d;
      g.beginPath();
      for (let i = 0; i < 256; i++) { const x = (i / 255) * W, y = H / 2 - clamp(tbuf[i * 4] * 2.5, -1, 1) * H * 0.42; if (i) g.lineTo(x, y); else g.moveTo(x, y); }
      g.stroke();
    }
  };
  const drawDecay = () => {
    D ??= fit(decay);
    const g = D.g, W = decay.width, H = decay.height, d = D.dpr;
    g.fillStyle = '#060807'; g.fillRect(0, 0, W, H);
    const secs = store.real('col.breakDecay'), wet = store.live('col.breakSpace');
    const span = 10;
    g.fillStyle = 'rgba(224,183,255,0.22)'; g.strokeStyle = '#e0b7ff'; g.lineWidth = 1.5 * d;
    g.beginPath(); g.moveTo(0, H);
    for (let i = 0; i <= 80; i++) { const t = (i / 80) * span; const a = Math.pow(Math.max(0, 1 - t / secs), 2.4) * wet; g.lineTo((i / 80) * W, H - a * H * 0.85); }
    g.lineTo(W, H); g.closePath(); g.fill(); g.stroke();
    g.fillStyle = 'rgba(233,231,226,0.8)'; g.font = `600 ${9 * d}px ui-monospace, monospace`;
    g.fillText(`${secs.toFixed(1)} s`, W - 34 * d, 12 * d);
  };
  const drawMeters = (t) => {
    for (const m of meters) {
      if (!m.cv.isConnected) continue;
      m.F ??= fit(m.cv);
      const g = m.F.g, W = m.cv.width, H = m.cv.height;
      let db = -70;
      if (C.ready) {
        const an = m.getLevel ? m.getLevel() : C.engine.buses.get(m.busName)?.meter;
        if (an) {
          an.getFloatTimeDomainData(tbuf);
          let pk = 0;
          for (let i = 0; i < an.fftSize && i < tbuf.length; i++) { const a = Math.abs(tbuf[i]); if (a > pk) pk = a; }
          db = 20 * Math.log10(pk + 1e-9);
        }
      }
      if (db > m.hold || t - m.holdT > 1000) { m.hold = db; m.holdT = t; }
      const vert = H > W;
      const n = vert ? 14 : 10;
      g.clearRect(0, 0, W, H);
      for (let i = 0; i < n; i++) {
        const lvl = -48 + (i / (n - 1)) * 48;
        const on = db >= lvl;
        const col = i >= n - 1 ? '255,46,77' : i >= n - 3 ? '255,181,71' : '198,255,61';
        g.fillStyle = `rgba(${col},${on ? 0.95 : 0.12})`;
        if (vert) g.fillRect(0, H - ((i + 1) / n) * H + 1, W, H / n - 2);
        else g.fillRect((i / n) * W + 1, 0, W / n - 2, H);
      }
    }
  };

  return {
    el,
    show() {
      const r = racks.querySelector(`[data-src="${state.sel}"]`);
      if (r) el.scrollTop = Math.max(0, r.offsetTop - 8);
    },
    draw(t) { drawScope(); drawDecay(); drawMeters(t); },
  };
}
