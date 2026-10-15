// The image wall (docs/images.md): every image made with Gemini in this project, newest first, as a masonry wall.
// Each card has the image, its batch and brief context, the model and settings, and the full prompt; a thumb up or
// down on each tells the artist (docs/artist-agent.md) which way to go. Tap an image to see it whole.
//
// A wall can grow without end, so the page holds only what is near the screen: cards are laid out from the records'
// sizes before any image arrives (each card keeps its shape), an image loads as it comes within a screen and a half
// of view, and is let go again (its src removed, so the phone can free the decoded pixels) once it is further away
// than that. Records come a page at a time as the wall is scrolled.
const API = '/studio/images/api/list';
const FILES = '/studio/images/files/';
const PAGE = 40;
const NEAR = '150% 0px';
const THUMB = 'M7 10v10H4V10zM7 10l4-7c1.4 0 2.3 1.1 2 2.5L12.4 9H18a2 2 0 0 1 2 2.3l-1.2 7A2 2 0 0 1 16.8 20H7';

const wall = document.getElementById('wall');
const more = document.getElementById('more');
const view = document.getElementById('view');
const params = new URLSearchParams(location.search);
let batch = params.get('batch') || null;
let offset = 0, total = Infinity, loading = false, cols = [], heights = [];
const records = [];

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v; else if (k === 'text') el.textContent = v; else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const svg = (d, cls = '') => {
  const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg');
  s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); if (cls) s.setAttribute('class', cls);
  const p = document.createElementNS('http://www.w3.org/2000/svg', 'path'); p.setAttribute('d', d);
  s.append(p);
  return s;
};
const tap = (el, fn) => {
  // on the touch itself (iPhone WebKit can drop the click after a scroll); the keyboard still clicks
  let down = null;
  el.addEventListener('pointerdown', (e) => { down = [e.clientX, e.clientY]; });
  el.addEventListener('pointerup', (e) => { const ok = down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 10; down = null; if (ok) fn(e); });
  el.addEventListener('click', (e) => { if (e.detail === 0) fn(e); });
};
const haptic = () => { if (navigator.vibrate) navigator.vibrate(6); else document.querySelector('label.haptic')?.click(); };
const when = (iso) => {
  const d = new Date(iso);
  return `${d.toLocaleDateString(undefined, { day: 'numeric', month: 'short' })} ${d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })}`;
};
const settingsLine = (r) => [r.model, r.settings?.imageConfig?.aspectRatio, r.settings?.imageConfig?.imageSize,
  `${r.width}×${r.height}`, r.seconds ? `${r.seconds}s` : null].filter(Boolean).join(' · ');

// --- lazy loading, and letting go ---
const io = new IntersectionObserver((entries) => {
  for (const e of entries) {
    const img = e.target;
    if (e.isIntersecting) { if (!img.getAttribute('src')) img.src = img.dataset.src; }
    else if (img.getAttribute('src')) { img.removeAttribute('src'); img.classList.remove('in'); }
  }
}, { rootMargin: NEAR });

// --- the wall: cards go into the shortest column ---
function columns() {
  const n = Math.max(2, Math.floor(wall.clientWidth / 190));
  if (n === cols.length) return false;
  wall.replaceChildren();
  cols = Array.from({ length: n }, () => wall.appendChild(h('div', { class: 'iw-col' })));
  heights = cols.map(() => 0);
  return true;
}
function place(card, r) {
  const k = heights.indexOf(Math.min(...heights));
  cols[k].append(card);
  heights[k] += r.height / r.width + 0.55;                     // the image's height in column widths, and the caption
}

const votes = (() => { try { return JSON.parse(localStorage.getItem('images:votes')) || {}; } catch { return {}; } })();
async function vote(r, v, card) {
  votes[r.id] = votes[r.id] === v ? null : v;
  try { localStorage.setItem('images:votes', JSON.stringify(votes)); } catch { /* this visit only */ }
  haptic(); paintVote(card, r);
  if (!votes[r.id]) return;
  try {
    await fetch('/studio/api/artist/feedback', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, keepalive: true,
      body: JSON.stringify({ vote: v, view: 'images', client_ts: Date.now(),
        context: { view: 'images', image: r.id, batch: r.batch, title: r.title, model: r.model } }),
    });
  } catch { /* the vote stays marked here */ }
}
function paintVote(card, r) {
  const v = votes[r.id];
  card.classList.toggle('up', v === 'up'); card.classList.toggle('down', v === 'down');
  card.querySelector('.iw-vote.up').classList.toggle('on', v === 'up');
  card.querySelector('.iw-vote.down').classList.toggle('on', v === 'down');
}

