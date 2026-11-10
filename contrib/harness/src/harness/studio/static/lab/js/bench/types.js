// The Bench's object types: what each box is called (Max's names where Max has one), how many params it takes,
// its inlets and outlets, its width, and how its body is built from the widget library.
//
//   kind 'ui'     a widget bound to params: one inlet (modulation in, added to every param it holds); a box with
//                 one param also has an outlet (its move away from the set, to patch into another param: a link)
//   kind 'mod'    a modulator on the bar clock (mods.js): an inlet (scales its depth) and an outlet
//   kind 'meter'  a meter on the master or a bus: no cords
//   kind 'note'   a comment

import { h, s } from '../ui.js';
import * as W from '../widgets/index.js';
import { MODS, modIcon } from './mods.js';

const icon = (d) => s('svg', { viewBox: '0 0 24 24', class: 'bn-ic', 'aria-hidden': 'true' }, s('path', { d }));
const I = {
  dial: 'M12 4a8 8 0 1 1-5.7 2.3M12 12l-4-4',
  slider: 'M12 3v18M8 9h8v4H8z',
  numbox: 'M3 7h18v10H3zM6 10l3 2-3 2',
  tab: 'M3 8h18v8H3zM9 8v8M15 8v8',
  toggle: 'M4 8h16v8H4zM8 12h.01',
  encoder: 'M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18M12 7v3',
  radial: 'M12 12L12 3A9 9 0 0 1 20 9zM12 12l-8 5',
  ribbon: 'M2 10h20v4H2zM9 8v8',
  spring: 'M2 10h20v4H2zM12 8v8M8 12h-3M16 12h3',
  crossfader: 'M3 12h18M10 8h4v8h-4z',
  xy: 'M4 4h16v16H4zM12 4v16M4 12h16M15 9a1 1 0 1 0 .01 0',
  multislider: 'M4 20V10M8 20V6M12 20v-8M16 20V4M20 20v-12',
  nodes: 'M9 9a5 5 0 1 0 .01 0M15 15a5 5 0 1 0 .01 0',
  macro: 'M12 5a7 7 0 1 1-.01 0M12 12l3-3M4 21h16',
  link: 'M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1',
  abc: 'M3 6h5v12H3zM10 6h5v12h-5zM17 6h4v12h-4z',
  pads: 'M4 4h7v7H4zM13 4h7v7h-7zM4 13h7v7H4zM13 13h7v7h-7z',
  steps: 'M3 8h3v8H3zM8 8h3v8H8zM13 8h3v8h-3zM18 8h3v8h-3z',
  matrix: 'M5 5h.01M12 5h.01M19 5h.01M5 12h.01M12 12h.01M19 12h.01M5 19h.01M12 19h.01M19 19h.01',
  meter: 'M9 3h6v18H9zM9 9h6M9 15h6',
  vu: 'M3 17a9 9 0 0 1 18 0M12 17l4-7',
  scope: 'M2 12c3-7 4 7 7 0s4-7 7 0 4 7 6 0',
  spectrum: 'M3 20v-6M7 20v-11M11 20v-8M15 20v-5M19 20v-3',
  comment: 'M4 6h16M4 11h12M4 16h9',
};

// The bus matrix: buses down the side, level / space / drive across.
const BUS_GRID = [['mix.kick', 'kick.verb', 'kick.drive'], ['mix.perc', 'mix.spaceMix', 'mix.hatsDrive'], ['mix.sfx', 'mix.sfxVerb', null]];

