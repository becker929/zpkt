// The gallery (docs/artist-agent.md): every commit hangs a plate, the work that played, the map at that moment, the
// item settled and, where there is one, the render approved. Wings by track, rooms by step, plates in the order they
// were made; the repertoire's works not yet seen hang at the end as silhouettes, their titles hidden. A plate opens
// full bleed with its render to play (as rendered: decoded and started, nothing made in the browser, docs/sound.md),
// the batch's other renders, and what it unlocked out in The Wasteland. The plates and the repertoire come from the
// harness (/studio/api/artist/); renders come through its site-audio route, which copies them from the site once.
import { haptic, loadTrack, onTap, TRACK } from '../concepts/model.js';
import { render } from './world.js';
import { CACHES, FINDS, KINDS } from './finds.js';
import { SOUNDS } from './sounds.js';
import { mountFeedback } from './feedback.js';

const API = '/studio/api/artist/';
const AUDIO = '/studio/site-audio/';
const $ = (id) => document.getElementById(id);
const SVGNS = 'http://www.w3.org/2000/svg';

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
function icon(d, cls = '') {
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('viewBox', '0 0 24 24'); svg.setAttribute('aria-hidden', 'true');
  if (cls) svg.setAttribute('class', cls);
  const p = document.createElementNS(SVGNS, 'path'); p.setAttribute('d', d);
  svg.append(p);
  return svg;
}
const PLAY = 'M8 5.5v13l11-6.5z';
const STOP = 'M7 7h10v10H7z';
const CLOSE = 'M15 5l-7 7 7 7';

