// multislider(ctx, ids, {height, barWidth, labels, label}) -> element
//
// Max's multislider: N params as a row of bars. Draw across them with one finger and each bar takes the height
// under it (fast swipes fill the bars in between). Two fingers or hold-then-drag is fine mode: the bar you started
// on moves relative to the finger instead. A press that does not move changes nothing. Each bar shows the set's
// value (acid tick), the tried range (pale band), and a thin blue cap where modulation has moved it from its knob.
// The readout names the last bar touched. Double tap: every bar back to the set. Long press: choose one to inspect.
//
//   height    the bars' height in px (default 150)
//   barWidth  each bar's width (default 34)
//   labels    the names under the bars (default: each param's short label)
//   label     the title

import { drag, h } from '../ui.js';
import { follow, normOf, shortLabel, stageColor } from './core.js';
import { setNorm, format } from '../params.js';
import { touches, writers } from './kit.js';

export function multislider(ctx, ids, { height = 150, barWidth = 34, labels, label } = {}) {
  const ps = ids.map((id) => ctx.params.get(id));
  const gw = writers(ctx, ids, 'multislider');
  const pct = (v) => `${(v * 100).toFixed(2)}%`;
  const read = h('span', { class: 'lcd-s ms-read' });
  const bars = ps.map((p) => h('div', { class: 'ms-bar', style: { '--c': stageColor(p) } },
    p.tried ? h('i', { class: 'ms-tried', style: { '--lo': pct(Math.min(normOf(p, p.tried[0]), normOf(p, p.tried[1]))), '--hi': pct(Math.max(normOf(p, p.tried[0]), normOf(p, p.tried[1]))) } }) : null,
    h('i', { class: 'ms-fill' }), h('i', { class: 'ms-base' }), h('i', { class: 'ms-set', style: { '--at': pct(setNorm(p)) } })));
  const field = h('div', { class: 'ms-bars' }, ...bars);
  const names = h('div', { class: 'ms-names' }, ...ps.map((p, i) => h('span', { text: labels?.[i] ?? shortLabel(p) })));
  const el = h('div', {
    class: 'w-ms', dataset: { param: ids.join(' ') },
    style: { '--h': `${height}px`, '--bw': `${barWidth}px`, '--n': ids.length, '--c': stageColor(ps[0]) },
  }, h('div', { class: 'ms-head' }, h('span', { class: 'w-label', text: label ?? 'multislider' }), read), field, names);

  let shown = 0;
  const showRead = (i) => {
    shown = i;
    read.textContent = `${labels?.[i] ?? shortLabel(ps[i])} ${format(ps[i], ctx.store.real(ids[i]))}`;
    read.classList.toggle('is-set-v', ctx.store.isSet(ids[i]));
  };
  ids.forEach((id, i) => follow(ctx, id, (v) => {
    const b = bars[i];
    b.style.setProperty('--v', pct(v));
    b.style.setProperty('--b', pct(ctx.store.get(id)));
    b.classList.toggle('is-mod', Math.abs(ctx.store.get(id) - v) > 0.004);
    b.classList.toggle('is-set', ctx.store.isSet(id));
    if (i === shown) showRead(i);
  }));

  let rect = null, last = null, first = -1;
  const at = (x, y) => {
    const i = Math.max(0, Math.min(ids.length - 1, Math.floor(((x - rect.left) / rect.width) * ids.length)));
    const v = 1 - (y - rect.top - 6) / (rect.height - 12);
    return { i, v: Math.max(0, Math.min(1, v)) };
  };
  drag(field, {
    onStart: (e) => { rect = field.getBoundingClientRect(); last = null; first = at(e.clientX, e.clientY).i; gw.begin(); el.classList.add('is-touched'); },
    onMove: (_dx, dy, { x, y, fine }) => {
      if (fine) { gw.add(first, -dy / (rect.height - 12)); bars[first].classList.add('is-hot'); showRead(first); return; }
      const cur = at(x, y);
      if (last && last.i !== cur.i) {                       // fill the bars a fast swipe skipped
        const step = cur.i > last.i ? 1 : -1;
        for (let j = last.i + step; j !== cur.i; j += step) gw.set(j, last.v + (cur.v - last.v) * ((j - last.i) / (cur.i - last.i)));
      }
      gw.set(cur.i, cur.v);
      for (const b of bars) b.classList.remove('is-hot');
      bars[cur.i].classList.add('is-hot');
      showRead(cur.i);
      last = cur;
    },
    onEnd: () => { gw.end(); el.classList.remove('is-touched'); for (const b of bars) b.classList.remove('is-hot'); },
    onTap: (e) => { rect = field.getBoundingClientRect(); showRead(at(e.clientX, e.clientY).i); },
  });
  touches(field, ctx, ids, { name: label ?? 'The bars' });
  showRead(0);
  return el;
}
