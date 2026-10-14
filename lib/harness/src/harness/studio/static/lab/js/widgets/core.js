// What every widget shares: reading a param, writing it as one gesture, the set's mark, haptic detents.
//
// A widget is a function (ctx, id, opts) -> element. ctx is the surface's context:
//   ctx.store, ctx.params, ctx.engine     the shared state, the param list, the sound
//   ctx.own(unsubscribe)                  register cleanup; it runs when the surface unmounts
// Widgets never talk to the engine directly: they write the store, and the engine listens.

import { format, setNorm, toReal } from '../params.js';
import { haptic } from '../ui.js';

/** Follow one param: render(norm, real, text, source) now and on every change. */
export function follow(ctx, id, render) {
  const p = ctx.params.get(id);
  ctx.own(ctx.store.on(id, (v, _id, source) => {
    const real = toReal(p, v);
    render(v, real, format(p, real), source);
  }));
  return p;
}

/**
 * A writer for one param: w.begin(); w.set(norm) / w.add(delta); w.end(). One undo step per gesture; a haptic
 * tick on crossing the set's value, the tried range's edges, and every enum step.
 */
export function writer(ctx, id, source) {
  const p = ctx.params.get(id);
  const marks = [setNorm(p), ...(p.tried ? p.tried.map((x) => normOf(p, x)) : [])];
  let last = ctx.store.get(id);
  const w = {
    p,
    begin() { ctx.store.begin(); last = ctx.store.get(id); },
    set(v) {
      v = Math.min(1, Math.max(0, v));
      if (p.scale === 'enum' || p.scale === 'toggle') {
        const steps = p.scale === 'toggle' ? 1 : p.options.length - 1;
        v = Math.round(v * steps) / steps;
        if (v !== last) haptic();
      } else if (marks.some((m) => (last - m) * (v - m) < 0)) haptic();
      ctx.store.set(id, v, { source });
      last = v;
    },
    add(d) { w.set(ctx.store.get(id) + d); },
    end() { ctx.store.end(); },
  };
  return w;
}

export function normOf(p, real) {
  if (p.scale === 'log') return Math.log(real / p.min) / Math.log(p.max / p.min);
  return (real - p.min) / (p.max - p.min);
}

/** Stage colour for a param (its stage's token). */
export const stageColor = (p) => `var(--stage-${p.stage})`;

/** A short label: the param's `short`, or its label cut at 14 chars. */
export const shortLabel = (p) => p.short ?? (p.label.length > 14 ? p.label.slice(0, 13) + '…' : p.label);