async function getJSON(url) {
  const r = await fetch(url, { cache: 'no-store' });
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

let data = null, plates = [], works = [], version = null, renders = { items: {} };
let openPlate = null, inView = null;

const itemId = (p) => (String(p.item).includes('.') ? String(p.item).split('.').pop() : String(p.item));
const stepOf = (p) => data.steps.find((s) => s.id === p.step);
const itemOf = (p) => stepOf(p)?.items.find((it) => it.id === itemId(p));
const workOf = (p) => works.find((w) => w.id === p.work?.id);
const workTitle = (p) => p.work?.title ?? workOf(p)?.title ?? 'A work';
const soundLabel = (id) => SOUNDS.find((s) => s.id === id)?.label ?? id ?? '';
const rendersOf = (p) => renders.items?.[`${p.track ?? TRACK}.${p.step}.${itemId(p)}`] ?? [];
function when(p) {
  const d = new Date((p.at ?? p.client_ts / 1000) * 1000);
  const mon = d.toLocaleString('en-GB', { month: 'short' });
  return `${d.getDate()} ${mon} ${d.getFullYear()} · ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}
const unlockedOf = (p) => (p.unlocked ?? []).map((k) => FINDS[k] ?? CACHES[k]).filter(Boolean);

// --- the player: one context (made on the first tap, as iOS requires), one render at a time ---
let ctx = null;
const buffers = new Map();
let playing = null;                 // { src, path, holder, raf }
function decoded(path) {
  if (!buffers.has(path)) {
    buffers.set(path, fetch(AUDIO + path)
      .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`${r.status}`))))
      .then((b) => ctx.decodeAudioData(b))
      .catch((e) => { buffers.delete(path); throw e; }));
  }
  return buffers.get(path);
}
function stop() {
  if (!playing) return;
  const { src, holder, raf } = playing;
  playing = null;
  cancelAnimationFrame(raf);
  try { src.stop(); } catch { /* already ended */ }
  holder.classList.remove('playing');
  holder.style.setProperty('--p', '0');
  const b = holder.querySelector('.gl-pbtn');
  b?.replaceChildren(icon(PLAY));
  b?.setAttribute('aria-label', `Play ${holder.dataset.label ?? 'the render'}`);
}
async function toggle(path, holder) {
  const same = playing && playing.path === path && playing.holder === holder;
  stop();
  if (same) return;
  haptic();
  try {
    ctx ??= new AudioContext();
    if (ctx.state === 'suspended') ctx.resume();
  } catch { holder.classList.add('failed'); return; }
  holder.classList.add('loading');
  let buf;
  try { buf = await decoded(path); } catch { holder.classList.remove('loading'); holder.classList.add('failed'); return; }
  holder.classList.remove('loading', 'failed');
  if (playing) stop();
  const src = ctx.createBufferSource();
  src.buffer = buf;
  src.connect(ctx.destination);
  const t0 = ctx.currentTime + 0.02;
  src.start(t0);
  const me = { src, path, holder, raf: 0 };
  playing = me;
  holder.classList.add('playing');
  const b = holder.querySelector('.gl-pbtn');
  b?.replaceChildren(icon(STOP));
  b?.setAttribute('aria-label', 'Stop');
  const step = () => {
    if (playing !== me) return;
    holder.style.setProperty('--p', Math.min(1, Math.max(0, (ctx.currentTime - t0) / buf.duration)).toFixed(4));
    me.raf = requestAnimationFrame(step);
  };
  me.raf = requestAnimationFrame(step);
  src.onended = () => { if (playing === me) stop(); src.disconnect(); };
}
function player(r, { big = false } = {}) {
  if (!r) return h('p', { class: 'gl-norender', text: 'No render yet' });
  const holder = h('div', { class: `gl-player${big ? ' big' : ''}`, 'data-path': r.path, 'data-label': r.label });
  const b = h('button', { type: 'button', class: 'gl-pbtn', 'aria-label': `Play ${r.label}` }, icon(PLAY));
  holder.append(b, h('div', { class: 'gl-pmeta' }, h('span', { class: 'gl-plabel', text: r.label }), h('i', { class: 'gl-line' })));
  onTap(b, (e) => { e?.stopPropagation?.(); toggle(r.path, holder); });
  return holder;
}

// --- the walls ---
const drawn = new IntersectionObserver((entries) => {
  for (const e of entries) {
    if (!e.isIntersecting) continue;
    const el = e.target;
    drawn.unobserve(el);
    const p = plates.find((x) => x.id === el.dataset.plate);
    if (p) el.innerHTML = render(data, new Set(p.done ?? []), { id: `pl-${p.n}`, fresh: new Set(p.unlocked ?? []), lamps: p.lamps ?? {}, sky: p.work?.params?.sky ?? 'none' });
  }
}, { rootMargin: '600px 0px' });
const seen = new IntersectionObserver((entries) => {
  for (const e of entries) if (e.isIntersecting) inView = e.target.dataset.plate;
}, { threshold: 0.6 });

function plateCard(p) {
  const map = h('div', { class: 'gl-map', 'data-plate': p.id, 'aria-hidden': 'true' });
  const frame = h('button', { type: 'button', class: 'gl-frame', 'aria-label': `Open plate ${p.n}: ${workTitle(p)}` }, map);
  const card = h('article', { class: 'gl-plate', 'data-plate': p.id, 'data-n': p.n },
    frame,
    h('div', { class: 'gl-cap' },
      h('b', { class: 'gl-no', text: `Plate ${p.n}` }),
      h('span', { class: 'gl-work', text: workTitle(p) }),
      h('span', { class: 'gl-item', text: p.title ?? itemOf(p)?.title ?? p.item }),
      h('time', { class: 'gl-when', text: when(p) }),
      p.sound ? h('span', { class: 'gl-sound', text: `Sound · ${soundLabel(p.sound)}` }) : null),
    player(p.render));
  onTap(frame, () => openUp(p));
  drawn.observe(map);
  seen.observe(card);
  return card;
}

function dropCap(text, cls = '') {
  return h('span', { class: `gl-cap-letter ${cls}`, 'aria-hidden': 'true' }, text);
}

function draw() {
  const halls = $('halls');
  const ids = new Set(works.map((w) => w.id));
  const seenWorks = new Set(plates.map((p) => p.work?.id).filter((id) => ids.has(id)));
  $('counts').textContent = `${plates.length} plate${plates.length === 1 ? '' : 's'} · ${seenWorks.size} work${seenWorks.size === 1 ? '' : 's'} seen of ${works.length}`;
  const name = String(data.track ?? TRACK);
  const wing = h('section', { class: 'gl-wing', 'data-track': TRACK },
    h('header', { class: 'gl-wing-head' },
      h('span', { class: 'gl-initial', 'aria-hidden': 'true' }, name.slice(0, 1), ornament()),
      h('div', { class: 'gl-wing-title' },
        h('p', { class: 'gl-wing-kicker', text: 'Wing I' }),
        h('h2', {}, h('span', { class: 'gl-sr' }, name.slice(0, 1)), name.slice(1)),
        h('p', { class: 'gl-wing-sub', text: `${plates.length} plate${plates.length === 1 ? '' : 's'} hung` }))));
  for (const step of data.steps) {
    const mine = plates.filter((p) => p.step === step.id);
    const room = h('section', { class: `gl-room${mine.length ? '' : ' empty'}`, 'data-step': step.id },
      h('header', { class: 'gl-room-head' }, dropCap(step.n),
        h('div', {}, h('h3', { text: step.name }),
          h('p', { text: mine.length ? `${mine.length} plate${mine.length === 1 ? '' : 's'}` : 'No plates yet' }))));
    if (mine.length) room.append(h('div', { class: 'gl-wall' }, mine.map(plateCard)));
    wing.append(room);
  }
  const unseen = works.filter((w) => !seenWorks.has(w.id));
  if (unseen.length) {
    wing.append(h('section', { class: 'gl-room gl-unseen' },
      h('header', { class: 'gl-room-head' }, dropCap('?', 'quiet'),
        h('div', {}, h('h3', { text: 'Not yet seen' }),
          h('p', { text: `${unseen.length} work${unseen.length === 1 ? '' : 's'} the artist has made` }))),
      h('div', { class: 'gl-wall' }, unseen.map(() => h('article', { class: 'gl-silhouette' },
        h('div', { class: 'gl-frame quiet' }, h('div', { class: 'gl-shade' }, shade())),
        h('div', { class: 'gl-cap' }, h('b', { class: 'gl-no', text: 'Not yet seen' }),
          h('span', { class: 'gl-item', text: 'A work the artist made' })))))));
  }
  halls.replaceChildren(wing);
}

/** The initial's corner flourish: a vine and a leaf, drawn once in gold. */
function ornament() {
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('viewBox', '0 0 64 64'); svg.setAttribute('class', 'gl-orn'); svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = '<path d="M4 60C4 30 18 12 46 6" /><path d="M14 40c8-2 12-8 12-16-7 2-12 8-12 16z" /><path d="M28 20c7 1 12-2 15-8-7-1-12 2-15 8z" />'
    + '<circle cx="50" cy="6" r="2.4" /><circle cx="6" cy="58" r="2.4" />';
  return svg;
}
/** A silhouette's shade: the outline of something hung, its face turned away. */
function shade() {
  const svg = document.createElementNS(SVGNS, 'svg');
  svg.setAttribute('viewBox', '0 0 100 84'); svg.setAttribute('aria-hidden', 'true');
  svg.innerHTML = '<rect x="10" y="10" width="80" height="64" rx="3" /><path d="M50 22l14 20-14 20-14-20z" />';
  return svg;
}

// --- a plate, open ---
function openUp(p) {
  haptic();
  openPlate = p;
  const host = $('open');
  const w = workOf(p);
  const others = rendersOf(p).filter((r) => r.path !== p.render?.path);
  const found = unlockedOf(p);
  const close = h('button', { type: 'button', class: 'gl-close', 'aria-label': 'Back to the gallery' }, icon(CLOSE));
  const map = h('div', { class: 'gl-bigmap' });
  map.innerHTML = render(data, new Set(p.done ?? []), { id: `plo-${p.n}`, fresh: new Set(p.unlocked ?? []), lamps: p.lamps ?? {}, sky: p.work?.params?.sky ?? 'none' });
  host.replaceChildren(h('article', { class: 'gl-o', 'data-plate': p.id },
    h('header', { class: 'gl-o-top' }, close,
      h('div', {}, h('b', { text: `Plate ${p.n}` }), h('span', { text: when(p) }))),
    h('div', { class: 'gl-o-body' },
      h('div', { class: 'gl-o-frame' }, map),
      h('p', { class: 'gl-o-kicker', text: `${stepOf(p)?.n ?? ''} ${p.step_name ?? stepOf(p)?.name ?? ''}`.trim() }),
      h('h2', { class: 'gl-o-item', text: p.title ?? itemOf(p)?.title ?? p.item }),
      h('section', { class: 'gl-o-work' },
        h('p', { class: 'gl-o-label', text: 'The work' }),
        h('h3', { text: workTitle(p) }),
        h('p', { class: 'gl-o-about', text: w?.about ?? `From the artist's repertoire, version ${p.work?.version ?? '?'}.` }),
        p.sound ? h('p', { class: 'gl-o-sound', text: `Sound · ${soundLabel(p.sound)}` }) : null),
      h('section', { class: 'gl-o-render' },
        h('p', { class: 'gl-o-label', text: 'The render' }),
        player(p.render, { big: true }),
        others.length ? h('div', { class: 'gl-o-others' },
          h('p', { class: 'gl-o-label', text: 'The rest of the batch' }),
          others.map((r) => player(r))) : null),
      found.length ? h('section', { class: 'gl-o-found' },
        h('p', { class: 'gl-o-label', text: 'Unlocked in The Wasteland' }),
        h('ul', {}, found.map((f) => h('li', {},
          h('i', { text: f.cache ? 'Cache' : (KINDS[f.kind]?.label ?? '') }), h('span', { text: f.title }))))) : null)));
  host.classList.add('show'); host.setAttribute('aria-hidden', 'false');
  document.body.classList.add('locked');
  onTap(close, shut);
}
function shut() {
  stop();
  openPlate = null;
  const host = $('open');
  host.classList.remove('show'); host.setAttribute('aria-hidden', 'true');
  host.replaceChildren();
  document.body.classList.remove('locked');
}