function card(r) {
  const img = h('img', { alt: r.title || r.prompt.slice(0, 80), 'data-src': FILES + r.thumb, decoding: 'async' });
  img.addEventListener('load', () => img.classList.add('in'));
  const box = h('div', { class: 'iw-img' }, img);
  box.style.aspectRatio = `${r.width} / ${r.height}`;
  const up = h('button', { type: 'button', class: 'iw-vote up', 'aria-label': 'I like this' }, svg(THUMB));
  const down = h('button', { type: 'button', class: 'iw-vote down', 'aria-label': "I don't like this" }, svg(THUMB));
  const prompt = h('details', { class: 'iw-prompt' }, h('summary', { text: 'Prompt' }), h('p', { text: r.prompt }));
  const settings = h('details', { class: 'iw-settings' }, h('summary', { text: 'Settings' }),
    h('pre', { text: JSON.stringify({ model: r.model, ...r.settings, inputs: r.inputs?.length ? r.inputs : undefined,
      seconds: r.seconds, tokens: r.tokens?.totalTokenCount, created: r.created, id: r.id, imported: r.imported || undefined }, null, 1) }));
  const el = h('article', { class: 'iw-card', 'data-id': r.id }, box,
    h('div', { class: 'iw-cap' },
      h('div', { class: 'iw-head' }, h('b', { text: r.title || 'Untitled' }), up, down),
      h('p', { class: 'iw-batch', text: `${r.batch} · ${when(r.created)}` }),
      h('p', { class: 'iw-ctx', text: r.context }),
      h('p', { class: 'iw-set', text: settingsLine(r) }),
      prompt, settings));
  tap(box, () => open(r));
  tap(up, () => vote(r, 'up', el)); tap(down, () => vote(r, 'down', el));
  paintVote(el, r);
  io.observe(img);
  return el;
}

function open(r) {
  const body = document.getElementById('view-body');
  const img = h('img', { src: FILES + r.file, alt: r.title });
  const copy = h('button', { type: 'button', class: 'iw-copy', text: 'Copy the prompt' });
  tap(copy, async () => { try { await navigator.clipboard.writeText(r.prompt); copy.textContent = 'Copied'; } catch { copy.textContent = 'Copy failed'; } });
  body.replaceChildren(img,
    h('h2', { text: r.title || 'Untitled' }),
    h('p', { class: 'iw-batch', text: `${r.batch} · ${when(r.created)}` }),
    h('p', { class: 'iw-ctx', text: r.context }),
    h('p', { class: 'iw-set', text: settingsLine(r) }),
    h('h3', { text: 'Prompt' }), h('p', { class: 'iw-full-prompt', text: r.prompt }), copy,
    r.text ? h('h3', { text: 'The model said' }) : null, r.text ? h('p', { class: 'iw-said', text: r.text }) : null,
    h('h3', { text: 'Settings' }), h('pre', { text: JSON.stringify({ model: r.model, ...r.settings, inputs: r.inputs, tokens: r.tokens, seconds: r.seconds, id: r.id }, null, 1) }));
  view.classList.add('show'); view.setAttribute('aria-hidden', 'false');
  document.body.classList.add('locked');
  view.scrollTop = 0;
}
function close() {
  view.classList.remove('show'); view.setAttribute('aria-hidden', 'true');
  document.body.classList.remove('locked');
  document.getElementById('view-body').replaceChildren();          // let the full image go
}
tap(document.getElementById('view-x'), close);
addEventListener('keydown', (e) => { if (e.key === 'Escape') close(); });

async function next() {
  if (loading || offset >= total) return;
  loading = true;
  try {
    const q = new URLSearchParams({ offset, limit: PAGE });
    if (batch) q.set('batch', batch);
    const d = await (await fetch(`${API}?${q}`, { cache: 'no-store' })).json();
    total = d.total;
    if (offset === 0) chips(d.batches);
    for (const r of d.items) { records.push(r); place(card(r), r); }
    offset += d.items.length;
    document.getElementById('count').textContent = `${total} image${total === 1 ? '' : 's'}${batch ? ` in ${batch}` : ''}`;
    if (!total) wall.replaceChildren(h('p', { class: 'iw-empty', text: 'No images yet. They arrive here as they are made.' }));
  } catch {
    document.getElementById('count').textContent = "The wall isn't answering";
  } finally {
    loading = false;
  }
  if (offset < total && more.getBoundingClientRect().top < innerHeight * 2.5) next();
}
new IntersectionObserver((e) => { if (e[0].isIntersecting) next(); }, { rootMargin: '250% 0px' }).observe(more);

function chips(batches) {
  const nav = document.getElementById('batches');
  const all = [{ batch: null, count: batches.reduce((a, b) => a + b.count, 0) }, ...batches];
  nav.replaceChildren(...all.map((b) => {
    const c = h('button', { type: 'button', class: `iw-chip${b.batch === batch ? ' on' : ''}` }, h('span', { text: b.batch ?? 'All' }), h('i', { text: String(b.count) }));
    tap(c, () => { batch = b.batch; restart(); });
    return c;
  }));
  const ctx = batches.find((b) => b.batch === batch);
  document.getElementById('context').textContent = ctx ? ctx.context : '';
}
function restart() {
  const u = new URL(location.href);
  if (batch) u.searchParams.set('batch', batch); else u.searchParams.delete('batch');
  history.replaceState(null, '', u);
  for (const img of wall.querySelectorAll('img')) io.unobserve(img);
  offset = 0; total = Infinity; records.length = 0; cols = [];
  columns();
  scrollTo(0, 0);
  next();
}
addEventListener('resize', () => {
  if (!columns()) return;
  for (const img of wall.querySelectorAll('img')) io.unobserve(img);
  for (const r of records) place(card(r), r);
});
columns();
next();
window.__wall = { records, loaded: () => wall.querySelectorAll('img[src]').length, cards: () => wall.querySelectorAll('.iw-card').length };
