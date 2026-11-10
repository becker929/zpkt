// The crystal concept: the track's checklist as one crystal that grows a shard for each cleared item
// (crystal-draw.js draws it, deterministically). Tap an arm or a numeral for that step's items, tap a box to clear
// one; Release now (mocked) freezes the crystal as a pressing, kept in this browser.
import { drawCrystal } from './crystal-draw.js';
import {
  TRACK, current, haptic, isDone, keyOf, loadTrack, onChange, onTap, roles, setDone, studioHref, totals,
} from './model.js';

const $ = (id) => document.getElementById(id);
const PRESS_KEY = `crystal:${TRACK}:releases`;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;

let data;
let open = null;          // the step whose items are listed
let shown = null;         // the keys the live crystal last drew, to grow in only what is new

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}

const doneKeys = () => new Set(data.steps.flatMap((s) => s.items.filter((it) => isDone(s, it)).map((it) => keyOf(s, it))));

// --- the live crystal ---
function drawLive() {
  const keys = doneKeys();
  const live = $('live');
  live.innerHTML = drawCrystal(data, keys);
  if (shown && !reduced) {
    for (const k of keys) if (!shown.has(k)) live.querySelector(`.shard[data-key="${k}"]`)?.classList.add('new');
  }
  shown = keys;
  live.querySelectorAll('.arm').forEach((g) => g.classList.toggle('sel', g.dataset.step === open));
  live.querySelectorAll('.num').forEach((t) => t.classList.toggle('sel', t.dataset.step === open));
  for (const hit of live.querySelectorAll('.hit, .num')) onTap(hit, () => choose(hit.dataset.step));
  const [n, of] = totals(data);
  $('total-n').textContent = n; $('total-of').textContent = of;
}

// --- the steps and the open step's list ---
function choose(id) {
  open = open === id ? null : id;
  haptic();
  render();
  if (open) $('list').scrollIntoView({ behavior: reduced ? 'auto' : 'smooth', block: 'nearest' });
}

function drawSteps() {
  const cur = current(data);
  $('steps').replaceChildren(...data.steps.map((s) => {
    const k = s.items.filter((it) => isDone(s, it)).length;
    const b = h('button', { type: 'button', class: 'step', 'data-step': s.id, 'aria-expanded': String(open === s.id) },
      h('span', { class: 'n', text: s.n }), h('span', { class: 'k', text: `${k}/${s.items.length}` }));
    b.classList.toggle('cur', s === cur);
    b.classList.toggle('full', k === s.items.length);
    onTap(b, () => choose(s.id));
    return b;
  }));
}

const NOTE = { you: 'your move', ready: 'ready', clearing: 'the agent is on it' };
const CHECK = '<svg viewBox="0 0 20 20" aria-hidden="true"><rect class="box" x="2" y="2" width="16" height="16"/><path class="tick" d="M5.5 10.5l3 3 6-7"/></svg>';
const ARROW = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6"/></svg>';

function drawList() {
  const list = $('list');
  const step = data.steps.find((s) => s.id === open);
  if (!step) { list.replaceChildren(); list.hidden = true; return; }
  list.hidden = false;
  const r = roles(step);
  list.replaceChildren(
    h('h2', {}, h('span', { text: `${step.n}. ` }), step.name),
    h('ul', {}, step.items.map((it, i) => {
      const done = isDone(step, it);
      const box = h('button', { type: 'button', class: 'check', role: 'checkbox', 'aria-checked': String(done), 'aria-label': it.title, 'data-key': keyOf(step, it) });
      box.innerHTML = CHECK;
      onTap(box, () => { setDone(step, it, !done); haptic(!done); });
      const go = h('a', { class: 'go', href: studioHref(step, it), 'aria-label': `${it.title}: work on it in studio` });
      go.innerHTML = ARROW;
      onTap(go, () => { location.href = go.href; });
      const note = NOTE[r[i]] ?? (it.gate && !done ? 'a decision' : '');
      return h('li', { class: done ? 'done' : '' }, box,
        h('span', { class: 'ttl' }, it.title, note ? h('em', { text: ` · ${note}` }) : null), go);
    })));
}

// --- releases: frozen pressings of the crystal ---
function pressings() { try { return JSON.parse(localStorage.getItem(PRESS_KEY)) || []; } catch { return []; } }
function keep(list) { try { localStorage.setItem(PRESS_KEY, JSON.stringify(list)); } catch { /* this visit only */ } }

function release() {
  const [n, of] = totals(data);
  const list = pressings();
  list.unshift({ at: new Date().toISOString(), n, of, svg: drawCrystal(data, doneKeys()) });
  keep(list);
  haptic(true);
  drawPressings(true);
}

function drawPressings(fresh = false) {
  const list = pressings();
  $('pressings-h').hidden = !list.length;
  const fmt = new Intl.DateTimeFormat(undefined, { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });
  $('pressings').replaceChildren(...list.map((p, i) => {
    const art = h('div', { class: 'art' });
    art.innerHTML = p.svg;                      // frozen: drawn once at release, never redrawn
    const li = h('li', { class: 'pressing' }, art,
      h('span', { class: 'when', text: fmt.format(new Date(p.at)) }), h('span', { class: 'of', text: `${p.n}/${p.of}` }));
    if (fresh && i === 0 && !reduced) li.classList.add('pressed');
    return li;
  }));
}

function render() { drawLive(); drawSteps(); drawList(); }

onTap($('release'), release);
onChange(() => { if (data) render(); });
loadTrack()
  .then((d) => {
    data = d;
    $('track').textContent = d.track; $('about').textContent = d.about;
    document.title = `${d.track} Crystal`;
    render(); drawPressings();
  })
  .catch((err) => { $('live').append(h('p', { class: 'err', text: String(err.message || err) })); });
