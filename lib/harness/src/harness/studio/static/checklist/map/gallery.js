// The gallery (docs/artist-agent.md): every commit hangs a plate, the work that played, the map at that moment, the
// item settled and, where there is one, the render approved. A wing per track, the one with the newest plate first.
// The checklist's track (HW002): rooms by step, plates in the order they were made; the repertoire's works not yet
// seen hang at the end as silhouettes, their titles hidden. A plate opens full bleed with its render to play (as
// rendered: decoded and started, nothing made in the browser, docs/sound.md), the batch's other renders, and what it
// unlocked out in The Wasteland. A short's wing (SH001, finished in The Rummage, docs/rummage.md): the record sleeves
// of the shorts as made hang side by side, newest first, each with its three choices, its date and its render to
// play. One render plays at a time. #<track> in the address goes to that wing and lights its newest plate; ?from=
// (wasteland, rummage) points the back link at where you came in. The plates and the repertoire come from the harness
// (/studio/api/artist/); the checklist's renders come through its site-audio route, which copies them from the site
// once, and a short's from its region's audio route.
import { haptic, loadTrack, onTap, TRACK } from '../concepts/model.js';
import { render } from './world.js';
import { CACHES, FINDS, KINDS } from './finds.js';
import { SOUNDS } from './sounds.js';
import { mountFeedback } from './feedback.js';

