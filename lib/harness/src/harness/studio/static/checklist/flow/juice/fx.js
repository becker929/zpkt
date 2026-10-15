// What the juice objects share: tweens on the animation frame (they always finish, even when frames stop coming),
// easings, SVG elements, and the keys of the done set. No sound here: the shell plays the click.

export const NS = 'http://www.w3.org/2000/svg';
export const ease = {
  out: (t) => 1 - (1 - t) ** 3,
  inOut: (t) => (t < 0.5 ? 4 * t * t * t : 1 - (-2 * t + 2) ** 3 / 2),
  back: (t) => { const c = 1.9; return 1 + (c + 1) * (t - 1) ** 3 + c * (t - 1) ** 2; },
  linear: (t) => t,
};
export const lerp = (a, b, t) => a + (b - a) * t;
export const bump = (t) => Math.sin(Math.PI * Math.min(1, Math.max(0, t)));    // 0 → 1 → 0

/** Call fn(eased, raw) every frame for `ms` after `delay`, ending exactly on fn(1, 1). */
export function tween(ms, fn, { delay = 0, easing = ease.out } = {}) {
  return new Promise((done) => {
    let start = null, over = false;
    const finish = () => { if (over) return; over = true; fn(easing(1), 1); done(); };
    const frame = (now) => {
      if (over) return;
      if (start === null) start = now + delay;
      if (now >= start) {
        const t = Math.min(1, (now - start) / ms);
        if (t >= 1) return finish();
        fn(easing(t), t);
      }
      requestAnimationFrame(frame);
    };
    requestAnimationFrame(frame);
    setTimeout(finish, delay + ms + 250);          // frames can stop (a hidden tab); the motion still ends
  });
}
export const wait = (ms) => new Promise((ok) => setTimeout(ok, ms));

export function el(tag, attrs = {}, parent = null) {
  const e = document.createElementNS(NS, tag);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, String(v));
  if (parent) parent.append(e);
  return e;
}

/** The keys of the step and item the shell passes (objects or ids). */
export function keyFor(step, item) {
  const s = typeof step === 'string' ? step : step.id;
  const i = typeof item === 'string' ? item : item.id;
  return [s, i, `${s}.${i}`];
}
export const asSet = (keys) => (keys instanceof Set ? keys : new Set(keys));
export const f = (x) => (Math.round(x * 10) / 10).toString();

/** Reduced motion: the AFTER state with a fade, nothing else. */
export async function fadeIn(stage, markup) {
  stage.innerHTML = markup;
  const inner = stage.firstElementChild;
  if (!inner) return;
  await tween(220, (e) => { inner.style.opacity = String(e); });
  stage.innerHTML = markup;           // a fresh element: WebKit leaves style="" behind a removed inline style
}
