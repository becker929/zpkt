// Tilt: the phone as a spirit level. The bubble is the cursor: it floats to the high side, and its place moves knobs
// (modulation on top of the knob: let go of the tilt and the knob is where it was). Right raises X, up raises Y,
// and how far the bubble is off centre raises the third (lean). 35 degrees of tilt is the whole depth.
//
// On: asks the iPhone for the motion sensor (it asks once, on that tap), and levels at the angle you hold it then.
// Hold: freezes the bubble where it is while your thumb is down. Level here: the angle you hold now is the centre.
// No sensor (a desktop, permission refused): drag the bubble with a finger; it drifts back when you let go.
// The Kick box machine rolls its balls with this tilt while Tilt is on.

import { h, haptic, toast } from '../ui.js';
import { C, btn, canvas2d, chips, clamp, pointers, rgba, shell, MONO } from './room.js';

const SPAN = 35;          // degrees for the whole depth
const TAU = Math.PI * 2;

export function tilt(room) {
  const m = shell(room, {
    key: 'tilt', title: 'Tilt', sub: 'a spirit level on three knobs', power: true,
    note: 'Tap Off to turn it on (the phone asks for its motion sensor) and tilt: the bubble floats to the high side and moves the knobs. Hold freezes it. Without the sensor, drag the bubble.',
  });
  const picks = chips(room, m, [
    { role: 'X', hint: 'bubble right', def: 'kick.colourFreq' },
    { role: 'Y', hint: 'bubble up', def: 'kick.colour' },
    { role: 'Lean', hint: 'bubble off centre', def: 'mix.spaceMix' },
  ]);
  m.el.insertBefore(picks.el, m.tools);
  m.output = room.out('tilt');
  const S = canvas2d(room, m.view);

  const st = { x: 0, y: 0, tx: 0, ty: 0, vx: 0, vy: 0, zero: null, raw: null, frozen: false, touch: false, sensor: 'off', trail: [] };
  let gotEvent = false, waitTimer = 0;

  const onOrient = (e) => {
    if (e.beta == null || e.gamma == null) return;
    gotEvent = true;
    st.sensor = 'on';
    st.raw = { b: e.beta, g: e.gamma };
    if (!st.zero) st.zero = { ...st.raw };
  };
  const listen = (on) => {
    if (on) window.addEventListener('deviceorientation', onOrient);
    else window.removeEventListener('deviceorientation', onOrient);
  };
  room.own(() => { listen(false); clearTimeout(waitTimer); });

  m.onPower = (on, user) => {
    if (!on) { listen(false); st.sensor = 'off'; st.zero = null; room.sensors.tilt = null; return; }
    gotEvent = false;
    st.zero = null;
    const start = () => {
      listen(true);
      st.sensor = 'waiting';
      clearTimeout(waitTimer);
      waitTimer = setTimeout(() => {
        if (gotEvent || !m.on) return;
        st.sensor = 'none';
        if (user) toast('No tilt sensor here: drag the bubble');
      }, 1200);
    };
    const DOE = window.DeviceOrientationEvent;
    if (user && DOE && typeof DOE.requestPermission === 'function') {
      DOE.requestPermission().then((r) => {
        if (r === 'granted') start();
        else { st.sensor = 'denied'; toast('Motion access refused: drag the bubble (Settings > Safari to allow it)'); }
      }).catch(() => { st.sensor = 'none'; });
    } else if (DOE) start();
    else st.sensor = 'none';
  };

  const hold = h('button', { type: 'button', class: 'pl-btn is-hold', 'aria-label': 'Hold to freeze the tilt' }, 'Hold');
  const press = (on) => { st.frozen = on; hold.classList.toggle('is-down', on); if (on) haptic(true); };
  hold.addEventListener('pointerdown', (e) => { try { hold.setPointerCapture(e.pointerId); } catch { /* synthetic */ } press(true); });
  for (const ev of ['pointerup', 'pointercancel', 'lostpointercapture']) hold.addEventListener(ev, () => { if (st.frozen) press(false); });
  hold.addEventListener('contextmenu', (e) => e.preventDefault());
  m.tools.append(room.knob('play.tiltDepth', { size: 64, label: 'Depth' }), hold,
    btn('Level here', () => { if (st.raw) { st.zero = { ...st.raw }; toast('Level: this angle is the centre'); } else { st.tx = 0; st.ty = 0; } }));

  // a finger moves the bubble (the fallback, and a way to nudge it with the sensor on)
  pointers(S.cv, {
    down() { st.touch = true; if (!m.on) m.setOn(true); },
    move(p) {
      if (!p.moved) return;
      const R = Math.min(S.w, S.h) * 0.4;
      st.tx = clamp(st.tx + (p.x - p.px) / R, -1, 1);
      st.ty = clamp(st.ty - (p.y - p.py) / R, -1, 1);
    },
    up(p, all) { if (!all.size) st.touch = false; },
  });

  let lastRing = 0;
  m.sim = (dt) => {
    if (!m.on) { st.tx = 0; st.ty = 0; }
    else if (!st.frozen && !st.touch) {
      if (st.sensor === 'on' && st.raw && st.zero) {
        let db = st.raw.b - st.zero.b, dg = st.raw.g - st.zero.g;
        if (db > 180) db -= 360; if (db < -180) db += 360;
        st.tx = clamp(-dg / SPAN, -1, 1);
        st.ty = clamp(db / SPAN, -1, 1);
      } else {
        st.tx *= Math.exp(-dt * 1.5); st.ty *= Math.exp(-dt * 1.5);
      }
    }
    if (!st.frozen) {
      const k = 1 - Math.exp(-dt * 10);
      st.vx = (st.tx - st.x) * k / Math.max(dt, 1e-3); st.vy = (st.ty - st.y) * k / Math.max(dt, 1e-3);
      st.x += (st.tx - st.x) * k; st.y += (st.ty - st.y) * k;
    } else { st.vx = 0; st.vy = 0; }
    const lean = Math.min(1, Math.hypot(st.x, st.y));
    const ring = Math.floor(lean * 3.0001);
    if (ring !== lastRing) { if (m.on && room.ratio(m) > 0) haptic(); lastRing = ring; }
    room.sensors.tilt = m.on ? { x: st.x, y: st.y } : null;
    if (m.on) {
      const depth = room.real('play.tiltDepth', 35) / 100;
      const [X, Y, Lz] = picks.ids;
      m.output.frame([[X, st.x * depth], [Y, st.y * depth], [Lz, lean * depth]]);
    }
  };

  m.draw = () => {
    const { g, w: W, h: H } = S.fit();
    const a = room.audio();
    g.clearRect(0, 0, W, H);
    g.fillStyle = '#060607'; g.fillRect(0, 0, W, H);
    const cx = W / 2, cy = H / 2, R = Math.min(W, H) * 0.42;
    // the bezel
    const bez = g.createRadialGradient(cx - R * 0.3, cy - R * 0.4, R * 0.2, cx, cy, R * 1.12);
    bez.addColorStop(0, '#4a4f58'); bez.addColorStop(0.7, '#1e2126'); bez.addColorStop(1, '#0b0c0e');
    g.beginPath(); g.arc(cx, cy, R * 1.1, 0, TAU); g.fillStyle = bez; g.fill();
    for (let i = 0; i < 72; i++) {
      const an = i / 72 * TAU, r1 = R * 1.09, r2 = i % 6 ? R * 1.04 : R * 1.0;
      g.strokeStyle = i % 6 ? 'rgba(255,255,255,0.12)' : 'rgba(255,255,255,0.35)'; g.lineWidth = 1;
      g.beginPath(); g.moveTo(cx + Math.cos(an) * r1, cy + Math.sin(an) * r1); g.lineTo(cx + Math.cos(an) * r2, cy + Math.sin(an) * r2); g.stroke();
    }
    // the vial
    const liq = g.createRadialGradient(cx, cy - R * 0.2, R * 0.1, cx, cy, R);
    liq.addColorStop(0, m.on ? 'rgba(198,255,61,0.2)' : 'rgba(198,255,61,0.07)');
    liq.addColorStop(1, 'rgba(10,20,4,0.95)');
    g.beginPath(); g.arc(cx, cy, R * 0.98, 0, TAU); g.fillStyle = liq; g.fill();
    g.strokeStyle = 'rgba(0,0,0,0.9)'; g.lineWidth = 3; g.stroke();
    // rings at 12, 23, 35 degrees and the cross
    g.font = `600 9px ${MONO}`; g.textAlign = 'left'; g.textBaseline = 'middle';
    [1, 2, 3].forEach((k) => {
      g.beginPath(); g.arc(cx, cy, R * 0.82 * k / 3, 0, TAU);
      g.strokeStyle = k === 3 ? 'rgba(198,255,61,0.45)' : 'rgba(198,255,61,0.22)'; g.lineWidth = 1; g.stroke();
      g.fillStyle = 'rgba(198,255,61,0.5)'; g.fillText(`${Math.round(SPAN * k / 3)}°`, cx + 4, cy - R * 0.82 * k / 3 + 8);
    });
    g.strokeStyle = 'rgba(198,255,61,0.25)';
    g.beginPath(); g.moveTo(cx - R * 0.95, cy); g.lineTo(cx + R * 0.95, cy); g.moveTo(cx, cy - R * 0.95); g.lineTo(cx, cy + R * 0.95); g.stroke();
    g.beginPath(); g.arc(cx, cy, 24, 0, TAU); g.strokeStyle = 'rgba(233,231,226,0.5)'; g.lineWidth = 1.5; g.stroke();
    // trail and bubble
    const bx = cx + st.x * R * 0.82, by = cy - st.y * R * 0.82;
    st.trail.push([bx, by]); if (st.trail.length > 26) st.trail.shift();
    st.trail.forEach(([x, y], i) => { g.fillStyle = rgba(C.cold, 0.012 * i); g.beginPath(); g.arc(x, y, 16, 0, TAU); g.fill(); });
    const sp = Math.min(0.35, Math.hypot(st.vx, st.vy) * 0.08);
    const an = Math.atan2(-st.vy, st.vx);
    g.save();
    g.translate(bx, by); g.rotate(an); g.scale(1 + sp, 1 - sp * 0.6);
    const br = 21 * (1 + 0.08 * a.pulse);
    const bub = g.createRadialGradient(-br * 0.35, -br * 0.4, 1, 0, 0, br);
    bub.addColorStop(0, '#ffffff'); bub.addColorStop(0.35, st.frozen ? C.acid : C.cold); bub.addColorStop(1, rgba(st.frozen ? C.acid : C.cold, 0.15));
    g.shadowColor = st.frozen ? C.acid : C.cold; g.shadowBlur = 18;
    g.beginPath(); g.arc(0, 0, br, 0, TAU); g.fillStyle = bub; g.fill();
    g.restore();
    if (st.frozen) { g.beginPath(); g.arc(bx, by, 30, 0, TAU); g.strokeStyle = C.acid; g.setLineDash([3, 4]); g.lineWidth = 1.5; g.stroke(); g.setLineDash([]); }
    // glass
    const gl = g.createLinearGradient(cx - R, cy - R, cx + R * 0.2, cy + R * 0.2);
    gl.addColorStop(0, 'rgba(255,255,255,0.14)'); gl.addColorStop(0.5, 'rgba(255,255,255,0)');
    g.beginPath(); g.arc(cx, cy, R * 0.97, Math.PI * 0.95, Math.PI * 1.7); g.lineWidth = R * 0.08; g.strokeStyle = gl; g.stroke();
    // readouts
    const deg = (v) => `${v >= 0 ? '+' : ''}${Math.round(v * SPAN)}°`;
    g.textBaseline = 'alphabetic'; g.font = `700 10px ${MONO}`;
    g.fillStyle = C.text3; g.textAlign = 'left'; g.fillText('X', 12, 18); g.textAlign = 'right'; g.fillText('Y', W - 12, 18);
    g.font = `600 13px ${MONO}`; g.fillStyle = m.on ? C.cold : C.text3;
    g.textAlign = 'left'; g.fillText(deg(st.x), 12, 34); g.textAlign = 'right'; g.fillText(deg(st.y), W - 12, 34);
    g.textAlign = 'center'; g.font = `700 10px ${MONO}`;
    const status = st.frozen ? 'HELD' : !m.on ? 'OFF: TAP ON, OR DRAG THE BUBBLE' : { on: 'TILT', waiting: 'WAITING FOR THE SENSOR', none: 'NO SENSOR: DRAG THE BUBBLE', denied: 'NO ACCESS: DRAG THE BUBBLE', off: '' }[st.sensor] ?? '';
    g.fillStyle = st.frozen ? C.acid : C.text2;
    g.fillText(status, cx, H - 10);
  };
  return room.add(m);
}
