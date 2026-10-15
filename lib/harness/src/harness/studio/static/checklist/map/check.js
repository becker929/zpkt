// The check, written into the ledger. Slow and heavy on purpose: the box lifts out of its row and comes to the middle
// of the screen, big; a ghost check hangs over it, then slams down; on contact everything freezes for a beat (hit
// stop), then the box fills, the screen shakes, white comes out from under the box, sparks, chips and dust burst
// and fall, and an impact mark stays where it landed. Nothing springs back: eases end flat, never past the mark.
// Then the shell hands the big box to the map (the box becomes its room). `landInRow` is the end: the box drops back
// into its row, pressed in, with a puff of dust.

const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
export const HEAVY = 'cubic-bezier(.3,.7,.1,1)';        // decelerates hard, never overshoots
const SLAM = 'cubic-bezier(.75,0,1,.55)';               // accelerates into the contact

const CHECK_SVG = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M4.5 12.5l5 5L19.5 7"/></svg>';
export const BIG = 112;                                 // the box at the middle of the screen, px

// --- particles: one canvas over everything, run only while something is alive ---
let cv, cx2, parts = [], running = false, dpr = 1;

export function particlesOn(canvas) {
  cv = canvas; cx2 = cv.getContext('2d');
  const size = () => {
    dpr = Math.min(2, devicePixelRatio || 1);           // sparks and dust don't need 3x: a third of the pixels to clear
    cv.width = innerWidth * dpr; cv.height = innerHeight * dpr;
    cv.style.width = `${innerWidth}px`; cv.style.height = `${innerHeight}px`;
  };
  size(); addEventListener('resize', size);
}

function spawn(p) { parts.push(p); if (!running) { running = true; requestAnimationFrame(tick); } }
let last = 0;
function tick(now) {
  const dt = Math.min(0.033, last ? (now - last) / 1000 : 0.016);
  last = now;
  cx2.setTransform(dpr, 0, 0, dpr, 0, 0);
  cx2.clearRect(0, 0, innerWidth, innerHeight);
  parts = parts.filter((p) => (p.age += dt) < p.life);
  for (const p of parts) {
    p.vx *= Math.pow(p.drag, dt * 60); p.vy = p.vy * Math.pow(p.drag, dt * 60) + p.g * dt;
    p.x += p.vx * dt; p.y += p.vy * dt; p.rot += p.spin * dt;
    if (p.floor != null && p.y > p.floor) { p.y = p.floor; p.vy *= -0.25; p.vx *= 0.5; p.spin *= 0.5; }   // dust settles
    const k = p.age / p.life, a = p.alpha * (k < 0.7 ? 1 : 1 - (k - 0.7) / 0.3);
    cx2.globalAlpha = Math.max(0, a);
    if (p.kind === 'spark') {
      cx2.strokeStyle = p.color; cx2.lineWidth = p.size; cx2.lineCap = 'round';
      const sp = Math.hypot(p.vx, p.vy) || 1, len = Math.min(26, sp * 0.03);
      cx2.beginPath(); cx2.moveTo(p.x, p.y); cx2.lineTo(p.x - (p.vx / sp) * len, p.y - (p.vy / sp) * len); cx2.stroke();
    } else if (p.kind === 'chip') {
      cx2.save(); cx2.translate(p.x, p.y); cx2.rotate(p.rot); cx2.fillStyle = p.color;
      cx2.fillRect(-p.size / 2, -p.size / 2, p.size, p.size * 0.6); cx2.restore();
    } else {
      cx2.fillStyle = p.color; cx2.beginPath(); cx2.arc(p.x, p.y, p.size * (1 + k * 1.5), 0, Math.PI * 2); cx2.fill();
    }
  }
  cx2.globalAlpha = 1;
  if (parts.length) requestAnimationFrame(tick);
  else { running = false; last = 0; cx2.clearRect(0, 0, innerWidth, innerHeight); }
}

