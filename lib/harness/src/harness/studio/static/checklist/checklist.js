// The track's checklist across the spine: seven steps, each a list of items to clear, each item a sub-list. A first
// draft: the steps and items come from data/<track>.json; the sub-lists are mocked. Holding clears (or opens again);
// a tap shows an item's sub-list, below it or on a page of its own; the work itself happens in studio, which an item
// links to. Switches can make it plain: black and white, everything unfolded, a tap on a box checks it. The tweaks panel (tweaks.js) changes how the page is built. Kept in this browser until the agent's store
// exists.
import { initTweaks, onTap, onTweak, tweak } from './tweaks.js';

const TRACK = new URLSearchParams(location.search).get('track') || 'hw002';
const KEY = `checklist:${TRACK}`;
const MOVE_PX = 10;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

const $ = (id) => document.getElementById(id);
const SVG = new Set(['svg', 'rect', 'path']);
function h(tag, attrs = {}, ...kids) {
  const el = SVG.has(tag) ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.setAttribute('class', v);
    else if (k === 'text') el.textContent = v;
    else if (k === 'style') for (const [p, x] of Object.entries(v)) el.style.setProperty(p, x);
    else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}

// --- haptics: iPhone Safari has no vibrate(); toggling an <input switch> through its label ticks (iOS 18+) ---
let lastTick = 0;
function haptic(strong = false) {
  const now = performance.now();
  if (now - lastTick < 35) return;
  lastTick = now;
  if (navigator.vibrate) { navigator.vibrate(strong ? 22 : 6); return; }
  document.querySelector('label.haptic')?.click();
}

// --- state ---
let data;
let saved = {};
function load() { try { saved = JSON.parse(localStorage.getItem(KEY)) || {}; } catch { saved = {}; } }
function save() { try { localStorage.setItem(KEY, JSON.stringify(saved)); } catch { /* private mode: this visit only */ } }
const stateOf = (step, item) => saved[`${step.id}.${item.id}`] ?? item.state;
// An item's sub-list is mocked: two to four sub-items, cleared with the item unless one was changed by hand.
const subCount = (it) => 2 + ([...it.id].reduce((a, c) => a + c.charCodeAt(0), 0) % 3);
const subKey = (step, it, k) => `${step.id}.${it.id}#${k}`;
const subDone = (step, it, k) => (saved[subKey(step, it, k)] ?? (stateOf(step, it) === 'done' ? 'done' : 'open')) === 'done';
const studioHref = (step, it) => `/studio/?focus=${encodeURIComponent(`${TRACK}.${step.id}.${it.id}`)}`;
const cleared = (step) => step.items.filter((it) => stateOf(step, it) === 'done').length;
const isClear = (step) => cleared(step) === step.items.length;
const current = () => data.steps.find((s) => !isClear(s));     // the lowest incomplete step

// A step is a path. You stand at its first open item (and at any item waiting on your listening); the agent works
// further down, so the items between you and it are ready: cleared by the agent, each waiting on your move above.
// The agent's own item is being cleared; past it is fog.
function roles(step) {
  const st = step.items.map((it) => stateOf(step, it));
  const you = st.findIndex((x) => x !== 'done');
  const agent = st.lastIndexOf('agent');
  return st.map((x, i) => {
    if (x === 'done') return 'done';
    if (i === you || x === 'waiting') return 'you';
    if (x === 'agent') return 'clearing';
    return agent > you && i > you && i < agent ? 'ready' : 'ahead';
  });
}

const CHIP = {
  you: ['Your move', 'chip-you'],
  ready: ['Ready', 'chip-ready'],
  clearing: ['Clearing', 'chip-agent'],
};
const WHY = { ready: 'Cleared · waits on your move (mocked)' };

// --- render ---
let open = null;          // the step whose card is open
const cards = new Map();  // step id -> {card, ticks, count, chip}

