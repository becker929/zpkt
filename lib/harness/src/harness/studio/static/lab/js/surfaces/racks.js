// Racks for a surface: a titled panel per param group, filled with a widget per param. The plainest surface; the
// designed ones use it for their "every knob" section.

import { h } from '../ui.js';
import { knob } from '../widgets/knob.js';
import { toggle } from '../widgets/fader.js';

/** A rack: title, optional subtitle and note, children (or build(body)). */
export function rack(title, { sub, note, row = false, cls = '' } = {}, ...children) {
  return h('section', { class: `rack ${cls}`.trim() },
    h('div', { class: 'rack-head' }, h('span', { class: 'rack-title', text: title }), sub ? h('span', { class: 'rack-sub', text: sub }) : null),
    h('div', { class: `rack-body${row ? ' is-row' : ''}` }, ...children),
    note ? h('p', { class: 'rack-note', text: note }) : null);
}

/** The control a param gets by default: a toggle for on/off and enums, a knob for the rest. */
export function control(ctx, id, opts = {}) {
  const p = ctx.params.get(id);
  return p.scale === 'toggle' || p.scale === 'enum' ? toggle(ctx, id, opts) : knob(ctx, id, opts);
}

/** Every param of the stage, a rack per group. */
export function allRacks(ctx, stage = ctx.stage) {
  return ctx.params.groups(stage).map((group) => rack(group, { sub: `${ctx.params.group(stage, group).length} controls` },
    ...ctx.params.group(stage, group).map((p) => control(ctx, p.id))));
}

export function stageHead(title, accent, about) {
  return h('header', { class: 'stage-head' }, h('h1', {}, `${title} `, h('em', { text: accent })), h('p', { text: about }));
}