const R = (a, b) => a + Math.random() * (b - a);
/** A burst at (x, y) from a box `s` px wide. `power` 1 is a check, 1.6 a check that finishes a step. */
export function burst(x, y, s, { power = 1, ink = '#fff', accent = '#f1b64a', floor = null } = {}) {
  const n = Math.round(46 * power);
  for (let i = 0; i < n; i++) {                                   // sparks off the edges, fast
    const a = R(0, Math.PI * 2), v = R(380, 980) * power;
    spawn({ kind: 'spark', x: x + Math.cos(a) * s * 0.45, y: y + Math.sin(a) * s * 0.45, vx: Math.cos(a) * v, vy: Math.sin(a) * v,
      g: 900, drag: 0.9, life: R(0.35, 0.8), age: 0, size: R(1.2, 2.6), color: Math.random() < 0.3 ? accent : ink, alpha: 1, rot: 0, spin: 0 });
  }
  for (let i = 0; i < Math.round(22 * power); i++) {             // chips: heavier, tumble and fall
    const a = R(-Math.PI * 0.95, -Math.PI * 0.05), v = R(220, 620);
    spawn({ kind: 'chip', x: x + R(-s / 2, s / 2), y: y + R(-s / 3, s / 3), vx: Math.cos(a) * v, vy: Math.sin(a) * v,
      g: 1700, drag: 0.985, life: R(1.1, 1.9), age: 0, size: R(3, 7), color: ink, alpha: 0.95, rot: R(0, 6), spin: R(-14, 14), floor });
  }
  for (let i = 0; i < Math.round(26 * power); i++) {             // dust: slow, spreads along the ground, settles
    const a = R(0, Math.PI * 2), v = R(30, 150);
    spawn({ kind: 'dust', x: x + R(-s / 2, s / 2), y: y + s / 2 + R(-6, 4), vx: Math.cos(a) * v * 1.8, vy: Math.sin(a) * v * 0.4 - 30,
      g: 60, drag: 0.94, life: R(1.4, 2.4), age: 0, size: R(1.5, 4), color: ink, alpha: 0.22, rot: 0, spin: 0 });
  }
}

function el(cls, html = '') { const d = document.createElement('div'); d.className = cls; d.innerHTML = html; return d; }

/** The transform that puts an element of size `s` centred at (cx, cy) over `rect`. */
const over = (rect, cx, cy, s) => `translate(${rect.left + rect.width / 2 - cx}px, ${rect.top + rect.height / 2 - cy}px) scale(${rect.width / s})`;

/**
 * The check at the middle of the screen. `box` is the row's box (hidden while its big double is out), `at` the
 * screen point to bring it to (the splash stage's centre), `fx` the layer to draw in, `shakeEl` what shakes.
 * `onContact()` plays the sound and haptic at the moment of contact. Resolves with the big box (still on screen,
 * for the shell to hand to the map) once the dust is falling.
 */