const API = '/studio/api/artist/';
const AUDIO = '/studio/site-audio/';
// The shorts: tracks finished in a region of their own, hung as record sleeves.
const SHORTS = {
  sh001: { title: 'SH001 · The Rummage', region: '../rummage/', art: '../rummage/art/', banner: '../rummage/art/title.webp',
           audio: '../rummage/audio.json', renders: '/studio/regions/rummage/audio/' },
};
const PARTS = [['bed', 'Bed'], ['drums', 'Drums'], ['bass', 'Bass']];
const ROMAN = ['', 'I', 'II', 'III'];
// Where the back link goes, by where you came in from (?from=)
const BACK = {
  wasteland: { href: '../wasteland/?from=museum', label: 'Back out to The Wasteland' },
  rummage: { href: '../rummage/', label: 'Back to The Rummage' },
};
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
const shortParts = {};                 // track -> its audio.json's parts, for a choice whose name the plate lacks
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
const buffers = new Map();          // url -> Promise<AudioBuffer>; the last few only (a short is ~20 MB decoded)
const KEEP = 3;
let playing = null;                 // { src, path (its url), holder, raf }
function decoded(url) {
  let got = buffers.get(url);
  if (got) { buffers.delete(url); buffers.set(url, got); return got; }        // most recent goes last
  got = fetch(url)
    .then((r) => (r.ok ? r.arrayBuffer() : Promise.reject(new Error(`${r.status}`))))
    .then((b) => ctx.decodeAudioData(b))
    .catch((e) => { buffers.delete(url); throw e; });
  buffers.set(url, got);
  for (const key of buffers.keys()) if (buffers.size > KEEP && key !== url && key !== playing?.path) buffers.delete(key);
  return got;
}
function stop() {
  if (!playing) return;
  const { src, holder, raf } = playing;
  playing = null;
  cancelAnimationFrame(raf);
  try { src.stop(); } catch { /* already ended */ }
  holder.classList.remove('playing');
  holder.closest('.gl-short')?.classList.remove('playing');
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
  holder.closest('.gl-short')?.classList.add('playing');
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
/** A render's play control: `r.url` where it is served, else `r.path` on the site (through site-audio). */
function player(r, { big = false } = {}) {
  const url = r?.url ?? (r?.path ? AUDIO + r.path : null);
  if (!url) return h('p', { class: 'gl-norender', text: 'No render yet' });
  const holder = h('div', { class: `gl-player${big ? ' big' : ''}`, 'data-path': r.path ?? url, 'data-label': r.label });
  const b = h('button', { type: 'button', class: 'gl-pbtn', 'aria-label': `Play ${r.label}` }, icon(PLAY));
  holder.append(b, h('div', { class: 'gl-pmeta' }, h('span', { class: 'gl-plabel', text: r.label }), h('i', { class: 'gl-line' })));
  holder.toggle = () => toggle(url, holder);
  onTap(b, (e) => { e?.stopPropagation?.(); holder.toggle(); });
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
  const card = h('article', { class: 'gl-plate', 'data-plate': p.id, 'data-n': p.n, 'data-at': p.at ?? 0 },
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

const trackOf = (p) => String(p.track ?? TRACK);
const latest = (list) => list.reduce((m, p) => Math.max(m, p.at ?? 0), -1);
const ROMAN_WING = ['I', 'II', 'III', 'IV', 'V', 'VI', 'VII', 'VIII', 'IX', 'X'];

/** Every track's wing, the one with the newest plate first (an empty wing last). */
function draw() {
  const halls = $('halls');
  const ids = new Set(works.map((w) => w.id));
  const seenWorks = new Set(plates.map((p) => p.work?.id).filter((id) => ids.has(id)));
  $('counts').textContent = `${plates.length} plate${plates.length === 1 ? '' : 's'} · ${seenWorks.size} work${seenWorks.size === 1 ? '' : 's'} seen of ${works.length}`;
  const tracks = new Set([TRACK, ...Object.keys(SHORTS), ...plates.map(trackOf)]);
  const wings = [...tracks].map((track) => {
    const mine = plates.filter((p) => trackOf(p) === track);
    const build = track === TRACK ? trackWing
      : SHORTS[track] || mine.some((p) => p.sleeve || p.item === 'short') ? shortsWing : plainWing;
    return { track, at: latest(mine), build, mine };
  }).sort((a, b) => b.at - a.at);
  halls.replaceChildren(...wings.map((w, i) => w.build(w.track, w.mine, `Wing ${ROMAN_WING[i] ?? i + 1}`)));
  lightUp();
}

/** The checklist's track: rooms by step, the map at each commit, the works not yet seen. */
function trackWing(track, list, kicker) {
  const name = String(data.track ?? track);
  const wing = h('section', { class: 'gl-wing', 'data-track': track, id: track },
    h('header', { class: 'gl-wing-head' },
      h('span', { class: 'gl-initial', 'aria-hidden': 'true' }, name.slice(0, 1), ornament()),
      h('div', { class: 'gl-wing-title' },
        h('p', { class: 'gl-wing-kicker', text: kicker }),
        h('h2', {}, h('span', { class: 'gl-sr' }, name.slice(0, 1)), name.slice(1)),
        h('p', { class: 'gl-wing-sub', text: `${list.length} plate${list.length === 1 ? '' : 's'} hung` }))));
  const ids = new Set(works.map((w) => w.id));
  const seenWorks = new Set(list.map((p) => p.work?.id).filter((id) => ids.has(id)));
  for (const step of data.steps) {
    const mine = list.filter((p) => p.step === step.id);
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
  return wing;
}

/** A short's wing: the title art for a banner, the record sleeves of the shorts as made, newest first. */
function shortsWing(track, list, kicker) {
  const meta = SHORTS[track] ?? { title: track.toUpperCase(), region: null, art: '', banner: null, renders: '' };
  const newest = [...list].sort((a, b) => (b.at ?? 0) - (a.at ?? 0) || (b.n ?? 0) - (a.n ?? 0));
  const banner = meta.banner
    ? h('figure', { class: 'gl-banner' }, h('img', { src: meta.banner, alt: meta.title.split(' · ').pop(), decoding: 'async' }))
    : null;
  const go = meta.region ? h('a', { class: 'gl-go', href: meta.region, text: 'Walk there' }) : null;
  if (go) onTap(go, () => { location.href = go.href; });
  const wing = h('section', { class: 'gl-wing gl-shorts', 'data-track': track, id: track },
    h('header', { class: 'gl-short-head' },
      h('p', { class: 'gl-wing-kicker', text: `${kicker} · Shorts` }),
      banner,
      h('h2', { text: meta.title }),
      h('p', { class: 'gl-wing-sub' },
        list.length ? `${list.length} short${list.length === 1 ? '' : 's'} hung, newest first · ` : 'No shorts hung yet · ', go)));
  if (!list.length) {
    wing.append(h('p', { class: 'gl-shorts-none', text: 'Finish the short in its region: operate the three machines and '
      + 'bring what they make to the Gramophone. Its record sleeve hangs here.' }));
    return wing;
  }
  wing.append(h('div', { class: 'gl-shelf', role: 'list' }, newest.map((p) => shortCard(p, meta))));
  return wing;
}

function choiceName(p, part) {
  const c = p.choices?.[part];
  const id = c?.id ?? (Number(String(p.combo ?? '').split('-')[PARTS.findIndex(([x]) => x === part)]) || null);
  return c?.name ?? shortParts[trackOf(p)]?.[part]?.find((o) => o.id === id)?.name ?? (id ? `Option ${ROMAN[id] ?? id}` : '-');
}

function shortCard(p, meta) {
  const r = p.render ? { ...p.render, url: p.render.url ?? (p.render.path ? meta.renders + p.render.path : null) } : null;
  const ctl = player(r && { ...r, label: r.label ?? meta.title });
  const name = meta.title.split(' · ')[0];
  const face = p.sleeve
    ? h('img', { src: meta.art + p.sleeve, alt: `The record sleeve of ${name}, ${p.combo ?? ''}`, decoding: 'async' })
    : h('span', { class: 'gl-sleeve-none', 'aria-hidden': 'true' }, h('b', { text: name }));
  const sleeve = h('button', { type: 'button', class: 'gl-sleeve', 'aria-label': `Play ${name} as made: ${p.combo ?? ''}` }, face);
  const card = h('article', { class: 'gl-short', role: 'listitem', 'data-plate': p.id, 'data-n': p.n, 'data-combo': p.combo ?? '',
    'data-at': p.at ?? 0 },
  h('div', { class: 'gl-record' }, h('i', { class: 'gl-disc', 'aria-hidden': 'true' }), sleeve),
  h('div', { class: 'gl-cap' },
    h('b', { class: 'gl-no', text: `Plate ${p.n}` }),
    h('ul', { class: 'gl-choices' }, PARTS.map(([part, label]) => h('li', { 'data-part': part },
      h('i', { text: label }), h('span', { text: choiceName(p, part) })))),
    h('time', { class: 'gl-when', text: when(p) })),
  ctl);
  onTap(sleeve, () => ctl.toggle?.());
  seen.observe(card);
  return card;
}

/** Any other track: its plates, captioned, with their renders. */
function plainWing(track, list, kicker) {
  return h('section', { class: 'gl-wing', 'data-track': track, id: track },
    h('header', { class: 'gl-wing-head' },
      h('span', { class: 'gl-initial', 'aria-hidden': 'true' }, track.slice(0, 1).toUpperCase(), ornament()),
      h('div', { class: 'gl-wing-title' }, h('p', { class: 'gl-wing-kicker', text: kicker }), h('h2', { text: track.toUpperCase() }),
        h('p', { class: 'gl-wing-sub', text: `${list.length} plate${list.length === 1 ? '' : 's'} hung` }))),
    h('div', { class: 'gl-wall' }, list.map((p) => h('article', { class: 'gl-plate plain', 'data-plate': p.id, 'data-n': p.n },
      h('div', { class: 'gl-cap' }, h('b', { class: 'gl-no', text: `Plate ${p.n}` }), h('span', { class: 'gl-work', text: p.title ?? p.item ?? '' }),
        h('time', { class: 'gl-when', text: when(p) })), player(p.render)))));
}

/** #<track>: go to that wing and light its newest plate. */
function lightUp() {
  const id = decodeURIComponent(location.hash.slice(1));
  const wing = id && [...document.querySelectorAll('.gl-wing')].find((w) => w.dataset.track === id);
  if (!wing) return;
  const items = [...wing.querySelectorAll('.gl-short, .gl-plate')];
  const newest = items.sort((a, b) => Number(b.dataset.at ?? 0) - Number(a.dataset.at ?? 0) || Number(b.dataset.n) - Number(a.dataset.n))[0];
  wing.scrollIntoView({ block: 'start' });
  if (!newest) return;
  newest.classList.remove('lit'); void newest.offsetWidth; newest.classList.add('lit');
  const shelf = newest.closest('.gl-shelf');
  if (shelf) shelf.scrollLeft = newest.offsetLeft - shelf.offsetLeft - 20;
}
addEventListener('hashchange', lightUp);

/** ?from=wasteland | rummage: the back link goes back out there. */
function backLink() {
  const back = BACK[new URLSearchParams(location.search).get('from')];
  if (!back) return;
  for (const a of document.querySelectorAll('.gl-back, .gl-foot a')) {
    a.href = back.href;
    if (a.classList.contains('gl-back')) a.setAttribute('aria-label', back.label); else a.textContent = back.label;
  }
}
backLink();

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
    plates = (await getJSON(`${API}plates`)).items ?? [];                // every track's
  } catch { down(); return; }
  plates.sort((a, b) => (a.n ?? 0) - (b.n ?? 0));
  await Promise.all(Object.entries(SHORTS).filter(([t]) => plates.some((p) => trackOf(p) === t)).map(([t, m]) =>
    getJSON(m.audio).then((a) => { shortParts[t] = a.parts ?? {}; }, () => {})));
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