function render() {
  $('track').textContent = data.track;
  $('about').textContent = data.about;
  $('draft').textContent = data.draft;
  document.title = `${data.track} Checklist`;
  const main = $('steps');
  main.replaceChildren();
  for (const step of data.steps) main.append(card(step));
  spine();
  open = current()?.id ?? null;
  refresh();
}

function card(step) {
  const ticks = h('div', { class: 'ticks' }, step.items.map(() => h('i')));
  const count = h('span', { class: 'count' });
  const chip = h('span', { class: 'state' });
  const head = h('button', { class: 'card-head', type: 'button', 'aria-expanded': 'false' },
    h('span', { class: 'num', text: step.n }),
    h('span', { class: 'name', text: step.name }),
    chip, count, ticks);
  onTap(head, () => { if (!folding()) return; open = open === step.id ? null : step.id; haptic(); refresh(); });
  const list = h('ol', { class: 'items' }, step.items.map((it) => item(step, it)));
  const el = h('section', { class: 'card', id: `step-${step.id}`, 'data-step': step.id }, head,
    h('div', { class: 'body' }, h('div', { class: 'body-in' }, list)), h('div', { class: 'sheen' }));
  cards.set(step.id, { el, head, ticks, count, chip });
  return el;
}

function socket() {
  return h('span', { class: 'sock' },
    h('svg', { viewBox: '0 0 32 32', 'aria-hidden': 'true' },
      h('rect', { class: 'sock-frame', x: 3, y: 3, width: 26, height: 26, rx: 3 }),
      h('rect', { class: 'sock-fill', x: 3, y: 3, width: 26, height: 26, rx: 3, pathLength: 100 }),
      h('path', { class: 'sock-check', d: 'M9 16.5l4.6 4.5L23.5 11', pathLength: 100 })));
}

