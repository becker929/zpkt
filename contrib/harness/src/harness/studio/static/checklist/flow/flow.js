// The flow mock-up: a (fake) production step, the checklist and the juice object, one after another. Tap an item:
// its production widget takes the whole screen (widgets.js). Commit there and the widget folds back into the item's
// row, the box checks with its own juice (a ghost check slams down from big to small, a white silhouette flashes
// from under the box, the screen shakes, a click), then the juice object comes over the screen in a splash and
// plays the change (juice/*.js), and settles into the header as the track's progress. Tapping a box straight away
// commits too. Nothing is locked. Checks are the checklist's own (../concepts/model.js).
import {
  current, haptic, isDone, keyOf, loadTrack, onTap, resetAll, roles, setDone, totals,
} from '../concepts/model.js';
import { openWidget } from './widgets.js';
import * as crystal from './juice/crystal.js';
import * as repair from './juice/repair.js';
import * as map from './juice/map.js';
import { click, setSound, soundOn, wake } from './sound.js';

const JUICE = { crystal, repair, map };
const KIND_KEY = 'flow:juice';
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const ROLE = { you: 'Your move', ready: 'Ready: the agent cleared the way (mocked)', clearing: 'The agent is on it (mocked)' };

function h(tag, attrs = {}, ...kids) {
  const el = ['svg', 'path'].includes(tag) ? document.createElementNS('http://www.w3.org/2000/svg', tag) : document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.setAttribute('class', v);
    else if (k === 'text') el.textContent = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}
