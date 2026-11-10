// Crystal: the six gaps between HW002 and its references, as the six points of a glass crystal.
//
// Each point is an aspect of the mix made of several of the set's knobs (sub: the 30 Hz shelves; colour: the
// kick-bus bell's frequency and gain and the hats' 1 kHz bell; and so on). At the inner ring every knob is at the
// set's value; at the rim each is at the far end of the range its experiment tried. Never outside it. Pull a point
// out to move that aspect toward the references; drag the crystal's heart up to grow all six at once (the "one
// joint climb over all the knobs" idea). Set, Centre and Far end put all six at the two ends and the middle of the
// tried ranges: Anthony's three alternatives. Writes knobs (one undo step per touch); a blue outline shows what is
// heard when other machines modulate the same knobs.

import { h, haptic, toast } from '../ui.js';
import { setNorm, toNorm } from '../params.js';
import { C, btn, canvas2d, clamp, pointers, rgba, shell, MONO } from './room.js';
import { camera, cross, mul, norm, rx, ry, sub, tf } from './proj.js';

const ASPECTS = [
  { key: 'SUB', about: 'Sub: the 30 Hz shelf on the kick bus, the rumble\'s 31 Hz shelf, the 35 Hz shelf. HW002 sits 7 to 9 dB under the references from 25 to 40 Hz.',
    parts: [['kick.sub30', 4.75], ['rumble.sub', 2.98], ['kick.sub35', 0.21]] },
  { key: 'COLOUR', about: 'Colour: the kick-bus bell moves from 484 Hz to 2.2 kHz and pushes harder, the hats get up to +4 dB at 1 kHz. The mids are 6 to 8 dB under the references.',
    parts: [['kick.colourFreq', 2184], ['kick.colour', 7.58], ['mix.hatsBell', 4.01]] },
  { key: 'DRIVE', about: 'Distortion: COLDFIRE on the kick bus and the rumble\'s Decapitator toward 50 %, the kick-bus compressor down to -8 dB. "The kick needs more distortion."',
    parts: [['kick.drive', 50], ['rumble.drive', 50], ['kick.thresh', -8]] },
  { key: 'MONO', about: 'Mono low end: the Main\'s bass mono comes on (past a fifth of the way) and rises from 120 to 169 Hz; the rumble goes mono past 40 %. The references are mono down there.',
    parts: [['mix.bassMono', 1, 0.2], ['rumble.mono', 1, 0.4], ['mix.monoFreq', 169.3]] },
  { key: 'SPACE', about: 'Space: Supermassive on the hats opens up, mix 28 to 43 %, feedback to 84 %, delay to 37 %, density to 98 %, high cut to 65 %. "Colour and space is missing."',
    parts: [['mix.spaceMix', 42.7], ['mix.spaceFeedback', 83.5], ['mix.spaceDelay', 36.5], ['mix.spaceDensity', 98.4], ['mix.spaceHighCut', 64.9]] },
  { key: 'DARK', about: 'Less air: the 5 kHz shelves come down on the kick bus, the rumble and the hats. HW002\'s air is about 5 dB high near 10 kHz.',
    parts: [['kick.air', -11.57], ['rumble.air', -6.82], ['mix.hatsAir', -2.34]] },
];
const TAU = Math.PI * 2;

