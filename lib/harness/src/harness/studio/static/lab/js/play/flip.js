// Flip: A/B inside the track, the way Anthony compares. Two sides (the knobs now, a snapshot slot A to D, or the
// set) swap every bar or every two bars, on the bar line, for as long as it is on. Nothing is written: the other
// side is a modulation over every knob that differs, and it lets go when Flip stops.

import { haptic, toast } from '../ui.js';
import { setNorm } from '../params.js';
import { C, canvas2d, load, rgba, save, segments, shell, MONO } from './room.js';

const SIDES = ['Now', 'A', 'B', 'C', 'D', 'Set'];

export function flip(room) {
  const { store, params } = room;
  const m = shell(room, {
    key: 'flip', title: 'Flip', sub: 'A/B every bar, on the bar line', power: true,
    note: 'Pick two sides and turn it on: they swap on every bar line (or every two). Save snapshots with the A to D buttons up top or the cube; Now is the knobs as they are.',
  });
  m.output = room.out('flip');
  const S = canvas2d(room, m.view);
  const st = { a: load('flip.a', 0), b: load('flip.b', 1), every: load('flip.every', 1), side: 0, lastSide: -1, diff: 0 };
  const segA = segments(SIDES, st.a, (i) => { st.a = i; save('flip.a', i); });
  const segB = segments(SIDES, st.b, (i) => { st.b = i; save('flip.b', i); });
  const segE = segments(['Every bar', 'Every 2'], st.every === 2 ? 1 : 0, (i) => { st.every = i ? 2 : 1; save('flip.every', st.every); });
  const label = (t) => { const el = document.createElement('span'); el.className = 'pl-flip-l'; el.textContent = t; return el; };
  const rows = [[label('Side 1'), segA.el], [label('Side 2'), segB.el]].map(([l, s]) => { const r = document.createElement('div'); r.className = 'pl-row pl-flip-row'; r.append(l, s); return r; });
  m.tools.append(...rows, segE.el);

  const ids = params.list.filter((p) => p.stage !== 'play').map((p) => p.id);
  /** The values a side stands for, or null for the knobs as they are. */
  const values = (i) => {
    if (i === 0) return null;
    if (i === 5) return Object.fromEntries(ids.map((id) => [id, setNorm(params.get(id))]));
    return store.slots[i - 1] ?? undefined;
  };
  m.onPower = (on, user) => {
    st.lastSide = -1;
    if (on && user) {
      const missing = [st.a, st.b].filter((i) => i >= 1 && i <= 4 && !store.slots[i - 1]).map((i) => SIDES[i]);
      if (missing.length) toast(`Slot ${missing.join(' and ')} is empty: it plays the knobs as they are`);
      if (st.a === st.b) toast('Both sides are the same');
    }
  };

  m.sim = () => {
    const c = room.clock();
    st.side = Math.floor(Math.floor(c.tRaw) / st.every) % 2;
    if (!m.on) return;
    if (st.side !== st.lastSide) { st.lastSide = st.side; if (room.ratio(m) > 0) haptic(true); }
    const va = values(st.a), vb = values(st.b);
    const of = (v, id) => (v && id in v ? v[id] : store.get(id));
    const v = st.side ? vb : va;
    const pairs = [];
    let n = 0;
    for (const id of ids) {
      if (Math.abs(of(va, id) - of(vb, id)) > 1e-4) n++;
      if (!v || !(id in v)) continue;
      const d = v[id] - store.get(id);
      if (Math.abs(d) > 1e-4) pairs.push([id, d]);
    }
    st.diff = n;
    m.output.frame(pairs);
  };

  m.draw = () => {
    const { g, w: W, h: H } = S.fit();
    const c = room.clock();
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#060607'; g.fillRect(0, 0, W, H);
    const half = (W - 30) / 2;
    [st.a, st.b].forEach((sideIx, k) => {
      const x = 10 + k * (half + 10), y = 10, w = half, hh = H - 48;
      const live = m.on && st.side === k;
      const full = sideIx === 0 || sideIx === 5 || !!store.slots[sideIx - 1];
      const gr = g.createLinearGradient(0, y, 0, y + hh);
      gr.addColorStop(0, live ? '#2a0b29' : '#16171b'); gr.addColorStop(0.5, live ? '#1a0619' : '#0f1013'); gr.addColorStop(0.5, '#050506'); gr.addColorStop(1, live ? '#220820' : '#121316');
      g.fillStyle = gr; g.fillRect(x, y, w, hh);
      g.strokeStyle = live ? C.magenta : 'rgba(255,255,255,0.1)'; g.lineWidth = live ? 2 : 1; g.strokeRect(x + 0.5, y + 0.5, w - 1, hh - 1);
      g.fillStyle = '#000'; g.fillRect(x, y + hh / 2 - 1, w, 2);
      g.textAlign = 'center'; g.textBaseline = 'middle';
      g.font = `italic 900 ${Math.min(64, hh * 0.55)}px -apple-system, "Helvetica Neue", Arial, sans-serif`;
      g.fillStyle = live ? '#fff' : full ? C.text2 : C.text3;
      if (live) { g.shadowColor = C.magenta; g.shadowBlur = 18; }
      g.fillText(SIDES[sideIx].toUpperCase(), x + w / 2, y + hh / 2 + 2);
      g.shadowBlur = 0;
      g.font = `700 9.5px ${MONO}`; g.fillStyle = full ? C.text3 : C.alarm;
      g.fillText(sideIx === 0 ? 'THE KNOBS' : sideIx === 5 ? 'THE SET' : full ? `SLOT ${SIDES[sideIx]}` : 'EMPTY SLOT', x + w / 2, y + hh - 10);
      g.beginPath(); g.arc(x + 12, y + 12, 4.5, 0, Math.PI * 2); g.fillStyle = live ? C.cold : '#14222b'; g.fill();
    });
    // the bars, as a strip
    const n = st.every * 2, f = ((((c.tRaw / n) % 1) + 1) % 1);
    for (let i = 0; i < n; i++) {
      const x = 10 + i * (W - 20) / n, w = (W - 20) / n - 4;
      g.fillStyle = Math.floor(i / st.every) % 2 ? rgba(C.magenta, 0.25) : 'rgba(255,255,255,0.08)';
      g.fillRect(x, H - 14, w, 6);
    }
    g.fillStyle = m.on ? C.cold : C.text3; g.fillRect(10 + f * (W - 20) - 1, H - 17, 2, 12);
    g.textAlign = 'right'; g.font = `600 9.5px ${MONO}`; g.fillStyle = C.text3; g.textBaseline = 'alphabetic';
    g.fillText(m.on ? `THE SIDES DIFFER IN ${st.diff} KNOB${st.diff === 1 ? '' : 'S'}` : 'OFF', W - 10, H - 23);
  };
  return room.add(m);
}