const CHECK = () => h('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, h('path', { d: 'M4.5 12.5l5 5L19.5 7' }));
const CHEVRON = () => h('svg', { viewBox: '0 0 24 24', 'aria-hidden': 'true' }, h('path', { d: 'M9 5l7 7-7 7' }));

let data;
let kind = (() => { try { return localStorage.getItem(KIND_KEY) || 'crystal'; } catch { return 'crystal'; } })();
if (!JUICE[kind]) kind = 'crystal';
const opened = new Set();
let busy = false;

const doneKeys = () => new Set(data.steps.flatMap((s) => s.items.filter((it) => isDone(s, it)).map((it) => keyOf(s, it))));

// --- the checklist ---
function render() {
  const main = $('steps');
  main.replaceChildren(...data.steps.map((step) => {
    const head = h('button', { type: 'button', class: 'step-head', 'aria-expanded': 'false' },
      h('span', { class: 'n', text: step.n }), h('span', { class: 'name', text: step.name }),
      h('span', { class: 'count' }), CHEVRON());
    const list = h('ol', { class: 'items' }, step.items.map((it) => {
      const box = h('button', { type: 'button', class: 'box', 'aria-label': `Check: ${it.title}` }, h('i'), CHECK());
      const open = h('button', { type: 'button', class: 'open-item' }, h('span', { class: 't', text: it.title }), h('span', { class: 'r' }));
      const go = h('span', { class: 'go', 'aria-hidden': 'true' }, CHEVRON());
      const li = h('li', { class: 'item', 'data-key': keyOf(step, it) }, box, open, go);
      onTap(box, () => { wake(); if (!busy) (isDone(step, it) ? uncheck(step, it) : commit(step, it, null)); });
      onTap(open, () => { wake(); if (!busy) work(step, it); });
      onTap(go, () => { wake(); if (!busy) work(step, it); });
      return li;
    }));
    const sec = h('section', { class: 'step', 'data-step': step.id }, head, list);
    onTap(head, () => { opened.has(step.id) ? opened.delete(step.id) : opened.add(step.id); haptic(); paint(); });
    return sec;
  }));
  paint();
}

function paint() {
  for (const step of data.steps) {
    const sec = document.querySelector(`.step[data-step='${step.id}']`);
    const r = roles(step);
    const n = step.items.filter((it) => isDone(step, it)).length;
    sec.classList.toggle('open', opened.has(step.id));
    sec.querySelector('.step-head').setAttribute('aria-expanded', String(opened.has(step.id)));
    sec.querySelector('.count').textContent = `${n}/${step.items.length}`;
    step.items.forEach((it, i) => {
      const li = sec.querySelector(`.item[data-key='${keyOf(step, it)}']`);
      li.classList.toggle('done', isDone(step, it));
      li.dataset.role = r[i];
      li.querySelector('.r').textContent = ROLE[r[i]] ?? (it.gate && !isDone(step, it) ? 'A decision' : '');
    });
  }
  const [n, of] = totals(data);
  $('total-n').textContent = n; $('total-of').textContent = of;
}

const mini = () => JUICE[kind].mini($('mini'), data, doneKeys());

function kinds() {
  const seg = $('kind');
  seg.replaceChildren(...Object.entries(JUICE).map(([k, mod]) => {
    const b = h('button', { type: 'button', role: 'radio', 'data-v': k, text: mod.label, 'aria-checked': String(k === kind) });
    onTap(b, () => {
      kind = k; try { localStorage.setItem(KIND_KEY, k); } catch { /* this visit only */ }
      for (const x of seg.children) x.setAttribute('aria-checked', String(x.dataset.v === k));
      haptic(); mini();
    });
    return b;
  }));
  const snd = $('snd');
  snd.setAttribute('aria-pressed', String(soundOn()));
  onTap(snd, () => { const on = !soundOn(); setSound(on); snd.setAttribute('aria-pressed', String(on)); if (on) { wake(); click(); } haptic(); });
}

// --- the production widget: full bleed ---
let widget = null;
function work(step, it) {
  const host = $('widget');
  const row = rowOf(step, it);
  host.replaceChildren();
  host.classList.add('show'); host.setAttribute('aria-hidden', 'false');
  document.body.classList.add('locked');
  haptic();
  if (!reduced) {
    const r = row.getBoundingClientRect();
    host.animate([
      { clipPath: `inset(${r.top}px 0 ${innerHeight - r.bottom}px 0)`, opacity: 0.6 },
      { clipPath: 'inset(0 0 0 0)', opacity: 1 },
    ], { duration: 340, easing: 'cubic-bezier(.2,.8,.2,1)' });
  }
  widget = openWidget(host, {
    data, step, item: it, haptic,
    commit: () => { wake(); commit(step, it, host); },
    close: () => closeWidget(step, it),
  });
}

async function closeWidget(step, it, quick = false) {
  const host = $('widget');
  if (!host.classList.contains('show')) return;
  const row = rowOf(step, it);
  if (!reduced && !quick) {
    const r = row.getBoundingClientRect();
    await host.animate([
      { clipPath: 'inset(0 0 0 0)', opacity: 1 },
      { clipPath: `inset(${r.top}px 0 ${innerHeight - r.bottom}px 0)`, opacity: 0.4 },
    ], { duration: 300, easing: 'cubic-bezier(.5,0,.2,1)' }).finished;
  }
  widget?.destroy?.(); widget = null;
  host.classList.remove('show'); host.setAttribute('aria-hidden', 'true');
  host.replaceChildren();
  document.body.classList.remove('locked');
}

const rowOf = (step, it) => document.querySelector(`.item[data-key='${keyOf(step, it)}']`);

// --- the commit: the check's juice, then the splash ---
async function commit(step, it, fromWidget) {
  if (busy) return;
  busy = true;
  try {
    opened.add(step.id); paint();
    const row = rowOf(step, it);
    const r0 = row.getBoundingClientRect();
    if (r0.top < 80 || r0.bottom > innerHeight - 40) row.scrollIntoView({ block: 'center' });
    if (fromWidget) await closeWidget(step, it);
    const before = doneKeys();
    await checkJuice(row, step);
    setDone(step, it, true);
    paint();
    const after = doneKeys();
    await sleep(reduced ? 0 : 260);
    await splash(step, it, before, after, row);
  } finally { busy = false; }
}

function uncheck(step, it) {
  setDone(step, it, false);
  haptic();
  paint(); mini();
}

async function checkJuice(row, step) {
  const box = row.querySelector('.box i');
  const b = box.getBoundingClientRect();
  const cx = b.left + b.width / 2, cy = b.top + b.height / 2;
  const fx = $('fx');
  const finishes = step.items.filter((x) => !isDone(step, x)).length === 1;
  if (reduced) { row.classList.add('done'); click(finishes); haptic(true); return; }
  row.classList.add('lift');
  // a ghost check, big and faint, slams down onto the box
  const ghost = h('div', { class: 'ghost' }, CHECK());
  Object.assign(ghost.style, { left: `${cx}px`, top: `${cy}px` });
  fx.append(ghost);
  haptic();
  await ghost.animate([
    { transform: 'scale(7) rotate(-12deg)', opacity: 0 },
    { transform: 'scale(5) rotate(-8deg)', opacity: 0.35, offset: 0.25 },
    { transform: 'scale(1) rotate(0deg)', opacity: 1 },
  ], { duration: 300, easing: 'cubic-bezier(.55,0,.9,.4)', fill: 'forwards' }).finished;
  ghost.remove();
  // contact: the box fills, a click, a strong tick, the screen shakes, white comes out from under the box
  row.classList.add('done');
  click(finishes);
  haptic(true);
  const sil = h('div', { class: 'silhouette' });
  Object.assign(sil.style, { left: `${cx}px`, top: `${cy}px` });
  fx.prepend(sil);
  sil.animate([
    { transform: 'scale(1)', opacity: 1 },
    { transform: 'scale(3.4)', opacity: 0 },
  ], { duration: 420, easing: 'cubic-bezier(.2,.8,.2,1)' }).finished.then(() => sil.remove());
  for (let i = 0; i < (finishes ? 3 : 2); i++) {
    const ring = h('div', { class: 'flash-ring' });
    Object.assign(ring.style, { left: `${cx}px`, top: `${cy}px` });
    fx.append(ring);
    ring.animate([
      { transform: 'scale(.6)', opacity: 1 },
      { transform: `scale(${4 + i * 2.4})`, opacity: 0, borderWidth: '0.5px' },
    ], { duration: 560 + i * 90, delay: i * 70, easing: 'cubic-bezier(.2,.8,.2,1)' }).finished.then(() => ring.remove());
  }
  box.animate([{ transform: 'scale(1.35)' }, { transform: 'scale(.92)' }, { transform: 'scale(1)' }], { duration: 260, easing: 'ease-out' });
  shake(finishes ? 9 : 6);
  await sleep(260);
  row.classList.remove('lift');
}

function shake(px) {
  const k = [];
  for (let i = 0; i <= 8; i++) {
    const a = px * (1 - i / 8);
    k.push({ transform: `translate(${(i % 2 ? -1 : 1) * a}px, ${((i * 7) % 3 - 1) * a * 0.6}px)` });
  }
  $('app').animate(k, { duration: 240, easing: 'linear' });
}

async function splash(step, it, before, after, row) {
  const el = $('splash'), stage = $('stage'), cap = $('caption'), cont = $('cont');
  const mod = JUICE[kind];
  stage.replaceChildren();
  cap.classList.remove('show'); cont.classList.remove('show');
  $('cap-step').textContent = `${step.n} ${step.name}`;
  $('cap-item').textContent = it.title;
  const [n, of] = totals(data);
  $('cap-n').textContent = `${step.items.filter((x) => isDone(step, x)).length}/${step.items.length} in the step · ${n}/${of} in the track`;
  el.classList.add('show'); el.setAttribute('aria-hidden', 'false');
  document.body.classList.add('locked');
  // the object comes over the screen from the item that was checked
  if (!reduced) {
    el.animate([{ backgroundColor: 'rgb(6 6 8 / 0)' }, { backgroundColor: 'rgb(6 6 8 / 0.97)' }], { duration: 280, fill: 'none' });
    stage.animate([{ transform: flipFrom(stage, row.querySelector('.box i')), opacity: 0 }, { transform: 'none', opacity: 1 }],
      { duration: 380, easing: 'cubic-bezier(.2,.8,.2,1)' });
  }
  const played = mod.play(stage, { data, before, after, step, item: it, reduced });
  await sleep(reduced ? 0 : 200);
  cap.classList.add('show');
  await played;
  cont.classList.add('show');
  await Promise.race([sleep(1800), tapOnce(el)]);
  // and settles into the header, where it stays as the track's progress
  if (!reduced) {
    const m = $('mini');
    await Promise.all([
      stage.animate([{ transform: 'none', opacity: 1 }, { transform: flipFrom(stage, m), opacity: 0.2 }],
        { duration: 420, easing: 'cubic-bezier(.5,0,.2,1)', fill: 'forwards' }).finished,
      el.animate([{ backgroundColor: 'rgb(6 6 8 / 0.97)' }, { backgroundColor: 'rgb(6 6 8 / 0)' }], { duration: 420, fill: 'forwards' }).finished,
      cap.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, fill: 'forwards' }).finished,
    ]);
  }
  el.getAnimations({ subtree: true }).forEach((a) => a.cancel());
  el.classList.remove('show'); el.setAttribute('aria-hidden', 'true');
  cap.classList.remove('show'); cont.classList.remove('show');
  stage.replaceChildren();
  document.body.classList.remove('locked');
  mini();
  const m = $('mini');
  m.classList.remove('got'); void m.offsetWidth; m.classList.add('got');
}

