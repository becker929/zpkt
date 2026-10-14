// Loop: a gesture recorder on the bar clock. Drag the dot (X and Y are two knobs, as heard), press Rec: it waits
// for the next bar line, records 1, 2 or 4 bars of your finger, then plays the path back in a loop, locked to the
// bars, as automation (modulation: the knobs underneath stay where they were). Touch the pad while it loops to
// take over; let go and the loop carries on. Clear stops it. The loop is kept on this phone.

import { haptic, toast } from '../ui.js';
import { setNorm } from '../params.js';
import { C, btn, canvas2d, chips, clamp, load, pointers, rgba, save, segments, shell, shortOf, MONO } from './room.js';

const PER_BAR = 64;
const LENGTHS = [1, 2, 4];
const TAU = Math.PI * 2;

export function looper(room) {
  const { store, params } = room;
  const m = shell(room, {
    key: 'loop', title: 'Loop', sub: 'record a gesture, loop it on the bars', power: true,
    note: 'Drag the dot, press Rec, keep moving: it starts on the next bar and loops what you drew. Touch to take over; let go and the loop goes on.',
  });
  const picks = chips(room, m, [
    { role: 'X', hint: 'left and right', def: 'kick.colourFreq' },
    { role: 'Y', hint: 'up and down', def: 'kick.drive' },
  ]);
  m.el.insertBefore(picks.el, m.tools);
  m.output = room.out('loop');
  const S = canvas2d(room, m.view);

  const saved = load('loop.path', null);
  const st = {
    x: store.get(picks.ids[0]), y: store.get(picks.ids[1]),
    mode: saved ? 'play' : 'idle', bars: load('loop.bars', 2),
    loop: saved ? { bars: saved.bars, pts: Float32Array.from(saved.pts), start: saved.start ?? 0 } : null,
    rec: null, armBar: 0, touch: false, blink: 0,
  };
  let lenIdx = Math.max(0, LENGTHS.indexOf(st.bars));
  const lenSeg = segments(LENGTHS.map((n) => `${n} bar${n > 1 ? 's' : ''}`), lenIdx, (i) => { st.bars = LENGTHS[i]; save('loop.bars', st.bars); });
  const recBtn = btn('Rec', () => arm(), { cls: 'is-rec', pressed: false, label: 'Record a loop from the next bar' });
  const clearBtn = btn('Clear', () => {
    st.loop = null; st.rec = null; st.mode = 'idle'; save('loop.path', null);
    recBtn.setAttribute('aria-pressed', 'false');
    m.setOn(false);
    toast('Loop cleared: the knobs are back');
  });
  m.tools.append(lenSeg.el, recBtn, clearBtn);

  const arm = () => {
    if (st.mode === 'armed' || st.mode === 'rec') { st.mode = st.loop ? 'play' : 'idle'; st.rec = null; recBtn.setAttribute('aria-pressed', 'false'); return; }
    st.mode = 'armed';
    st.armBar = Math.floor(room.clock().t);
    recBtn.setAttribute('aria-pressed', 'true');
    if (!m.on) m.setOn(true);
    if (!room.clock().playing) toast('Rec: the transport is stopped, so it records on a silent clock');
  };

  pointers(S.cv, {
    down() { st.touch = true; if (!m.on) m.setOn(true); haptic(); },
    move(p) {
      if (!p.moved) return;
      const k = p.e?.altKey ? 0.25 : 1;
      st.x = clamp(st.x + (p.x - p.px) / S.w * k);
      st.y = clamp(st.y - (p.y - p.py) / S.h * k);
    },
    up(p, all) { if (!all.size) st.touch = false; },
  });
  room.own(picks.onChange(() => { st.x = store.get(picks.ids[0]); st.y = store.get(picks.ids[1]); }));

  const sample = (loop, f) => {               // f in 0..1 of the loop
    const n = loop.pts.length / 2, i = f * n, i0 = Math.floor(i) % n, i1 = (i0 + 1) % n, t = i - Math.floor(i);
    return [loop.pts[i0 * 2] * (1 - t) + loop.pts[i1 * 2] * t, loop.pts[i0 * 2 + 1] * (1 - t) + loop.pts[i1 * 2 + 1] * t];
  };

  m.sim = (dt) => {
    const c = room.clock();
    st.blink += dt;
    if (st.mode === 'armed' && Math.floor(c.t) > st.armBar) {
      st.mode = 'rec';
      st.rec = { bars: st.bars, start: Math.floor(c.t), pts: new Float32Array(st.bars * PER_BAR * 2).fill(-1), last: -1 };
      haptic(true);
    }
    if (st.mode === 'rec') {
      const r = st.rec, n = r.bars * PER_BAR;
      const f = (c.t - r.start) / r.bars;
      if (f >= 1) {
        for (let i = 0; i < n; i++) if (r.pts[i * 2] < 0) { const j = (i + n - 1) % n; r.pts[i * 2] = r.pts[j * 2] >= 0 ? r.pts[j * 2] : st.x; r.pts[i * 2 + 1] = r.pts[j * 2 + 1] >= 0 ? r.pts[j * 2 + 1] : st.y; }
        st.loop = { bars: r.bars, pts: r.pts, start: r.start };
        st.rec = null; st.mode = 'play';
        recBtn.setAttribute('aria-pressed', 'false');
        save('loop.path', { bars: st.loop.bars, start: st.loop.start % st.loop.bars, pts: Array.from(st.loop.pts, (v) => Math.round(v * 1000) / 1000) });
        haptic(true);
        toast(`Looping ${r.bars} bar${r.bars > 1 ? 's' : ''}`);
      } else {
        const i = Math.min(n - 1, Math.floor(f * n));
        for (let k = r.last + 1; k <= i; k++) { r.pts[k * 2] = st.x; r.pts[k * 2 + 1] = st.y; }
        r.last = Math.max(r.last, i);
      }
    } else if (st.mode === 'play' && st.loop && !st.touch && m.on) {
      const L = st.loop;
      const f = ((((c.t - L.start) % L.bars) + L.bars) % L.bars) / L.bars;
      [st.x, st.y] = sample(L, f);
    }
    if (m.on) {
      const [X, Y] = picks.ids;
      m.output.frame([[X, st.x - store.get(X)], [Y, st.y - store.get(Y)]]);
    } else if (!st.touch) {
      st.x += (store.get(picks.ids[0]) - st.x) * Math.min(1, dt * 8);
      st.y += (store.get(picks.ids[1]) - st.y) * Math.min(1, dt * 8);
    }
  };

  m.draw = () => {
    const { g, w: W, h: H } = S.fit();
    const c = room.clock(), a = room.audio();
    const [X, Y] = picks.ids;
    const px = (v) => v * W, py = (v) => H - v * H;
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#060608'; g.fillRect(0, 0, W, H);
    g.strokeStyle = 'rgba(255,255,255,0.05)'; g.lineWidth = 1;
    for (let i = 1; i < 8; i++) { g.beginPath(); g.moveTo(W * i / 8, 0); g.lineTo(W * i / 8, H); g.moveTo(0, H * i / 8); g.lineTo(W, H * i / 8); g.stroke(); }
    // the set's values and the knobs underneath
    const sx = px(setNorm(params.get(X))), sy = py(setNorm(params.get(Y)));
    g.setLineDash([3, 5]); g.strokeStyle = rgba(C.acid, 0.5);
    g.beginPath(); g.moveTo(sx, 0); g.lineTo(sx, H); g.moveTo(0, sy); g.lineTo(W, sy); g.stroke(); g.setLineDash([]);
    const kx = px(store.get(X)), ky = py(store.get(Y));
    g.strokeStyle = 'rgba(233,231,226,0.5)'; g.strokeRect(kx - 6, ky - 6, 12, 12);
    // the loop's path and its playhead
    const path = st.rec ? st.rec : st.loop;
    if (path) {
      const n = path.pts.length / 2;
      g.beginPath();
      let started = false;
      for (let i = 0; i < n; i++) {
        const x = path.pts[i * 2], y = path.pts[i * 2 + 1];
        if (x < 0) { started = false; continue; }
        if (!started) { g.moveTo(px(x), py(y)); started = true; } else g.lineTo(px(x), py(y));
      }
      if (!st.rec) g.closePath();
      g.strokeStyle = st.rec ? C.alarm : rgba(C.magenta, 0.85); g.lineWidth = 2.5;
      g.shadowColor = st.rec ? C.alarm : C.magenta; g.shadowBlur = 10; g.stroke(); g.shadowBlur = 0;
      // bar ticks along the path
      if (!st.rec) for (let b = 0; b < path.bars; b++) {
        const i = b * PER_BAR, x = px(path.pts[i * 2]), y = py(path.pts[i * 2 + 1]);
        g.fillStyle = C.lcd; g.beginPath(); g.arc(x, y, 3.5, 0, TAU); g.fill();
        g.font = `700 9px ${MONO}`; g.fillText(`${b + 1}`, x + 6, y - 6);
      }
    }
    // the dot
    const dx = px(st.x), dy = py(st.y);
    g.strokeStyle = rgba(m.on ? C.cold : C.text3, 0.35); g.lineWidth = 1;
    g.beginPath(); g.moveTo(dx, 0); g.lineTo(dx, H); g.moveTo(0, dy); g.lineTo(W, dy); g.stroke();
    const r = 15 + 5 * a.pulse;
    const gr = g.createRadialGradient(dx - 4, dy - 5, 1, dx, dy, r);
    gr.addColorStop(0, '#fff'); gr.addColorStop(0.4, m.on ? C.cold : C.steel4); gr.addColorStop(1, rgba(m.on ? C.cold : C.steel4, 0.1));
    g.shadowColor = C.cold; g.shadowBlur = m.on ? 16 : 0;
    g.fillStyle = gr; g.beginPath(); g.arc(dx, dy, r, 0, TAU); g.fill(); g.shadowBlur = 0;
    // axis names
    g.font = `700 10px ${MONO}`; g.fillStyle = C.text2;
    g.textAlign = 'right'; g.fillText(`${shortOf(params.get(X)).toUpperCase()} >`, W - 10, H - 10);
    g.save(); g.translate(14, 34); g.rotate(Math.PI / 2); g.textAlign = 'left'; g.fillText(`< ${shortOf(params.get(Y)).toUpperCase()}`, 0, 0); g.restore();
    // the bar clock: one segment per bar of the loop (or of the length chosen)
    const bars = st.rec?.bars ?? st.loop?.bars ?? st.bars;
    const start = st.rec?.start ?? st.loop?.start ?? 0;
    const f = ((((c.t - start) % bars) + bars) % bars) / bars;
    const ox = W - 30, oy = 30;
    for (let b = 0; b < bars; b++) {
      const a0 = -Math.PI / 2 + (b / bars) * TAU + 0.06, a1 = -Math.PI / 2 + ((b + 1) / bars) * TAU - 0.06;
      g.beginPath(); g.arc(ox, oy, 17, a0, a1); g.strokeStyle = 'rgba(255,255,255,0.12)'; g.lineWidth = 5; g.stroke();
    }
    if (st.mode === 'rec' || st.mode === 'play') {
      g.beginPath(); g.arc(ox, oy, 17, -Math.PI / 2, -Math.PI / 2 + f * TAU);
      g.strokeStyle = st.mode === 'rec' ? C.alarm : C.magenta; g.lineWidth = 5; g.stroke();
    }
    g.textAlign = 'center'; g.font = `700 9px ${MONO}`; g.fillStyle = C.text2; g.fillText(String(bars), ox, oy + 3);
    g.textAlign = 'left'; g.font = `700 10px ${MONO}`;
    const blink = Math.floor(st.blink * 4) % 2;
    const label = st.mode === 'armed' ? (blink ? `ARMED: BAR ${st.armBar + 2}` : '') : st.mode === 'rec' ? `REC ${Math.floor(f * bars) + 1}/${bars}` : st.mode === 'play' ? (m.on ? (st.touch ? 'YOU HAVE IT' : `LOOP ${bars} BAR${bars > 1 ? 'S' : ''}`) : 'LOOP: TURN ON TO HEAR') : (m.on ? 'LIVE: PRESS REC' : 'DRAG THE DOT');
    g.fillStyle = st.mode === 'rec' || st.mode === 'armed' ? C.alarm : m.on ? C.cold : C.text3;
    g.fillText(label, 10, 18);
  };
  return room.add(m);
}