export async function stamp({ box, at, fx, shakeEl, finishes = false, onContact = () => {}, onLift = () => {} }) {
  const r0 = box.getBoundingClientRect();
  const [cx, cy] = at;
  const big = el('bigbox', CHECK_SVG);
  Object.assign(big.style, { left: `${cx - BIG / 2}px`, top: `${cy - BIG / 2}px`, width: `${BIG}px`, height: `${BIG}px` });
  fx.append(big);
  box.style.visibility = 'hidden';
  onLift();
  // 1. lift: out of the row, up to the middle, big
  await big.animate([
    { transform: over(r0, cx, cy, BIG), boxShadow: '0 0 0 rgb(0 0 0 / 0)' },
    { transform: 'translate(0, -6px) scale(1.04)', boxShadow: '0 30px 60px rgb(0 0 0 / 0.55)', offset: 0.8 },
    { transform: 'none', boxShadow: '0 22px 50px rgb(0 0 0 / 0.5)' },
  ], { duration: 620, easing: HEAVY, fill: 'forwards' }).finished;
  // 2. the ghost check hangs over it, huge and faint, and the box braces
  const ghost = el('ghost-check', CHECK_SVG);
  Object.assign(ghost.style, { left: `${cx - BIG / 2}px`, top: `${cy - BIG / 2}px`, width: `${BIG}px`, height: `${BIG}px` });
  fx.append(ghost);
  big.animate([{ transform: 'none' }, { transform: 'scale(.95)' }], { duration: 420, easing: HEAVY, fill: 'forwards' });
  await ghost.animate([
    { transform: 'scale(5.2) rotate(-14deg)', opacity: 0 },
    { transform: 'scale(3.4) rotate(-9deg)', opacity: 0.4 },
  ], { duration: 420, easing: HEAVY, fill: 'forwards' }).finished;
  await sleep(90);
  // 3. the slam
  await ghost.animate([
    { transform: 'scale(3.4) rotate(-9deg)', opacity: 0.4 },
    { transform: 'scale(1) rotate(0deg)', opacity: 1 },
  ], { duration: 210, easing: SLAM, fill: 'forwards' }).finished;
  // 4. contact: filled at once, the sound, then everything holds still for a beat (hit stop)
  ghost.remove();
  big.getAnimations().forEach((a) => a.cancel());
  big.classList.add('filled');
  big.style.transform = 'scale(.9)';
  big.style.boxShadow = '0 6px 14px rgb(0 0 0 / 0.5)';
  onContact();
  const sil = el('silhouette-big');
  Object.assign(sil.style, { left: `${cx - BIG / 2}px`, top: `${cy - BIG / 2}px`, width: `${BIG}px`, height: `${BIG}px` });
  fx.insertBefore(sil, big);
  await sleep(85);
  // 5. release: the burst, the shake, white from under the box, rings, an impact mark that stays
  burst(cx, cy, BIG, { power: finishes ? 1.6 : 1, floor: cy + BIG / 2 + 70 });
  shake(shakeEl, finishes ? 18 : 13, finishes ? 560 : 440);
  sil.animate([
    { transform: 'scale(1)', opacity: 1 },
    { transform: `scale(${finishes ? 3.4 : 2.7})`, opacity: 0 },
  ], { duration: 620, easing: HEAVY, fill: 'forwards' }).finished.then(() => sil.remove());
  for (let i = 0; i < (finishes ? 4 : 3); i++) {
    const ring = el('ring-big');
    Object.assign(ring.style, { left: `${cx - BIG / 2}px`, top: `${cy - BIG / 2}px`, width: `${BIG}px`, height: `${BIG}px` });
    fx.append(ring);
    ring.animate([
      { transform: 'scale(.9)', opacity: 0.9 },
      { transform: `scale(${2.2 + i * 0.9})`, opacity: 0 },
    ], { duration: 700 + i * 140, delay: i * 90, easing: HEAVY, fill: 'forwards' }).finished.then(() => ring.remove());
  }
  const mark = el('impact');
  Object.assign(mark.style, { left: `${cx - BIG / 2}px`, top: `${cy - BIG / 2}px`, width: `${BIG}px`, height: `${BIG}px` });
  fx.insertBefore(mark, big);
  mark.animate([{ transform: 'scale(1)', opacity: 0.9 }, { transform: 'scale(1.22)', opacity: 0.35 }],
    { duration: 520, easing: HEAVY, fill: 'forwards' });
  await big.animate([
    { transform: 'scale(.9)', boxShadow: '0 6px 14px rgb(0 0 0 / 0.5)' },
    { transform: 'scale(1)', boxShadow: '0 3px 0 rgb(0 0 0 / 0.6)' },
  ], { duration: 520, easing: HEAVY, fill: 'forwards' }).finished;
  return { big, mark };
}

/** The screen shakes: a jolt that decays, mostly vertical (the weight came down). */
export function shake(target, px, ms) {
  const k = [];
  const n = 12;
  for (let i = 0; i <= n; i++) {
    const a = px * Math.pow(1 - i / n, 1.6);
    k.push({ transform: `translate(${(i % 2 ? -0.55 : 0.55) * a * (i % 3 ? 1 : 0.4)}px, ${(i % 2 ? 1 : -1) * a}px)` });
  }
  return target.animate(k, { duration: ms, easing: 'linear' });
}

/** The end: the box drops back into its row, pressed in, a puff of dust, and the row's stamp writes in. */
export async function landInRow(box, { ink, onLand = () => {} } = {}) {
  box.style.visibility = '';
  const r = box.getBoundingClientRect();
  await box.animate([
    { transform: 'translateY(-26px) scale(1.5)', opacity: 0 },
    { transform: 'translateY(-14px) scale(1.35)', opacity: 1, offset: 0.4 },
    { transform: 'none', opacity: 1 },
  ], { duration: 360, easing: SLAM }).finished;
  onLand();
  burst(r.left + r.width / 2, r.top + r.height / 2, r.width, { power: 0.18, ink, accent: ink, floor: r.bottom + 4 });
  await box.animate([{ transform: 'scale(.9)' }, { transform: 'none' }], { duration: 260, easing: HEAVY }).finished;
}
