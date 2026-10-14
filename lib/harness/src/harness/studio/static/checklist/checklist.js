// The track's checklist across the spine: seven steps, each a list of items to clear. A first draft: the steps and
// items come from data/<track>.json; what is inside an item is a wireframe mock-up. Holding an item clears it (or
// opens it again); a tap looks inside. Checks are kept in this browser until the agent's store exists.

const TRACK = new URLSearchParams(location.search).get('track') || 'hw002';
const KEY = `checklist:${TRACK}`;
const HOLD_MS = 520;
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
  refresh(true);
}

function card(step) {
  const ticks = h('div', { class: 'ticks' }, step.items.map(() => h('i')));
  const count = h('span', { class: 'count' });
  const chip = h('span', { class: 'state' });
  const head = h('button', { class: 'card-head', type: 'button', 'aria-expanded': 'false',
    onclick: () => { open = open === step.id ? null : step.id; haptic(); refresh(); } },
  h('span', { class: 'num', text: step.n }),
  h('span', { class: 'name', text: step.name }),
  chip, count, ticks);
  const list = h('ol', { class: 'items' }, step.items.map((it) => item(step, it)));
  const el = h('section', { class: 'card', id: `step-${step.id}`, 'data-step': step.id }, head,
    h('div', { class: 'body' }, h('div', { class: 'body-in' }, list)), h('div', { class: 'sheen' }));
  cards.set(step.id, { el, head, ticks, count, chip });
  return el;
}

function item(step, it) {
  const sock = h('span', { class: 'sock' },
    h('svg', { viewBox: '0 0 32 32', 'aria-hidden': 'true' },
      h('rect', { class: 'sock-frame', x: 3, y: 3, width: 26, height: 26, rx: 3 }),
      h('rect', { class: 'sock-fill', x: 3, y: 3, width: 26, height: 26, rx: 3, pathLength: 100 }),
      h('path', { class: 'sock-check', d: 'M9 16.5l4.6 4.5L23.5 11', pathLength: 100 })));
  const chip = h('span', { class: 'chip' });
  const why = h('span', { class: 'why' });
  const row = h('div', { class: 'row', role: 'button', tabindex: '0' },
    h('span', { class: 'hold' }), sock,
    h('span', { class: 'label' }, h('span', { class: 'ttl', text: it.title }), why),
    chip);
  const li = h('li', { class: 'item', 'data-id': it.id }, row, mock(step, it));
  li.paint = (role) => {
    const st = stateOf(step, it);
    li.dataset.state = st;
    li.dataset.role = role;
    li.classList.toggle('gate', !!it.gate);
    const [text, cls] = CHIP[role] ?? (it.gate && st !== 'done' ? ['Gate', 'chip-gate'] : ['', '']);
    chip.textContent = text; chip.className = `chip ${cls}`;
    why.textContent = role === 'done' || role === 'ahead' ? '' : (WHY[role] ?? it.why ?? '');
  };
  li.paint(stateOf(step, it) === 'done' ? 'done' : 'ahead');
  li.paint();
  holdable(row, li, step, it);
  return li;
}

// What is inside an item: a wireframe, every word of it a placeholder.
function mock(step, it) {
  const line = (w) => h('span', { class: 'ph', style: { '--w': `${w}%` } });
  const sub = (k) => h('li', {}, h('span', { class: 'msock' }), h('span', { class: 'mtext' }, `Sub-step ${k}`, h('em', { text: ' · mocked' })), line(30 + ((k * 23) % 40)));
  return h('div', { class: 'mock' }, h('div', { class: 'mock-in' },
    h('div', { class: 'mock-tag', text: 'Mock-up · wireframe' }),
    h('ol', { class: 'msub' }, [1, 2, 3].map(sub)),
    h('div', { class: 'mbox' }, h('b', { text: 'Agent’s question (mocked)' }), line(90), line(64),
      h('div', { class: 'mchoices' }, h('span', { text: 'Choice A' }), h('span', { text: 'Choice B' }), h('span', { text: 'Later' }))),
    h('div', { class: 'mrow' },
      h('div', { class: 'mbox mwidget' }, h('b', { text: 'Widget (mocked)' }), h('div', { class: 'xbox' })),
      h('div', { class: 'mbox' }, h('b', { text: 'Evidence (mocked)' }), line(80), line(55), line(70))),
    h('div', { class: 'mfoot', text: `${step.n}.${step.items.indexOf(it) + 1} · history, renders and notes go here (mocked)` })));
}