/** The transform that puts `stage` over `target` (for flying it in and out). */
function flipFrom(stage, target) {
  const s = stage.getBoundingClientRect(), t = target.getBoundingClientRect();
  const k = Math.max(0.04, t.width / s.width);
  const dx = t.left + t.width / 2 - (s.left + s.width / 2), dy = t.top + t.height / 2 - (s.top + s.height / 2);
  return `translate(${dx}px, ${dy}px) scale(${k})`;
}

function tapOnce(el) {
  return new Promise((ok) => {
    const f = () => { el.removeEventListener('pointerup', f); ok(); };
    el.addEventListener('pointerup', f);
  });
}

onTap($('reset'), () => { resetAll(); haptic(true); paint(); mini(); });

loadTrack().then((d) => {
  data = d;
  $('track').textContent = d.track;
  const cur = current(d);
  if (cur) opened.add(cur.id);
  kinds();
  render();
  mini();
  // ?item=kick.drive opens that item's widget straight away (for links from studio, and for tests)
  const want = new URLSearchParams(location.search).get('item');
  if (want) {
    const [sid, iid] = want.split('.');
    const step = d.steps.find((s) => s.id === sid), it = step?.items.find((x) => x.id === iid);
    if (it) { opened.add(step.id); paint(); work(step, it); }
  }
}).catch((err) => { $('steps').append(h('p', { text: String(err.message || err) })); });
