// Works: the juice as descriptions the page performs (docs/artist-agent.md). A work is a set of values for the page's
// primitives (the vocabulary below); the artist agent composes and tunes works, and new primitives only arrive as
// reviewed code. The repertoire comes from the harness (the artist's current version), else the seed in works.json.
//
// Which work plays on a commit: mostly what he has liked, weighted; a known work wears off each time it is seen
// recently; a rare work enters the draw only when its rarity roll passes, so it stays rare; about one commit in ten
// goes to the least-seen work of those in the draw instead (a delight is partly
// surprise). Night works only play at night. The pick is seeded by the commit, so the same history picks the same.
import { hash, rng } from '../concepts/model.js';

export const PRIMITIVES = {
  seal: ['check', 'wax'],
  particles: { power: [0.3, 2], palette: ['white', 'gold', 'ember', 'ink'] },
  shake: [0, 1.6],
  hitstop: [30, 220],
  lift: [90, 150],
  lamp: 'bool',
  sky: ['none', 'stars'],
  pace: [0.75, 1.35],
};
export const PALETTES = {
  white: { ink: '#ffffff', accent: '#f1b64a' },
  gold: { ink: '#f1b64a', accent: '#fff3d6' },
  ember: { ink: '#ff7a3d', accent: '#ffd27a' },
  ink: { ink: '#cfc9bf', accent: '#7d776d' },
};
export const DEFAULT = { seal: 'check', particles: { power: 1, palette: 'white' }, shake: 1, hitstop: 85, lift: 112, lamp: false, sky: 'none', pace: 1 };

const num = (v, [lo, hi], d) => (Number.isFinite(v) ? Math.min(hi, Math.max(lo, v)) : d);
const one = (v, list, d) => (list.includes(v) ? v : d);
/** A work's values, each kept inside the vocabulary (a bad value falls back to the default, never breaks a commit). */
export function params(p = {}) {
  const P = PRIMITIVES, D = DEFAULT;
  return {
    seal: one(p.seal, P.seal, D.seal),
    particles: { power: num(p.particles?.power, P.particles.power, 1), palette: one(p.particles?.palette, P.particles.palette, 'white') },
    shake: num(p.shake, P.shake, D.shake),
    hitstop: num(p.hitstop, P.hitstop, D.hitstop),
    lift: num(p.lift, P.lift, D.lift),
    lamp: p.lamp === true,
    sky: one(p.sky, P.sky, D.sky),
    pace: num(p.pace, P.pace, D.pace),
  };
}

/** The artist's current repertoire: {version, works}. */
export async function repertoire() {
  for (const url of ['/studio/api/artist/repertoire', new URL('works.json', import.meta.url).href]) {
    try {
      const r = await fetch(url, { cache: 'no-store' });
      if (!r.ok) continue;
      const rep = await r.json();
      if (Array.isArray(rep.works) && rep.works.length) return rep;
    } catch { /* the next source */ }
  }
  return { version: 0, works: [{ id: 'ledger', title: 'The ledger', weight: 1, rarity: 1, params: DEFAULT }] };
}

export const isNight = (d = new Date()) => d.getHours() >= 21 || d.getHours() < 5;

/**
 * The work for this commit. `recent`: the ids of the works played lately, oldest first. `seed`: something that names
 * this commit (its item key and the plate count). Returns the work, with `params` kept in the vocabulary.
 */
export function choose(rep, { recent = [], seed = '', now = new Date() } = {}) {
  const r = rng(hash(`${seed}|${recent.length}`));
  const night = isNight(now);
  const works = rep.works.filter((w) => !w.when?.night || night);
  // a rare work only comes into the draw when its own roll says so: novelty can't make it common
  const rolled = works.filter((w) => r() < Math.max(0.02, Math.min(1, w.rarity ?? 1)));
  const pool = rolled.length ? rolled : works.length ? works : rep.works;
  const last8 = recent.slice(-8);
  const seen = (w) => last8.filter((id) => id === w.id).length;
  let pick;
  if (r() < 0.1) {
    // the edge: the least-seen work over the whole history
    const count = (w) => recent.filter((id) => id === w.id).length;
    const least = Math.min(...pool.map(count));
    const cands = pool.filter((w) => count(w) === least);
    pick = cands[Math.floor(r() * cands.length)];
  } else {
    const score = (w) => Math.max(0, w.weight ?? 1) * 0.5 ** seen(w)
      * (recent.at(-1) === w.id ? 0.35 : 1);                       // and rarely the same twice running
    const total = pool.reduce((a, w) => a + score(w), 0);
    let x = r() * total;
    pick = pool.find((w) => (x -= score(w)) <= 0) ?? pool[0];
  }
  return { ...pick, version: rep.version, params: params(pick.params) };
}