function spine() {
  const nav = $('spine');
  nav.replaceChildren(...data.steps.map((s) => h('button', { type: 'button', class: 'node', 'data-step': s.id,
    'aria-label': `${s.n} ${s.name}`,
    onclick: () => { open = s.id; haptic(); refresh(); $(`step-${s.id}`).scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'start' }); } },
  h('span', { class: 'gem' }), h('span', { class: 'node-n', text: s.n }))));
}

function refresh(first = false) {
  const cur = current();
  let n = 0, of = 0;
  for (const step of data.steps) {
    const c = cards.get(step.id), k = cleared(step);
    n += k; of += step.items.length;
    const state = isClear(step) ? 'clear' : step === cur ? 'current' : 'open';
    c.el.dataset.state = state;
    c.el.classList.toggle('open', open === step.id);
    c.head.setAttribute('aria-expanded', String(open === step.id));
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
  hud(cur, first);
}

function hud(cur) {
  const hudEl = $('hud');
  if (!cur) {
    hudEl.dataset.done = 'true';
    $('hud-n').textContent = ''; $('hud-name').textContent = 'Every step cleared';
    $('hud-bar').replaceChildren(); $('hud-meta').textContent = 'Ready to release';
    return;
  }
  hudEl.dataset.done = 'false';
  $('hud-n').textContent = cur.n; $('hud-name').textContent = cur.name;
  const r = roles(cur);
  $('hud-bar').replaceChildren(...r.map((x) => h('i', { class: x })));
  const n = (x) => r.filter((y) => y === x).length;
  const parts = [];
  if (n('you')) parts.push(`${n('you')} your move`);
  if (n('ready')) parts.push(`${n('ready')} ready`);
  if (n('clearing')) parts.push(`agent clearing ${n('clearing')}`);
  if (n('ahead')) parts.push(`${n('ahead')} ahead`);
  $('hud-meta').textContent = parts.join(' · ');
}

// --- hold to clear, tap to look inside ---
function holdable(row, li, step, it) {
  let t0 = 0, x0 = 0, y0 = 0, raf = 0, timer = 0, half = false, held = false;
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
    li.classList.add('holding');
    haptic();
    const tick = () => {
      const p = Math.min(1, (performance.now() - t0) / HOLD_MS);
      li.style.setProperty('--hold', p.toFixed(3));
      if (p > 0.5 && !half) { half = true; haptic(); }
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    timer = setTimeout(() => { held = true; end(false); toggle(li, step, it); }, HOLD_MS);
  });
  row.addEventListener('pointermove', (e) => {
    if (t0 && Math.hypot(e.clientX - x0, e.clientY - y0) > MOVE_PX) end(true);
  });
  row.addEventListener('pointerup', () => {
    if (!t0) return;
    const quick = performance.now() - t0 < 260;
    end(!held && !quick);
    if (quick && !held) { li.classList.toggle('peek'); haptic(); }
  });
  row.addEventListener('pointercancel', () => end(true));
  row.addEventListener('contextmenu', (e) => e.preventDefault());
  row.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') toggle(li, step, it);
    if (e.key === ' ') { e.preventDefault(); li.classList.toggle('peek'); }
  });
}

function toggle(li, step, it) {
  const wasClear = isClear(step);
  const was = stateOf(step, it);
  const next = was === 'done' ? (it.state === 'done' ? 'open' : it.state) : 'done';
  saved[`${step.id}.${it.id}`] = next;
  save();
  if (next === 'done') {
    haptic(true);
    burst(li.querySelector('.sock'));
    sheen(cards.get(step.id).el);
    li.classList.add('stamp'); setTimeout(() => li.classList.remove('stamp'), 600);
  } else {
    haptic();
    li.classList.add('unstamp'); setTimeout(() => li.classList.remove('unstamp'), 400);
  }
  refresh();
  const c = cards.get(step.id);
  c.count.classList.remove('bump'); void c.count.offsetWidth; c.count.classList.add('bump');
  if (!wasClear && isClear(step)) clearedStep(step);
}

function burst(at) {
  if (reduced) return;
  const r = at.getBoundingClientRect();
  for (let i = 0; i < 3; i++) {
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

$('reset').addEventListener('click', () => {
  saved = {}; save(); haptic(true);
  open = current()?.id ?? null; refresh();
});

load();
fetch(`data/${encodeURIComponent(TRACK)}.json`, { cache: 'no-cache' })
  .then((r) => { if (!r.ok) throw new Error(`no checklist for ${TRACK}`); return r.json(); })
  .then((d) => { data = d; render(); })
  .catch((err) => { $('steps').append(h('p', { class: 'err', text: String(err.message || err) })); });
