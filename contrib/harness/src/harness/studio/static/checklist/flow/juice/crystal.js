// The crystal as a juice object: the concept's crystal (crystal-draw.js, a pure function of the done set). On a
// commit the item's faint trace lights, then its shard grows out of its root with an overshoot, light runs across its
// three facets, a bloom opens at the seed and a shimmer travels out through the other shards. It ends on exactly the
// crystal a fresh draw of the new set gives.
import { drawCrystal, SIZE } from '../../concepts/crystal-draw.js';
import { asSet, bump, ease, el, fadeIn, keyFor, lerp, tween, wait } from './fx.js';

export const label = 'Crystal';

/** The whole drawing for a done set: the same set always gives the same markup. */
export const render = (data, done) => `<div class="jz jz-crystal">${drawCrystal(data, asSet(done))}</div>`;

export function mini(host, data, doneKeys) {
  host.innerHTML = `<div class="jz jz-mini jz-crystal">${drawCrystal(data, asSet(doneKeys))}</div>`;
}

const C = SIZE / 2;
const opacityOf = (node) => Number(getComputedStyle(node).fillOpacity) || 0;
const rootOf = (g) => {
  const m = /translate\(([-\d.]+) ([-\d.]+)\)/.exec(g.getAttribute('transform') || '');
  return m ? [Number(m[1]), Number(m[2])] : [C, C];
};

export async function play(stage, { data, before, after, step, item, reduced }) {
  const [, , key] = keyFor(step, item);
  if (reduced) return fadeIn(stage, render(data, after));

  // BEFORE: the trace of what is about to crystallise catches the light
  stage.innerHTML = render(data, before);
  const trace = stage.querySelector(`.shard.trace[data-key="${key}"] .edge`);
  if (trace) {
    trace.classList.add('jz-hot');
    await tween(280, (e) => { trace.style.strokeOpacity = String(lerp(0.2, 1, e)); });
  }

  // AFTER, with the new shard starting from nothing at its root
  stage.innerHTML = render(data, after);
  const svg = stage.querySelector('svg');
  const g = stage.querySelector(`.shard.solid[data-key="${key}"]`);
  if (!svg || !g) return;
  const base = g.getAttribute('transform');
  const polys = [...g.querySelectorAll('polygon')];
  const edges = [...g.querySelectorAll('.edge')];
  const rest = polys.map(opacityOf);
  g.setAttribute('transform', `${base} scale(0.02 0.3)`);

  const fx = el('g', { class: 'jz-fx' }, svg);
  const defs = el('defs', {}, fx);
  const grad = el('radialGradient', { id: 'jz-bloom' }, defs);
  el('stop', { offset: '0', class: 'jz-bloom-0' }, grad);
  el('stop', { offset: '0.45', class: 'jz-bloom-1' }, grad);
  el('stop', { offset: '1', class: 'jz-bloom-2' }, grad);
  const bloom = el('circle', { cx: C, cy: C, r: 0, fill: 'url(#jz-bloom)' }, fx);
  const ring = el('circle', { cx: C, cy: C, r: 8, class: 'jz-ring' }, fx);
  const [rx, ry] = rootOf(g);

  const others = [...svg.querySelectorAll('.shard.solid')].filter((s) => s !== g).map((s) => {
    const [x, y] = rootOf(s);
    const p = s.querySelector('polygon');
    return { p, rest: opacityOf(p), d: Math.hypot(x - rx, y - ry) };
  });

  const motion = [
    // the shard grows out with a small overshoot
    tween(720, (e) => {
      g.setAttribute('transform', `${base} scale(${lerp(0.02, 1, e).toFixed(4)} ${lerp(0.3, 1, Math.min(1, e * 1.3)).toFixed(4)})`);
    }, { easing: ease.back }),
    // a bloom at the seed and a ring going out
    tween(760, (e, t) => { bloom.setAttribute('r', (lerp(0, 92, e)).toFixed(1)); bloom.style.opacity = String(1 - t); }),
    tween(1000, (e, t) => {
      ring.setAttribute('r', lerp(8, 190, e).toFixed(1));
      ring.style.strokeOpacity = String(0.85 * (1 - t));
      ring.style.strokeWidth = String(lerp(2.2, 0.4, t));
    }, { delay: 60 }),
    // light runs across the facets, one after another, and the edges flash gold then cool
    ...polys.map((p, i) => tween(360, (_, t) => {
      p.style.fillOpacity = String(rest[i] + (0.92 - rest[i]) * bump(t));
    }, { delay: 430 + i * 110, easing: ease.linear })),
    tween(1000, (_, t) => { for (const e of edges) e.style.stroke = t < 1 ? `color-mix(in srgb, var(--jz-gold) ${Math.round(100 * (1 - t))}%, var(--jz-ink))` : ''; }, { delay: 380, easing: ease.linear }),
    // a shimmer through the rest of the crystal, outward from the new shard
    ...others.map((o) => tween(420, (_, t) => {
      o.p.style.fillOpacity = String(o.rest + 0.34 * bump(t));
    }, { delay: 520 + o.d * 1.6, easing: ease.linear })),
    // the whole thing settles
    tween(1100, (e) => { svg.style.transform = `scale(${lerp(0.965, 1, e).toFixed(4)})`; }, { easing: ease.out }),
  ];
  // the commit completed the step: gold runs up the whole arm, root to tip
  const [sid] = keyFor(step, item);
  const all = (set) => (data.steps.find((x) => x.id === sid)?.items ?? []).every((it) => asSet(set).has(`${sid}.${it.id}`));
  if (all(after) && !all(before)) {
    const arm = [...svg.querySelectorAll(`.arm[data-step="${sid}"] .shard.solid`)];
    motion.push(...arm.map((s, i) => tween(460, (_, t) => {
      for (const e of s.querySelectorAll('.edge:not(.inner)')) e.style.stroke = t < 1 ? `color-mix(in srgb, var(--jz-gold) ${Math.round(100 * bump(t))}%, var(--jz-ink))` : '';
    }, { delay: 900 + i * 45, easing: ease.linear })));
  }
  await Promise.all(motion);
  await wait(60);
  stage.innerHTML = render(data, after);          // exactly the drawing of the new set
}