/** {type: {cls, kind, params: [min, max], width, about, icon, build(octx, obj, keepState) -> element}} */
export const TYPES = {
  // --- one param ----------------------------------------------------------------------------------------------
  dial: { cls: 'live.dial', kind: 'ui', params: [1, 1], width: 168, about: 'A knob.', build: (c, o) => W.knob(c, o.params[0], { size: 64 }) },
  slider: { cls: 'live.slider', kind: 'ui', params: [1, 1], width: 160, about: 'A long fader.', build: (c, o) => W.fader(c, o.params[0], { length: 130 }) },
  numbox: { cls: 'live.numbox', kind: 'ui', params: [1, 1], width: 168, about: 'A number box: drag a digit, tap to type.', build: (c, o) => W.numberBox(c, o.params[0], { width: 100 }) },
  tab: { cls: 'live.tab', kind: 'ui', params: [1, 1], width: 300, about: 'A segmented switch for a choice.', build: (c, o) => W.segmented(c, o.params[0]) },
  toggle: { cls: 'live.toggle', kind: 'ui', params: [1, 1], width: 168, about: 'A latching button.', build: (c, o) => W.toggle(c, o.params[0], { wide: true }) },
  encoder: { cls: 'encoder', kind: 'ui', params: [1, 1], width: 150, about: 'An endless encoder with detents.', build: (c, o) => W.encoder(c, o.params[0], { size: 76 }) },
  radial: { cls: 'radial', kind: 'ui', params: [1, 1], width: 150, about: 'A pie menu for a choice: press and slide.', build: (c, o) => W.radial(c, o.params[0], { size: 64 }) },
  ribbon: { cls: 'ribbon', kind: 'ui', params: [1, 1], width: 320, about: 'A long touch strip.', build: (c, o) => W.ribbon(c, o.params[0], { length: 300 }) },
  spring: { cls: 'ribbon.spring', kind: 'ui', params: [1, 1], width: 320, about: 'Throw a param and it springs back.', build: (c, o) => W.ribbon(c, o.params[0], { length: 300, mode: 'spring' }) },
  crossfader: { cls: 'crossfader', kind: 'ui', params: [1, 1], width: 320, about: 'A DJ crossfader with a centre detent.', build: (c, o) => W.crossfader(c, o.params[0], { length: 300 }) },
  // --- many params --------------------------------------------------------------------------------------------
  xy: { cls: 'xy', kind: 'ui', params: [2, 2], width: 248, about: 'Two params on one pad, with a trail.', build: (c, o) => W.xyPad(c, o.params, { size: 232 }) },
  multislider: { cls: 'multislider', kind: 'ui', params: [2, 8], width: null, about: 'Bars you draw across.', build: (c, o) => W.multislider(c, o.params, { barWidth: 40, height: 140, label: o.opts?.label }) },
  nodes: { cls: 'nodes', kind: 'ui', params: [1, 8], width: 268, about: 'Blend snapshots by moving among circles.', build: (c, o, k) => W.nodes(c, o.params, { size: 252, snapshots: o.opts?.snapshots, label: o.opts?.label, ...k }) },
  macro: { cls: 'macro', kind: 'ui', params: [1, 6], width: 286, about: 'One big knob over many params.', build: (c, o, k) => W.macro(c, o.opts?.targets ?? o.params, { label: o.opts?.label ?? 'macro', size: 116, ...k }) },
  link: { cls: 'link', kind: 'ui', params: [2, 2], width: 210, about: 'Two params moving together.', build: (c, o) => W.link(c, o.params, { size: 140, label: o.opts?.label ?? 'link' }) },
  abc: { cls: 'abc', kind: 'ui', params: [1, 4], width: 320, about: 'Three snapshots switched on the bar grid.', build: (c, o, k) => W.abcTapper(c, o.params, { ...k }) },
  pads: { cls: 'pads', kind: 'ui', params: [1, 8], width: 320, about: 'Hit to throw a param; velocity from where you hit.', build: (c, o) => W.padGrid(c, o.params, { cols: 4 }) },
  steps: { cls: 'step.grid', kind: 'ui', params: [1, 4], width: 340, about: 'A 16-step lane per param.', build: (c, o, k) => W.stepGrid(c, o.params, { ...k }) },   // k.gate: the lane plays only while the bench runs
  matrix: { cls: 'matrixctrl', kind: 'ui', params: [0, 0], fixed: BUS_GRID.flat().filter(Boolean), width: 252, about: 'The buses against level, space and drive.', build: (c) => W.matrixctrl(c, BUS_GRID, { rows: ['Kick', 'Perc', 'SFX'], cols: ['Level', 'Space', 'Drive'], label: 'buses' }) },
  // --- modulators ---------------------------------------------------------------------------------------------
  ...Object.fromEntries(Object.entries(MODS).map(([k, m]) => [k, { cls: m.cls, kind: 'mod', params: [0, 0], width: 176, about: m.about, mod: true }])),
  // --- meters -------------------------------------------------------------------------------------------------
  meter: { cls: 'meter~', kind: 'meter', params: [0, 0], width: 104, about: 'An LED ladder.', build: (c, o) => W.ledLadder(c, o.opts?.source ?? 'master', { height: 150, label: o.opts?.source ?? 'master' }) },
  vu: { cls: 'vu~', kind: 'meter', params: [0, 0], width: 220, about: 'A VU needle.', build: (c, o) => W.vu(c, o.opts?.source ?? 'master', { width: 204 }) },
  scope: { cls: 'scope~', kind: 'meter', params: [0, 0], width: 260, about: 'An oscilloscope.', build: (c, o) => W.scope(c, o.opts?.source ?? 'master', { width: 244, height: 96 }) },
  spectrum: { cls: 'spectroscope~', kind: 'meter', params: [0, 0], width: 260, about: 'A spectrum with the sub, mids and air marked.', build: (c, o) => W.spectrum(c, o.opts?.source ?? 'master', { width: 244, height: 96 }) },
  // --- a comment ----------------------------------------------------------------------------------------------
  comment: { cls: 'comment', kind: 'note', params: [0, 0], width: 330, about: 'A note on the patch.', build: (_c, o) => h('p', { class: 'bn-note', text: o.opts?.text ?? '' }) },
};

export const typeIcon = (type) => (TYPES[type]?.mod ? modIcon(type) : icon(I[type] ?? I.comment));

/** Inlets and outlets of an object. */
export function ports(obj) {
  const t = TYPES[obj.type];
  if (!t) return { ins: 0, outs: 0 };
  if (t.kind === 'mod') return { ins: 1, outs: 1 };
  if (t.kind === 'ui') return { ins: 1, outs: obj.params.length === 1 ? 1 : 0 };
  return { ins: 0, outs: 0 };
}

/** The params a box holds (the bus matrix holds its own fixed set). */
export const paramsOf = (obj) => TYPES[obj.type]?.fixed ?? obj.params ?? [];

/** The box's title, Max-style: the class name and its arguments. */
export function titleOf(obj, params) {
  const t = TYPES[obj.type];
  if (!t) return obj.type;
  if (t.kind === 'meter') return `${t.cls} ${obj.opts?.source ?? 'master'}`;
  if (t.kind === 'note' || obj.type === 'matrix') return t.cls;
  const ids = obj.params ?? [];
  if (ids.length === 1) return `${t.cls} ${ids[0]}`;
  if (obj.type === 'macro' && obj.opts?.label) return `${t.cls} ${obj.opts.label}`;
  if (ids.length === 2) return `${t.cls} ${ids.map((id) => params.get(id).short ?? id).join(' ')}`.toLowerCase();
  return `${t.cls} ${ids.length}`;
}
