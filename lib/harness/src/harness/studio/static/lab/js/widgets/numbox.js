// numberBox(ctx, id, {label, width, unit}) -> element
//
// Max's number box: an LCD with a triangle. Drag a digit up or down and that digit moves (the tens digit by tens,
// the tenths by tenths; 10 px a step, two fingers or hold-then-drag a tenth of that). Tap to type a value (the
// phone's number pad; "2.2k" works for Hz). An enum steps through its options as you drag, and a tap opens a pie of
// them; an on/off flips on a tap. Acid when it holds the set's value. Long press: the inspector.
//
//   width   the box's width in px (default 96)
//   unit    false to hide the unit

import { drag, h, haptic, longPress, inspect } from '../ui.js';
import { follow, shortLabel, stageColor, writer } from './core.js';
import { format, toNorm } from '../params.js';
import { pie } from './radial.js';

const PX = 10;

export function numberBox(ctx, id, { label, width = 96, unit = true } = {}) {
  const p = ctx.params.get(id);
  const w = writer(ctx, id, 'numbox');
  const discrete = p.scale === 'enum' || p.scale === 'toggle';
  const digits = h('span', { class: 'num-digits' });
  const unitEl = h('span', { class: 'num-unit' });
  const tri = h('i', { class: 'num-tri' });
  const box = h('div', { class: 'num-box', role: 'spinbutton', tabindex: '0', 'aria-label': p.label }, tri, digits, unitEl);
  const el = h('div', {
    class: `w-num${discrete ? ' is-discrete' : ''}`, dataset: { param: id }, style: { '--w': `${width}px`, '--c': stageColor(p) },
  }, label === false ? null : h('div', { class: 'w-label', text: label ?? shortLabel(p) }), box);

  let real = 0, shown = null, hotPlace = null;
  follow(ctx, id, (v, r, text) => {
    real = r;
    render(text);
    el.classList.toggle('is-set', ctx.store.isSet(id));
    box.setAttribute('aria-valuetext', text);
  });

  function render() {
    const now = format(p, real, { unit: false });
    if (now === shown) return;
    shown = now;
    if (discrete) { digits.replaceChildren(h('span', { text: format(p, real) })); unitEl.textContent = ''; return; }
    let text = now;
    let mult = 1;
    if (/k$/.test(text)) { mult = 1000; text = text.slice(0, -1).trim(); }
    const dot = text.includes('.') ? text.indexOf('.') : text.length;
    digits.replaceChildren(...[...text].map((ch, i) => {
      const exp = /\d/.test(ch) ? (i < dot ? dot - i - 1 : -(i - dot)) : 0;
      const place = Math.pow(10, exp) * mult;
      return h('span', { text: ch, class: hotPlace === place && /\d/.test(ch) ? 'is-hot' : null, dataset: { place: String(place) } });
    }));
    unitEl.textContent = unit ? (mult === 1000 ? 'k' : '') + (p.unit === 'Hz' ? 'Hz' : p.unit) : '';
  }

  let place = 1, acc = 0, target = 0;
  drag(box, {
    onStart: (e) => {
      const t = document.elementFromPoint?.(e.clientX, e.clientY);
      place = Math.max(Number(t?.dataset?.place) || defaultPlace(), p.step ?? 0);
      acc = 0; target = real;
      w.begin();
      el.classList.add('is-touched');
      hotPlace = digits.contains(t) ? Number(t.dataset.place) : null;
      for (const sp of digits.children) sp.classList.toggle('is-hot', sp === t);
    },
    onMove: (_dx, dy, { fine }) => {
      acc += -dy;
      const unitPx = discrete ? 24 : PX;
      const steps = Math.trunc(acc / unitPx);
      if (!steps) return;
      acc -= steps * unitPx;
      if (discrete) {
        const n = p.scale === 'toggle' ? 1 : p.options.length - 1;
        w.set(Math.round(ctx.store.get(id) * n + steps) / n);
        return;
      }
      target = Math.min(p.max, Math.max(p.min, target + steps * place * (fine ? 0.1 : 1)));
      w.set(toNorm(p, target));
      haptic();
    },
    onEnd: () => { w.end(); el.classList.remove('is-touched'); hotPlace = null; for (const sp of digits.children) sp.classList.remove('is-hot'); },
    onTap: () => tap(),
  });
  longPress(box, () => { if (!ctx.local) inspect(id); });

  function defaultPlace() {
    const span = p.max - p.min;
    return Math.pow(10, Math.floor(Math.log10(span / 100)));
  }

  let menu = null;
  function tap() {
    if (p.scale === 'toggle') { w.begin(); w.set(ctx.store.get(id) >= 0.5 ? 0 : 1); w.end(); haptic(); return; }
    if (p.scale === 'enum') {
      const r = box.getBoundingClientRect();
      menu = pie(r.left + r.width / 2, r.top + r.height / 2, p.options, { title: p.label, current: Math.round(real) });
      menu.then((i) => { menu = null; if (i >= 0) { w.begin(); w.set(i / Math.max(1, p.options.length - 1)); w.end(); } });
      return;
    }
    edit();
  }

  function edit() {
    const input = h('input', {
      class: 'num-input', type: 'text', inputmode: 'decimal', enterkeyhint: 'done', 'aria-label': `Type ${p.label}`,
      value: String(Math.round(real * 1000) / 1000),
    });
    let gone = false;
    const commit = (ok) => {
      if (gone) return;
      gone = true;
      if (ok) {
        const raw = input.value.trim().replace(',', '.');
        let v = parseFloat(raw.replace(/[^\d.+-]/g, ''));
        if (/k/i.test(raw)) v *= 1000;
        if (Number.isFinite(v)) { w.begin(); w.set(toNorm(p, Math.min(p.max, Math.max(p.min, v)))); w.end(); haptic(true); }
      }
      input.remove();
      box.classList.remove('is-editing');
    };
    input.addEventListener('keydown', (e) => { if (e.key === 'Enter') commit(true); if (e.key === 'Escape') commit(false); });
    input.addEventListener('blur', () => commit(true));
    box.classList.add('is-editing');
    box.append(input);
    input.focus();
    input.select();
  }

  box.addEventListener('keydown', (e) => {
    const d = { ArrowUp: 1, ArrowRight: 1, ArrowDown: -1, ArrowLeft: -1 }[e.key];
    if (!d) return;
    e.preventDefault();
    w.begin();
    if (discrete) w.add(d / Math.max(1, (p.options?.length ?? 2) - 1));
    else w.set(toNorm(p, Math.min(p.max, Math.max(p.min, real + d * defaultPlace() * (e.shiftKey ? 10 : 1)))));
    w.end();
  });
  ctx.own(() => menu?.cancel());
  return el;
}