export function crystal(room) {
  const { store, params } = room;
  const m = shell(room, { key: 'crystal', title: 'Crystal', sub: 'six gaps to the references' });
  const S = canvas2d(room, m.view);
  const note = h('p', { class: 'rack-note pl-note is-live', text: 'Pull a point out: that aspect moves toward the references. Drag the heart up: all six at once. Inner ring: the set. Rim: the far end of what was tried. Double tap a point (or the heart) to go back.' });
  m.el.append(note);

  for (const A of ASPECTS) {
    A.ps = A.parts.filter(([id]) => params.has(id)).map(([id, to, thr]) => {
      const p = params.get(id);
      return { id, p, thr, sN: setNorm(p), tN: p.scale === 'toggle' ? 1 : toNorm(p, to) };
    });
  }
  const read = (A, get) => {
    let s = 0, n = 0;
    for (const q of A.ps) {
      if (q.p.scale === 'toggle' || Math.abs(q.tN - q.sN) < 1e-6) continue;
      s += clamp((get(q.id) - q.sN) / (q.tN - q.sN)); n++;
    }
    return n ? s / n : 0;
  };
  const write = (A, v) => {
    v = clamp(v);
    for (const q of A.ps) {
      const val = q.p.scale === 'toggle' ? (v >= (q.thr ?? 0.5) ? 1 : q.sN) : q.sN + (q.tN - q.sN) * v;
      store.set(q.id, val, { source: 'crystal' });
    }
  };
  const all = (v, label) => {
    store.begin();
    for (const A of ASPECTS) write(A, v);
    store.end();
    haptic(true);
    toast(label);
  };
  m.tools.append(
    btn('Set', () => all(0, 'Crystal: every aspect at the set')),
    btn('Centre', () => all(0.5, 'Crystal: the middle of every tried range')),
    btn('Far end', () => all(1, 'Crystal: the far end of every tried range')));

  // --- geometry: the six points on screen, from the last frame -----------------------------------------------------
  let geo = null, drag = null, lastTap = { k: null, t: -1e9 };
  const vals = () => ASPECTS.map((A) => read(A, (id) => store.get(id)));

  pointers(S.cv, {
    down(p) {
      if (!geo) return;
      let best = null, bd = 40;
      if (Math.hypot(p.x - geo.cx, p.y - geo.cy) < 20) best = 'all';
      else geo.handles.forEach((hd, k) => { const d = Math.hypot(p.x - hd.x, p.y - hd.y); if (d < bd) { bd = d; best = k; } });
      if (best == null) { drag = null; return; }
      const now = performance.now();
      if (lastTap.k === best && now - lastTap.t < 320) {
        store.begin();
        if (best === 'all') ASPECTS.forEach((A) => write(A, 0)); else write(ASPECTS[best], 0);
        store.end();
        haptic(true);
        toast(best === 'all' ? 'Crystal: every aspect at the set' : `${ASPECTS[best].key}: the set`);
        lastTap = { k: null, t: -1e9 };
        drag = null;
        return;
      }
      lastTap = { k: best, t: now };
      const v0 = vals();
      drag = { k: best, v: best === 'all' ? v0 : v0[best], last: v0 };
      store.begin();
      note.textContent = best === 'all' ? 'All six at once: the joint climb. Up grows the crystal toward the references, down shrinks it to the set.' : ASPECTS[best].about;
    },
    move(p) {
      if (!drag || !p.moved || !geo) return;
      const span = geo.R - geo.r0;
      const dx = p.x - p.px, dy = p.y - p.py;
      if (drag.k === 'all') {
        const d = -dy / span;
        drag.v = drag.v.map((v) => clamp(v + d));
        ASPECTS.forEach((A, k) => write(A, drag.v[k]));
        detent(drag.last[0], drag.v[0]);
        drag.last = drag.v.slice();
      } else {
        const hd = geo.handles[drag.k];
        const ux = hd.dx, uy = hd.dy;
        const before = drag.v;
        drag.v = clamp(drag.v + (dx * ux + dy * uy) / span);
        write(ASPECTS[drag.k], drag.v);
        detent(before, drag.v);
      }
    },
    up() { if (drag) store.end(); drag = null; },
  });
  const detent = (a, b) => { for (const m0 of [0, 0.5, 1]) if ((a - m0) * (b - m0) < 0 || (a !== b && b === m0)) { haptic(m0 !== 0.5); return; } };

  // --- drawing ----------------------------------------------------------------------------------------------------
  m.draw = () => {
    const { g, w: W, h: H } = S.fit();
    const a = room.audio();
    const t = performance.now() / 1000;
    g.clearRect(0, 0, W, H);
    const bg = g.createRadialGradient(W / 2, H / 2, 10, W / 2, H / 2, Math.max(W, H) * 0.7);
    bg.addColorStop(0, '#1a0a1a'); bg.addColorStop(1, '#050406');
    g.fillStyle = bg; g.fillRect(0, 0, W, H);

    const cx = W / 2, cy = H / 2 + 6, R = Math.min(W, H) * 0.34, r0 = R * 0.36;
    const v = vals();
    const lv = ASPECTS.map((A) => read(A, (id) => store.live(id)));
    const mean = v.reduce((s, x) => s + x, 0) / v.length;
    const M = mul(rx(0.2 * Math.sin(t * 0.5) - 0.12), ry(0.24 * Math.sin(t * 0.37)));
    const cam = camera(cx, cy, 1, 1400);
    const at = (r, k, z = 0) => { const an = Math.PI / 2 - k * TAU / 6; return tf(M, [r * Math.cos(an), r * Math.sin(an), z]); };
    const P = (v3) => cam.p(v3);

    // guides: the set's ring (acid), the rim (the far end of the tried ranges), spokes
    const ring = (r, style, dash) => {
      g.beginPath();
      for (let k = 0; k <= 6; k++) { const q = P(at(r, k % 6)); k ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y); }
      g.setLineDash(dash); g.strokeStyle = style; g.lineWidth = 1.2; g.stroke(); g.setLineDash([]);
    };
    for (let k = 0; k < 6; k++) { const q0 = P(at(r0, k)), q1 = P(at(R, k)); g.strokeStyle = 'rgba(255,255,255,0.08)'; g.beginPath(); g.moveTo(q0.x, q0.y); g.lineTo(q1.x, q1.y); g.stroke(); }
    ring(R * 0.65, 'rgba(255,255,255,0.07)', [2, 5]);
    ring(R, 'rgba(233,231,226,0.35)', [5, 5]);
    ring(r0, rgba(C.acid, 0.7), [3, 4]);

    // the crystal: six top facets to a raised apex, six bottom ones seen through the glass
    const rad = v.map((x) => r0 + (R - r0) * x);
    const apexH = R * (0.42 + 0.35 * mean) * (1 + 0.12 * a.pulse);
    const verts = rad.map((r, k) => at(r, k));
    const top = tf(M, [0, 0, apexH]), bot = tf(M, [0, 0, -apexH * 0.7]);
    const L = norm([-0.45, 0.55, 0.75]);
    const facet = (apex, k, alpha, under) => {
      const p0 = verts[k], p1 = verts[(k + 1) % 6];
      let n = norm(cross(sub(p0, apex), sub(p1, apex)));
      if (n[2] < 0) n = n.map((x) => -x);
      const lit = 0.18 + 0.82 * Math.max(0, n[0] * L[0] + n[1] * L[1] + n[2] * L[2]);
      const glint = Math.pow(Math.max(0, n[0] * L[0] + n[1] * L[1] + n[2] * L[2]), 18);
      const A = P(apex), B = P(p0), Cq = P(p1);
      const gr = g.createLinearGradient(A.x, A.y, (B.x + Cq.x) / 2, (B.y + Cq.y) / 2);
      const hot = Math.round(255 * Math.min(1, lit * (1.05 + 0.35 * a.pulse)));
      gr.addColorStop(0, `rgba(${hot},${Math.round(hot * (0.55 + glint * 0.4))},${hot},${alpha})`);
      gr.addColorStop(1, `rgba(${Math.round(110 * lit)},${Math.round(14 * lit)},${Math.round(105 * lit)},${alpha * 0.9})`);
      g.beginPath(); g.moveTo(A.x, A.y); g.lineTo(B.x, B.y); g.lineTo(Cq.x, Cq.y); g.closePath();
      g.fillStyle = gr; g.fill();
      g.strokeStyle = under ? 'rgba(255,61,242,0.25)' : `rgba(255,${Math.round(180 + 60 * glint)},255,${0.35 + 0.4 * glint})`;
      g.lineWidth = 1; g.stroke();
    };
    g.save();
    g.shadowColor = rgba(C.magenta, 0.5); g.shadowBlur = 24 + 20 * a.pulse;
    for (let k = 0; k < 6; k++) facet(bot, k, 0.22, true);
    g.restore();
    const order = [0, 1, 2, 3, 4, 5].sort((i, j) => (verts[i][2] + verts[(i + 1) % 6][2]) - (verts[j][2] + verts[(j + 1) % 6][2]));
    for (const k of order) facet(top, k, 0.88, false);

    // what is heard, when other machines move these knobs
    if (lv.some((x, k) => Math.abs(x - v[k]) > 0.01)) {
      g.beginPath();
      lv.forEach((x, k) => { const q = P(at(r0 + (R - r0) * x, k)); k ? g.lineTo(q.x, q.y) : g.moveTo(q.x, q.y); });
      g.closePath(); g.strokeStyle = C.cold; g.lineWidth = 2; g.shadowColor = C.cold; g.shadowBlur = 8; g.stroke(); g.shadowBlur = 0;
    }

    // handles and labels
    const handles = [];
    ASPECTS.forEach((A, k) => {
      const q = P(verts[k]);
      const an = Math.PI / 2 - k * TAU / 6;
      const dx = Math.cos(an), dy = -Math.sin(an);
      handles.push({ x: q.x, y: q.y, dx, dy });
      const on = drag && (drag.k === k || drag.k === 'all');
      g.beginPath(); g.arc(q.x, q.y, on ? 14 : 11, 0, TAU);
      g.fillStyle = on ? C.magenta : '#1b0c1b'; g.fill();
      g.lineWidth = 2; g.strokeStyle = C.magenta; g.stroke();
      g.beginPath(); g.arc(q.x, q.y, 3.5, 0, TAU); g.fillStyle = on ? '#fff' : C.magenta; g.fill();
      const lq = P(at(R + 26, k));
      g.textAlign = 'center'; g.textBaseline = 'middle';
      g.font = `800 10.5px ${MONO}`; g.fillStyle = on ? C.magenta : C.text;
      g.fillText(A.key, lq.x, lq.y - 6);
      g.font = `600 10.5px ${MONO}`; g.fillStyle = v[k] < 0.005 ? C.acid : C.lcd;
      g.fillText(`${Math.round(v[k] * 100)}%`, lq.x, lq.y + 7);
    });
    // the heart
    const hq = P(top);
    g.beginPath(); g.arc(cx, cy, 16, 0, TAU);
    g.fillStyle = drag?.k === 'all' ? rgba(C.magenta, 0.5) : 'rgba(255,255,255,0.06)'; g.fill();
    g.strokeStyle = 'rgba(255,255,255,0.35)'; g.lineWidth = 1; g.stroke();
    g.font = `700 9px ${MONO}`; g.fillStyle = C.text2; g.textAlign = 'center';
    g.fillText(`${Math.round(mean * 100)}%`, cx, cy + 1);
    void hq;
    g.textAlign = 'left'; g.font = `600 9.5px ${MONO}`; g.textBaseline = 'alphabetic';
    g.fillStyle = rgba(C.acid, 0.7); g.fillText('INNER RING: THE SET', 10, 16);
    g.fillStyle = C.text3; g.fillText('RIM: FAR END TRIED', 10, 29);
    geo = { cx, cy, R, r0, handles };
  };
  return room.add(m);
}
