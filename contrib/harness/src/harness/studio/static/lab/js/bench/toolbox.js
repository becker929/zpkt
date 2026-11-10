// The Bench's toolbox: a sheet that slides up inside the bench. Pick an object; a control then asks which params
// (any stage: kick, mix, collage, arrange), a meter which bus, a comment its words. The box lands in the middle of
// the view, selected. The Patch section puts the starting patch back or clears the bench (tap twice).

import { h, haptic } from '../ui.js';
import { format } from '../params.js';
import { TYPES, typeIcon } from './types.js';

const SECTIONS = [
  ['Modulators, on the bar clock', ['cycle', 'phasor', 'noise', 'step', 'env']],
  ['One control', ['dial', 'slider', 'numbox', 'encoder', 'tab', 'radial', 'toggle', 'ribbon', 'spring', 'crossfader']],
  ['Many controls', ['xy', 'multislider', 'nodes', 'macro', 'link', 'abc', 'pads', 'steps', 'matrix']],
  ['Meters', ['meter', 'vu', 'scope', 'spectrum']],
];
const STAGES = [['all', 'All'], ['kick', 'Kick'], ['mix', 'Mix'], ['collage', 'Collage'], ['arrange', 'Arrange']];
const choice = (p) => p.scale === 'enum' || p.scale === 'toggle';

export function openToolbox(bench) {
  const ctx = bench.ctx;
  const sheet = h('div', { class: 'bn-sheet', role: 'dialog', 'aria-label': 'Add an object' });
  let gone = false;
  const close = () => {
    if (gone) return;
    gone = true;
    sheet.classList.remove('is-open');
    setTimeout(() => sheet.remove(), 220);
    if (bench.closeToolbox === close) bench.closeToolbox = null;
  };
  bench.el.append(sheet);
  requestAnimationFrame(() => sheet.classList.add('is-open'));

  const head = (title, back) => h('div', { class: 'bn-sh-head' },
    back ? h('button', { type: 'button', class: 'bn-sh-back', 'aria-label': 'Back', onclick: () => { haptic(); back(); } }, '‹') : null,
    h('b', { text: title }),
    h('button', { type: 'button', class: 'bn-sh-x', 'aria-label': 'Close', onclick: () => { haptic(); close(); } }, '×'));
  const show = (title, back, body, { top = null, foot = null } = {}) => sheet.replaceChildren(
    ...[h('div', { class: 'sheet-grip' }), head(title, back), top, h('div', { class: 'bn-sh-body' }, ...[].concat(body)), foot].filter(Boolean));
  const item = (type) => {
    const t = TYPES[type];
    return h('button', { type: 'button', class: `bn-item is-${t.kind}`, dataset: { type }, onclick: () => { haptic(); pick(type); } },
      typeIcon(type), h('b', { text: t.cls }), h('span', { text: t.about }));
  };

  function menu() {
    let armed = null;
    const danger = (text, again, fn) => {
      const b = h('button', { type: 'button', class: 'bn-item is-patch' }, h('b', { text }), h('span', { text: 'Tap twice' }));
      b.addEventListener('click', () => {
        haptic();
        if (armed !== b) { armed = b; b.classList.add('is-armed'); b.querySelector('span').textContent = again; return; }
        close(); fn();
      });
      return b;
    };
    show('Add an object', null, [
      ...SECTIONS.map(([title, types]) => h('section', { class: 'bn-sec' }, h('h3', { text: title }), h('div', { class: 'bn-items' }, ...types.map(item)))),
      h('section', { class: 'bn-sec' }, h('h3', { text: 'Patch' }), h('div', { class: 'bn-items' },
        item('comment'),
        danger('Starting patch', 'Tap again: this patch goes', () => bench.reset()),
        danger('Clear the bench', 'Tap again: every box goes', () => bench.clear())))]);
  }

  function pick(type) {
    const t = TYPES[type];
    if (t.kind === 'mod' || type === 'matrix') { close(); bench.add(type); return; }
    if (t.kind === 'meter') { sources(type); return; }
    if (t.kind === 'note') { comment(); return; }
    params(type);
  }

  function sources(type) {
    const list = [['master', 'The master: everything'], ['kick', 'The kick group (kick + rumble)'], ['perc', 'The perc group (hats)'], ['sfx', 'The SFX group']];
    show(`${TYPES[type].cls}: which bus?`, menu, h('div', { class: 'bn-rows' }, ...list.map(([id, text]) =>
      h('button', { type: 'button', class: 'bn-prow', onclick: () => { haptic(); close(); bench.add(type, [], { source: id }); } },
        h('b', { text: id }), h('span', { text })))));
  }

  function comment() {
    const input = h('textarea', { class: 'bn-text', rows: 3, placeholder: 'A note for the patch' });
    const go = h('button', { type: 'button', class: 'bn-go', text: 'Add the comment', onclick: () => {
      const text = input.value.trim();
      if (!text) return;
      haptic(); close(); bench.add('comment', [], { text });
    } });
    show('comment', menu, [input, go]);
    setTimeout(() => input.focus(), 50);
  }

  function params(type) {
    const t = TYPES[type];
    const [min, max] = t.params;
    const multi = max > 1;
    const chosen = [];
    let stage = 'all';
    const fit = (p) => (type === 'radial' || type === 'toggle' ? choice(p) : true);
    const go = h('button', { type: 'button', class: 'bn-go' });
    const rows = h('div', { class: 'bn-rows' });
    const chips = h('div', { class: 'bn-chips' }, ...STAGES.map(([id, label]) => h('button', {
      type: 'button', class: 'bn-chip', dataset: { stage: id }, 'aria-pressed': String(id === stage),
      onclick: () => { stage = id; haptic(); for (const c of chips.children) c.setAttribute('aria-pressed', String(c.dataset.stage === id)); fill(); },
    }, label)));
    const paint = () => {
      go.textContent = multi ? `Make the ${t.cls} (${chosen.length} of ${min === max ? max : `${min}-${max}`})` : '';
      go.disabled = chosen.length < min;
      go.hidden = !multi;
      for (const r of rows.querySelectorAll('.bn-prow')) r.classList.toggle('is-on', chosen.includes(r.dataset.id));
    };
    const make = () => { close(); bench.add(type, chosen.slice()); };
    go.addEventListener('click', () => { if (chosen.length >= min) { haptic(true); make(); } });
    function fill() {
      const list = ctx.params.list.filter((p) => (stage === 'all' || p.stage === stage) && fit(p));
      rows.replaceChildren(...list.map((p) => h('button', {
        type: 'button', class: 'bn-prow', dataset: { id: p.id }, style: { '--c': `var(--stage-${p.stage})` },
        onclick: () => {
          haptic();
          if (!multi) { chosen.splice(0, 1, p.id); make(); return; }
          const i = chosen.indexOf(p.id);
          if (i >= 0) chosen.splice(i, 1); else if (chosen.length < max) chosen.push(p.id);
          paint();
          if (min === max && chosen.length === max) make();
        },
      }, h('i'), h('b', { text: p.label }), h('span', { text: `${p.id} · ${format(p, ctx.store.real(p.id))}` }))));
      paint();
    }
    const say = multi ? (min === max ? `pick ${max}` : `pick ${min === 1 ? 'up to' : `${min} to`} ${max}`) : 'pick a control';
    show(`${t.cls}: ${say}`, menu, rows, { top: chips, foot: multi ? go : null });
    fill();
  }

  menu();
  return close;
}