function down() {
  $('counts').textContent = 'The doors are shut';
  const retry = h('button', { type: 'button', class: 'gl-retry', text: 'Try again' });
  $('halls').replaceChildren(h('div', { class: 'gl-down', role: 'status' },
    h('p', { class: 'gl-down-head', text: "The gallery's store isn't answering." }),
    h('p', { text: 'The plates are kept by the harness on the Mac. Nothing is lost; try again in a moment.' }),
    retry));
  onTap(retry, () => { haptic(); boot(); });
}

async function boot() {
  try { data ??= await loadTrack(); } catch (err) { $('halls').replaceChildren(h('p', { text: String(err.message || err) })); return; }
  renders = await getJSON('renders.json').catch(() => ({ items: {} }));
  try {
    plates = (await getJSON(`${API}plates?track=${encodeURIComponent(TRACK)}`)).items ?? [];
  } catch { down(); return; }
  plates.sort((a, b) => (a.n ?? 0) - (b.n ?? 0));
  let rep;
  try { rep = await getJSON(`${API}repertoire`); } catch { rep = await getJSON('works.json').catch(() => ({ works: [] })); }
  works = rep.works ?? [];
  version = rep.version ?? null;
  draw();
}

mountFeedback({
  context: () => {
    const p = openPlate ?? plates.find((x) => x.id === inView) ?? null;
    return { view: 'gallery', plate: p?.id ?? null, open: !!openPlate, work: p ? `${p.work?.id}@${p.work?.version}` : null,
      repertoire: version, playing: playing?.path ?? null };
  },
});
boot();
