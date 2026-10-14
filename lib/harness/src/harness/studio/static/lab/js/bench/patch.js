// The Bench's patch: its objects and cords, kept on this phone (localStorage), and the patch it starts with.
//
//   {v: 1, objects: [{id, type, x, y, params: [ids], opts: {}, state: {}}], cords: [{from: [id, outlet], to: [id, inlet]}],
//    running: false, view: {tx, ty, z}}       running: the modulators were going when the patch was last saved
//
// x/y are world px (the canvas is 4000 x 4000); state is the object's own (a modulator's rate and depth, a step
// pattern, a nodes object's circles); opts are what it was made with (a meter's source, a comment's text).

import { setNorm, toNorm } from '../params.js';
import { TYPES } from './types.js';

export const KEY = 'hw002-lab:bench:v1';

/** The starting patch: it plays at once. Two modulators on the bar clock into two knobs, the colour on a pad, the
 *  batch-6 findings as nodes, the space as a multislider, and the master on a scope. */
export function defaultPatch(params) {
  const n = (id, real) => toNorm(params.get(id), real);
  const set = (ids) => Object.fromEntries(ids.map((id) => [id, setNorm(params.get(id))]));
  const NODE = ['kick.drive', 'rumble.drive', 'kick.colourFreq', 'kick.colour', 'mix.spaceMix', 'mix.spaceFeedback'];
  const snap = (over) => ({ ...set(NODE), ...Object.fromEntries(Object.entries(over).map(([id, v]) => [id, n(id, v)])) });
  const objects = [
    { id: 'o1', type: 'comment', x: 14, y: 8, opts: { text: 'RUN sets the modulators going. Drag from an outlet (tab under a box) to an inlet (tab on top) to patch; long-press a cord to cut it.' } },
    { id: 'o2', type: 'phasor', x: 14, y: 96, state: { rate: 1, depth: 22 } },
    { id: 'o3', type: 'cycle', x: 200, y: 96, state: { rate: 4, depth: 30, pol: 1 } },
    { id: 'o4', type: 'dial', x: 14, y: 352, params: ['kick.drive'] },
    { id: 'o5', type: 'dial', x: 200, y: 352, params: ['mix.spaceMix'] },
    { id: 'o7', type: 'xy', x: 14, y: 560, params: ['kick.colourFreq', 'kick.colour'] },
    { id: 'o6', type: 'meter', x: 272, y: 560, opts: { source: 'kick' } },
    { id: 'o8', type: 'nodes', x: 14, y: 984, params: NODE, opts: { label: 'batch 6', snapshots: [
      { name: 'SET', values: set(NODE) },
      { name: 'HARD', values: snap({ 'kick.drive': 45, 'rumble.drive': 45 }) },
      { name: 'COLOUR', values: snap({ 'kick.colourFreq': 2184, 'kick.colour': 7.58 }) },
      { name: 'SPACE', values: snap({ 'mix.spaceMix': 42.7, 'mix.spaceFeedback': 83.5 }) },
    ] } },
    { id: 'o9', type: 'multislider', x: 14, y: 1376, params: ['mix.spaceMix', 'mix.spaceFeedback', 'mix.spaceDelay', 'mix.spaceDensity', 'mix.spaceHighCut'], opts: { label: 'space' } },
    { id: 'o10', type: 'scope', x: 14, y: 1656, opts: { source: 'master' } },
  ];
  for (const o of objects) { o.params ??= []; o.opts ??= {}; }
  return {
    v: 1,
    objects,
    cords: [{ from: ['o2', 0], to: ['o4', 0] }, { from: ['o3', 0], to: ['o5', 0] }],
    running: false,                                   // nothing moves until RUN
    view: null,
  };
}

/** The saved patch if it is sound (objects whose params still exist, cords between objects that exist). */
export function loadPatch(params) {
  let p = null;
  try { p = JSON.parse(localStorage.getItem(KEY) || 'null'); } catch { p = null; }
  if (!p || p.v !== 1 || !Array.isArray(p.objects)) return defaultPatch(params);
  p.objects = p.objects.filter((o) => o && TYPES[o.type] && (o.params ?? []).every((id) => params.has(id)));
  for (const o of p.objects) { o.params ??= []; o.opts ??= {}; o.x = Number(o.x) || 0; o.y = Number(o.y) || 0; }
  const ids = new Set(p.objects.map((o) => o.id));
  p.cords = (p.cords ?? []).filter((c) => ids.has(c.from?.[0]) && ids.has(c.to?.[0]));
  return p;
}

export function savePatch(patch) {
  try { localStorage.setItem(KEY, JSON.stringify(patch)); } catch { /* private mode: this visit only */ }
}

/** A fresh object id. */
export function nextId(patch) {
  let n = 1;
  for (const o of patch.objects) n = Math.max(n, (parseInt(String(o.id).slice(1), 10) || 0) + 1);
  return `o${n}`;
}