const ARROW = () => h('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, h('path', { d: 'M5 12h13M13 6l6 6-6 6' }));

function item(step, it) {
  const chip = h('span', { class: 'chip' });
  const why = h('span', { class: 'why' });
  const go = h('a', { class: 'go', href: studioHref(step, it), 'aria-label': `${it.title}: work on it in studio` }, ARROW());
  go.addEventListener('pointerdown', (e) => e.stopPropagation());
  onTap(go, () => { location.href = go.href; });
  const row = h('div', { class: 'row', role: 'button', tabindex: '0', 'aria-expanded': 'false' },
    h('span', { class: 'hold' }), socket(),
    h('span', { class: 'label' }, h('span', { class: 'ttl', text: it.title }), why),
    chip, go);
  const subs = h('div', { class: 'subs' }, h('div', { class: 'subs-in' }));
  const li = h('li', { class: 'item', 'data-id': it.id }, row, subs);
  li.paint = (role) => {
    const st = stateOf(step, it);
    li.dataset.state = st;
    li.dataset.role = role;
    li.classList.toggle('gate', !!it.gate);
    const [text, cls] = CHIP[role] ?? (it.gate && st !== 'done' ? ['Gate', 'chip-gate'] : ['', '']);
    chip.textContent = text; chip.className = `chip ${cls}`;
    why.textContent = role === 'done' || role === 'ahead' ? '' : (WHY[role] ?? it.why ?? '');
  };
  holdable(row, li, () => toggle(li, step, it), () => details(li, step, it));
  return li;
}

// An item's sub-list: its sub-items (mocked, but they clear like items) and the way to studio, where the work is.
function subList(step, it) {
  const n = subCount(it);
  const rows = [];
  for (let k = 1; k <= n; k++) {
    const row = h('div', { class: 'row sub-row', role: 'button', tabindex: '0' }, h('span', { class: 'hold' }), socket(),
      h('span', { class: 'label' }, h('span', { class: 'ttl' }, `Sub-item ${step.n}.${step.items.indexOf(it) + 1}.${k}`, h('em', { text: ' · mocked' }))));
    const li = h('li', { class: 'sub', 'data-sub': subKey(step, it, k) }, row);
    li.paint = () => { li.dataset.state = subDone(step, it, k) ? 'done' : 'open'; };
    li.paint();
    holdable(row, li, () => {
      const done = !subDone(step, it, k);
      saved[subKey(step, it, k)] = done ? 'done' : 'open'; save();
      if (done) { haptic(true); burst(row.querySelector('.sock')); } else haptic();
      paintSubs();
    }, () => {});
    rows.push(li);
  }
  const link = h('a', { class: 'studio-link', href: studioHref(step, it) },
    h('span', {}, h('b', { text: 'Work on it in studio' }), h('small', { text: 'Studio does not open on the item yet (mocked)' })),
    ARROW());
  onTap(link, () => { location.href = link.href; });
  return h('div', { class: 'sublist' }, h('ol', { class: 'subs-list' }, rows), link);
}

const paintSubs = () => document.querySelectorAll('[data-sub]').forEach((li) => li.paint());
const folding = () => tweak('folding') !== 'off';

// With folding off every step and every sub-list is open, all the time.
function unfold() {
  if (!data) return;
  for (const step of data.steps) {
    for (const it of step.items) {
      const li = $(`step-${step.id}`).querySelector(`.item[data-id='${it.id}']`);
      const inner = li.querySelector('.subs-in');
      if (!folding() && !inner.firstChild) inner.append(subList(step, it));
      li.classList.toggle('peek', !folding() || li.dataset.peeked === 'true');
    }
  }
  refresh();
}

function details(li, step, it) {
  if (!folding()) return;
  haptic();
  if (tweak('details') === 'drill') return drill(step, it);
  const open = !li.classList.contains('peek');
  const inner = li.querySelector('.subs-in');
  if (open && !inner.firstChild) inner.append(subList(step, it));
  li.classList.toggle('peek', open);
  li.dataset.peeked = String(open);
  li.querySelector('.row').setAttribute('aria-expanded', String(open));
}

function drill(step, it) {
  const el = $('drill');
  $('drill-crumb').replaceChildren(h('span', { class: 'crumb-n', text: step.n }), h('span', { text: step.name }));
  const li = $(`step-${step.id}`).querySelector(`.item[data-id='${it.id}']`);
  $('drill-body').replaceChildren(
    h('div', { class: `drill-item`, 'data-role': li.dataset.role },
      h('h2', { text: it.title }),
      h('div', { class: 'drill-chips' }, li.querySelector('.chip').cloneNode(true), h('span', { class: 'why', text: li.querySelector('.why').textContent }))),
    subList(step, it));
  el.classList.add('open'); el.setAttribute('aria-hidden', 'false');
  history.pushState({ drill: true }, '');
}
function closeDrill() {
  const el = $('drill');
  if (!el.classList.contains('open')) return;
  el.classList.remove('open'); el.setAttribute('aria-hidden', 'true');
  $('drill-body').replaceChildren();
}
onTap($('drill-back'), () => history.back());
addEventListener('popstate', closeDrill);

function spine() {
  const nav = $('spine');
  nav.replaceChildren(...data.steps.map((s) => {
    const node = h('button', { type: 'button', class: 'node', 'data-step': s.id, 'aria-label': `${s.n} ${s.name}` },
      h('span', { class: 'gem' }), h('span', { class: 'node-n', text: s.n }));
    onTap(node, () => { open = s.id; haptic(); refresh(); $(`step-${s.id}`).scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' }); });
    return node;
  }));
}

function refresh() {
  const cur = current();
  let n = 0, of = 0;
  for (const step of data.steps) {
    const c = cards.get(step.id), k = cleared(step);
    n += k; of += step.items.length;
    const state = isClear(step) ? 'clear' : step === cur ? 'current' : 'open';
    c.el.dataset.state = state;
    c.el.classList.toggle('open', !folding() || open === step.id);
    c.head.setAttribute('aria-expanded', String(!folding() || open === step.id));
    c.count.textContent = `${k}/${step.items.length}`;
    c.chip.textContent = { clear: 'Cleared', current: 'Current', open: '' }[state];
    const r = roles(step);
    [...c.ticks.children].forEach((t, i) => { t.className = r[i]; });
    c.el.querySelectorAll('.item').forEach((li, i) => li.paint(r[i]));
  }
  for (const node of $('spine').children) {
    const s = data.steps.find((x) => x.id === node.dataset.step);
    node.dataset.state = isClear(s) ? 'clear' : s === cur ? 'current' : 'open';
    node.classList.toggle('open', open === s.id);
  }
  $('total-n').textContent = n; $('total-of').textContent = of;
  hud(cur);
}

// The current objective, in whichever form the tweaks chose: the panel, a strip in the header, a line in the header,
// or nothing beyond the gems and the card.
function hud(cur) {
  const r = cur ? roles(cur) : [];
  const n = (x) => r.filter((y) => y === x).length;
  const parts = [];
  if (n('you')) parts.push(`${n('you')} your move`);
  if (n('ready')) parts.push(`${n('ready')} ready`);
  if (n('clearing')) parts.push(`agent clearing ${n('clearing')}`);
  if (n('ahead')) parts.push(`${n('ahead')} ahead`);
  const bar = () => r.map((x) => h('i', { class: x }));
  $('hud').dataset.done = String(!cur);
  $('hud-n').textContent = cur?.n ?? '';
  $('hud-name').textContent = cur?.name ?? 'Every step cleared';
  $('hud-bar').replaceChildren(...bar());
  $('hud-meta').textContent = cur ? parts.join(' · ') : 'Ready to release';
  $('strip-n').textContent = cur?.n ?? '';
  $('strip-name').textContent = cur?.name ?? 'All clear';
  $('strip-bar').replaceChildren(...bar());
  $('strip-meta').textContent = cur ? (n('you') ? `${n('you')} your move` : `${r.length - n('done')} left`) : '';
  $('hdr-obj').textContent = cur ? `Now: ${cur.n} ${cur.name} · ${parts[0] ?? ''}` : 'Every step cleared';
}

// --- hold to clear (or tap the box, a tweak), tap for details ---
const onBox = (row, x) => x <= row.querySelector('.sock').getBoundingClientRect().right + 12;
function holdable(row, li, onHold, onTap) {
  let t0 = 0, x0 = 0, y0 = 0, raf = 0, timer = 0, half = false, held = false;
  const ms = () => Number(tweak('hold')) || 520;
  const end = (cancel) => {
    cancelAnimationFrame(raf); clearTimeout(timer);
    li.style.setProperty('--hold', '0');
    li.classList.remove('holding');
    if (cancel && t0) { li.classList.add('snap'); setTimeout(() => li.classList.remove('snap'), 220); }
    t0 = 0;
  };
  row.addEventListener('pointerdown', (e) => {
    if (e.button > 0) return;
    t0 = performance.now(); x0 = e.clientX; y0 = e.clientY; half = false; held = false;
    if (tweak('check') === 'tap') return;
    li.classList.add('holding');
    haptic();
    const total = ms();
    const tick = () => {
      const p = Math.min(1, (performance.now() - t0) / total);
      li.style.setProperty('--hold', p.toFixed(3));
      if (p > 0.5 && !half) { half = true; haptic(); }
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    timer = setTimeout(() => { held = true; end(false); onHold(); }, total);
  });
  row.addEventListener('pointermove', (e) => {
    if (t0 && Math.hypot(e.clientX - x0, e.clientY - y0) > MOVE_PX) end(true);
  });
  row.addEventListener('pointerup', (e) => {
    if (!t0) return;
    if (tweak('check') === 'tap') { t0 = 0; if (onBox(row, e.clientX)) onHold(); else onTap(); return; }
    const quick = performance.now() - t0 < 260;
    end(!held && !quick);
    if (quick && !held) onTap();
  });
  row.addEventListener('pointercancel', () => end(true));
  row.addEventListener('contextmenu', (e) => e.preventDefault());
  row.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') onHold();
    if (e.key === ' ') { e.preventDefault(); onTap(); }
  });
}

function toggle(li, step, it) {
  const wasClear = isClear(step);
  const was = stateOf(step, it);
  const next = was === 'done' ? (it.state === 'done' ? 'open' : it.state) : 'done';
  saved[`${step.id}.${it.id}`] = next;
  save();
  for (let k = 1; k <= subCount(it); k++) delete saved[subKey(step, it, k)];     // its sub-items follow it
  save();
  if (next === 'done') {
    haptic(true);
    burst(li.querySelector('.sock'));
    if (tweak('effects') === 'full') sheen(cards.get(step.id).el);
    li.classList.add('stamp'); setTimeout(() => li.classList.remove('stamp'), 600);
  } else {
    haptic();
    li.classList.add('unstamp'); setTimeout(() => li.classList.remove('unstamp'), 400);
  }
  refresh();
  paintSubs();
  const c = cards.get(step.id);
  c.count.classList.remove('bump'); void c.count.offsetWidth; c.count.classList.add('bump');
  if (!wasClear && isClear(step)) clearedStep(step);
}

function burst(at) {
  if (reduced || tweak('effects') === 'off') return;
  const r = at.getBoundingClientRect();
  for (let i = 0; i < (tweak('effects') === 'full' ? 3 : 1); i++) {
    const ring = h('i', { class: 'ring', style: { left: `${r.left + r.width / 2}px`, top: `${r.top + r.height / 2}px`, '--d': `${i * 70}ms`, '--s': `${5 + i * 2.2}` } });
    document.body.append(ring);
    setTimeout(() => ring.remove(), 900 + i * 70);
  }
}

function sheen(el) {
  if (reduced) return;
  el.classList.remove('flash'); void el.offsetWidth; el.classList.add('flash');
  setTimeout(() => el.classList.remove('flash'), 800);
}

function clearedStep(step) {
  haptic(true); setTimeout(() => haptic(true), 120);
  if (tweak('effects') !== 'full') {
    setTimeout(() => { open = current()?.id ?? null; refresh(); }, 400);
    return;
  }
  const b = $('banner');
  $('banner-n').textContent = step.n; $('banner-name').textContent = step.name;
  b.classList.remove('show'); void b.offsetWidth; b.classList.add('show');
  setTimeout(() => {
    b.classList.remove('show');
    const next = current();
    open = next?.id ?? null;
    refresh();
    if (next) {
      const node = document.querySelector(`.node[data-step="${next.id}"]`);
      node?.classList.add('arrive'); setTimeout(() => node?.classList.remove('arrive'), 1200);
      $(`step-${next.id}`).scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' });
    }
  }, 1500);
}

onTap($('reset'), () => {
  saved = {}; save(); haptic(true);
  open = current()?.id ?? null; refresh(); paintSubs();
});

initTweaks(h, haptic);
const rebuilt = () => {
  if (tweak('details') === 'inline' || !folding()) closeDrill();
  unfold();
  document.querySelector('meta[name=theme-color]').content = getComputedStyle(document.body).backgroundColor;
};
onTweak(rebuilt);
rebuilt();
load();
fetch(`data/${encodeURIComponent(TRACK)}.json`, { cache: 'no-cache' })
  .then((r) => { if (!r.ok) throw new Error(`no checklist for ${TRACK}`); return r.json(); })
  .then((d) => { data = d; render(); unfold(); })
  .catch((err) => { $('steps').append(h('p', { class: 'err', text: String(err.message || err) })); });
