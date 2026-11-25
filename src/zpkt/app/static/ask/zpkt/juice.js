// Game juice: small motion that says "something happened". Purely visual, never sound (sound rule).
// Motion never touches opacity: if an animation stalls (a background tab), nothing is left invisible.
// Everything here does nothing while a session is being replayed or when the viewer asked for reduced motion.
let quiet = false;
const still = () => quiet || matchMedia('(prefers-reduced-motion: reduce)').matches || document.hidden;

/** Turn effects off (replay) or on. */
export function setQuiet(q) { quiet = !!q; }

/** A quick squash-and-stretch on an element. */
export function bump(el, scale = 1.12) {
  if (!el || still() || !el.animate) return;
  el.animate([{ transform: 'scale(1)' }, { transform: `scale(${scale})` }, { transform: 'scale(.97)' }, { transform: 'scale(1)' }], { duration: 320, easing: 'cubic-bezier(.3,1.6,.5,1)' });
}

/** New thing arriving: slides up into place. */
export function enter(el) {
  if (!el || still() || !el.animate) return;
  el.animate([{ transform: 'translateY(8px)' }, { transform: 'none' }], { duration: 180, easing: 'ease-out' });
}

/** A burst of square confetti in the palette, from an element's centre. */
export function burst(el, n = 14) {
  if (!el || still() || !document.body.animate) return;
  const r = el.getBoundingClientRect();
  if (!r.width) return;
  const x = r.left + r.width / 2, y = r.top + r.height / 2;
  const colors = ['#c6f432', '#111', '#fff', '#c6f432'];
  for (let i = 0; i < n; i++) {
    const p = document.createElement('i');
    const size = 5 + Math.random() * 6;
    p.style.cssText = `position:fixed;left:${x}px;top:${y}px;width:${size}px;height:${size}px;background:${colors[i % colors.length]};outline:1px solid #111;pointer-events:none;z-index:50`;
    document.body.append(p);
    const a = Math.random() * Math.PI * 2, d = 40 + Math.random() * 70;
    p.animate([
      { transform: 'translate(-50%,-50%) rotate(0) scale(1)' },
      { transform: `translate(${Math.cos(a) * d - size / 2}px, ${Math.sin(a) * d - 30 - size / 2}px) rotate(${Math.random() * 540 - 270}deg) scale(1)`, offset: 0.7 },
      { transform: `translate(${Math.cos(a) * d * 1.1 - size / 2}px, ${Math.sin(a) * d + 40}px) rotate(${Math.random() * 720 - 360}deg) scale(0)` },
    ], { duration: 650 + Math.random() * 300, easing: 'cubic-bezier(.2,.7,.4,1)' }).onfinish = () => p.remove();
    setTimeout(() => p.remove(), 1500);   // even if the animation never ran
  }
}
