// The map round: the checklist as a heavy ledger, the map as its only juice object, and The Wasteland around the
// map, where every check reveals a find from Anthony's library or the agents' work (all mocked here). Tap an item:
// its production widget takes the screen (../flow/widgets.js), with what you've taken from The Wasteland that fits
// it. Commit, or tap the box: the box comes to the middle of the screen and the check is stamped into it
// (check.js), then the box becomes its room on the map, which reveals the room and the find it leads to
// (world.js), and the map settles into the header. A checked box stays pressed into the ledger, dated; holding it
// reopens it. Nothing is locked: finds entice, and release never waits on them.
import {
  current, extra, haptic, isDone, keyOf, loadTrack, onTap, resetAll, setDone, setExtra, totals,
} from '../concepts/model.js';
import { openWidget } from '../flow/widgets.js';
import * as world from './world.js';
import { openCard, openSignal } from './card.js';
import { KINDS, cacheFor, findFor } from './finds.js';
import { land as landSound, load as loadSounds, picker, play as playSound, soundOn, SOUNDS, soundId, wake } from './sounds.js';
import { landInRow, particlesOn, stamp } from './check.js';

const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = (id) => document.getElementById(id);
const sleep = (ms) => new Promise((ok) => setTimeout(ok, ms));
const ROLE = { you: 'Your move', ready: 'Ready: the agent cleared the way (mocked)', clearing: 'The agent is on it (mocked)' };
const SCRIM = 'rgb(6 6 8 / 0.94)', CLEAR = 'rgb(6 6 8 / 0)';

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
const opened = new Set();
let busy = false;

// --- what the ledger keeps beside the checks (in the checklist's own store, so Reset clears it too) ---
const stamps = () => extra('map!at') ?? {};                       // item key -> when it was checked here
const keys = (name) => new Set(extra(name) ?? []);
const fresh = () => keys('map!fresh');                            // finds revealed and not looked at yet
const taken = () => keys('map!taken');                            // finds taken into the track
const saveSet = (name, set) => setExtra(name, set.size ? [...set] : undefined);

const doneKeys = () => new Set(data.steps.flatMap((s) => s.items.filter((it) => isDone(s, it)).map((it) => keyOf(s, it))));
const when = (iso) => {
  const d = new Date(iso);
  return `${d.getDate()} ${d.toLocaleString('en-GB', { month: 'short' }).toUpperCase()} ${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
};
/** A thud the hand feels: iOS gives one tick per touch, so three close together. */
function thud() { haptic(true); setTimeout(() => haptic(true), 45); setTimeout(() => haptic(true), 95); }

// --- the ledger ---
function render() {
  $('steps').replaceChildren(...data.steps.map((step, s) => {
    const head = h('button', { type: 'button', class: 'step-head', 'aria-expanded': 'false' },
      h('span', { class: 'n', text: step.n }), h('span', { class: 'name', text: step.name }),
      h('span', { class: 'count' }), CHEVRON(),
      h('span', { class: 'tally', 'aria-hidden': 'true' }, step.items.map(() => h('i'))));
    const list = h('ol', { class: 'items' }, step.items.map((it, k) => {
      const box = h('button', { type: 'button', class: 'box', 'aria-label': `Check: ${it.title}` }, h('i', {}, CHECK()));
      const open = h('button', { type: 'button', class: 'open-item' },
        h('span', { class: 't', text: it.title }), h('span', { class: 'r' }), h('span', { class: 'stamp' }));
      const go = h('span', { class: 'go', 'aria-hidden': 'true' }, CHEVRON());
      const li = h('li', { class: 'item', 'data-key': keyOf(step, it) },
        h('span', { class: 'no', text: `${s + 1}.${k + 1}` }), box, open, go);
      boxPress(box, step, it);
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
  const at = stamps();
  for (const step of data.steps) {
    const sec = document.querySelector(`.step[data-step='${step.id}']`);
    const n = step.items.filter((it) => isDone(step, it)).length;
    sec.classList.toggle('open', opened.has(step.id));
    sec.classList.toggle('clear', n === step.items.length);
    sec.querySelector('.step-head').setAttribute('aria-expanded', String(opened.has(step.id)));
    sec.querySelector('.count').textContent = `${n}/${step.items.length}`;
    [...sec.querySelectorAll('.tally i')].forEach((t, i) => t.classList.toggle('on', isDone(step, step.items[i])));
    const you = step.items.findIndex((it) => !isDone(step, it));
    step.items.forEach((it, i) => {
      const li = sec.querySelector(`.item[data-key='${keyOf(step, it)}']`);
      const done = isDone(step, it);
      li.classList.toggle('done', done);
      const role = done ? 'done' : i === you || it.state === 'waiting' ? 'you' : it.state === 'agent' ? 'clearing' : '';
      li.dataset.role = role;
      li.querySelector('.r').textContent = done ? '' : (it.why ?? ROLE[role] ?? (it.gate ? 'A decision' : ''));
      const k = keyOf(step, it);
      li.querySelector('.stamp').textContent = done ? (at[k] ? `Settled · ${when(at[k])}` : 'Settled') : '';
    });
  }
  const [n, of] = totals(data);
  $('total-n').textContent = n; $('total-of').textContent = of;
  const found = data.steps.reduce((a, s) => a + s.items.filter((it) => isDone(s, it)).length, 0);
  $("found").textContent = `${found} finds out there`;
}

function mini() {
  const f = fresh();
  const host = $('mini');
  [...host.children].filter((c) => c.id !== 'fresh').forEach((c) => c.remove());
  const tmp = document.createElement('div');
  world.mini(tmp, data, doneKeys(), { fresh: f });
  host.prepend(...tmp.childNodes);
  $('fresh').textContent = f.size ? String(f.size) : '';
  host.classList.toggle('has-fresh', f.size > 0);
  host.setAttribute('aria-label', f.size ? `Open The Wasteland: ${f.size} new` : 'Open The Wasteland');
}

/** A box: tap an open one to check it; a checked one is in the ledger, so a tap only knocks on it, and holding it
 * reopens the item. */
function boxPress(box, step, it) {
  let down = null, timer = null;
  const cancel = () => { clearTimeout(timer); timer = null; box.classList.remove('holding'); };
  box.addEventListener('pointerdown', (e) => {
    wake();
    down = [e.clientX, e.clientY];
    if (busy || !isDone(step, it)) return;
    box.classList.add('holding');
    timer = setTimeout(() => { timer = null; down = null; box.classList.remove('holding'); reopen(step, it); }, 800);
  });
  box.addEventListener('pointermove', (e) => { if (down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) > 12) { down = null; cancel(); } });
  box.addEventListener('pointercancel', () => { down = null; cancel(); });
  box.addEventListener('pointerup', (e) => {
    const tap = down && Math.hypot(e.clientX - down[0], e.clientY - down[1]) < 12;
    const holding = timer !== null;
    down = null; cancel();
    if (!tap || busy) return;
    if (!isDone(step, it)) commit(step, it, false);
    else if (holding) knock(box);
  });
}

function knock(box) {
  haptic();
  landSound();
  box.querySelector('i').animate([{ transform: 'translateY(1.5px)' }, { transform: 'none' }], { duration: 140, easing: 'ease-out' });
  toast('In the ledger. Hold the box to reopen it.');
}

function reopen(step, it) {
  setDone(step, it, false);
  const at = stamps(); delete at[keyOf(step, it)]; setExtra('map!at', Object.keys(at).length ? at : undefined);
  haptic(true);
  paint(); mini();
  toast(`Reopened: ${it.title}`);
}

let toastTimer;
function toast(text) {
  const t = $('toast');
  t.textContent = text; t.classList.add('show');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => t.classList.remove('show'), 2200);
}

// --- the production widget, full bleed, with what you've taken from The Wasteland that fits ---
let widget = null;
const rowOf = (step, it) => document.querySelector(`.item[data-key='${keyOf(step, it)}']`);
const stepOf = (key) => { const [sid, iid] = key.split('.'); const step = data.steps.find((s) => s.id === sid); return [step, step?.items.find((x) => x.id === iid)]; };

function work(step, it) {
  const host = $('widget');
  const row = rowOf(step, it);
  host.replaceChildren();
  host.classList.add('show'); host.setAttribute('aria-hidden', 'false');
  document.body.classList.add('locked');
  haptic();
  if (!reduced && row) {
    const r = row.getBoundingClientRect();
    host.animate([
      { clipPath: `inset(${r.top}px 0 ${innerHeight - r.bottom}px 0)`, opacity: 0.6 },
      { clipPath: 'inset(0 0 0 0)', opacity: 1 },
    ], { duration: 380, easing: 'cubic-bezier(.2,.8,.2,1)' });
  }
  widget = openWidget(host, {
    data, step, item: it, haptic,
    commit: () => { wake(); commit(step, it, true); },
    close: () => closeWidget(step, it),
  });
  crate(host, step, it);
}

/** "From your crate": finds taken into the track whose use includes this item (or this step), and a pointer to the
 * ones found nearby but not taken yet. Auditioning is mocked: nothing plays. */
function crate(host, step, it) {
  const foot = host.querySelector('.wg-commit');
  if (!foot) return;
  const key = keyOf(step, it);
  const done = doneKeys(), have = taken();
  const all = [...done].map((k) => findFor(k)).filter(Boolean)
    .concat(data.steps.filter((s) => s.items.every((x) => done.has(keyOf(s, x)))).map((s) => cacheFor(s.id)).filter(Boolean));
  const fits = (f) => (f.useIn ?? []).some((u) => u === key || u.split('.')[0] === step.id);
  const mine = all.filter((f) => have.has(f.key) && fits(f));
  const near = all.filter((f) => !have.has(f.key) && fits(f));
  const sec = h('section', { class: 'wg-crate', 'aria-label': 'From your crate (mocked)' },
    h('div', { class: 'cr-head' }, h('b', { text: 'From your crate' }), h('span', { text: 'The Wasteland · mocked' })));
  if (!mine.length) sec.append(h('p', { class: 'cr-empty', text: 'Nothing taken for this yet.' }));
  for (const f of mine) {
    const row = h('button', { type: 'button', class: 'cr-row', 'data-key': f.key },
      h('span', { class: 'cr-kind', text: KINDS[f.kind]?.label ?? f.kind }),
      h('span', { class: 'cr-title', text: f.title }),
      h('span', { class: 'cr-act', text: 'Audition against this' }));
    onTap(row, () => {
      haptic();
      const on = row.classList.toggle('on');
      row.querySelector('.cr-act').textContent = on ? 'Auditioning · mocked, no audio' : 'Audition against this';
    });
    sec.append(row);
  }
  if (near.length) {
    const b = h('button', { type: 'button', class: 'cr-near', text: `${near.length} more found nearby: open The Wasteland` });
    onTap(b, () => { closeWidget(step, it, true); openExplore(); });
    sec.append(b);
  }
  foot.before(sec);
}

async function closeWidget(step, it, quick = false) {
  const host = $('widget');
  if (!host.classList.contains('show')) return;
  const row = rowOf(step, it);
  if (!reduced && !quick && row) {
    const r = row.getBoundingClientRect();
    await host.animate([
      { clipPath: 'inset(0 0 0 0)', opacity: 1 },
      { clipPath: `inset(${r.top}px 0 ${innerHeight - r.bottom}px 0)`, opacity: 0.4 },
    ], { duration: 320, easing: 'cubic-bezier(.5,0,.2,1)' }).finished;
  }
  widget?.destroy?.(); widget = null;
  host.classList.remove('show'); host.setAttribute('aria-hidden', 'true');
  host.replaceChildren();
  document.body.classList.remove('locked');
}

// --- the commit: the check stamped at the middle of the screen, the box becomes its room, the map, the ledger ---
async function commit(step, it, fromWidget) {
  if (busy) return;
  busy = true;
  try {
    opened.add(step.id); paint();
    const row = rowOf(step, it);
    const r0 = row.getBoundingClientRect();
    if (r0.top < 120 || r0.bottom > innerHeight - 40) row.scrollIntoView({ block: 'center' });
    if (fromWidget) await closeWidget(step, it);
    const before = doneKeys();
    const finishes = step.items.filter((x) => !isDone(step, x)).length === 1;
    const box = row.querySelector('.box i');
    const el = $('splash'), stage = $('stage'), cap = $('caption'), cont = $('cont');

    // the scrim comes up; the check happens over it, at the stage's centre
    stage.replaceChildren(); stage.style.opacity = '0';
    cap.classList.remove('show'); cont.classList.remove('show'); $('unlock').replaceChildren();
    $('cap-step').textContent = `${step.n} ${step.name}`;
    $('cap-item').textContent = it.title;
    el.classList.add('show'); el.setAttribute('aria-hidden', 'false');
    document.body.classList.add('locked');
    let big = null, mark = null;
    if (reduced) {
      playSound(undefined, { strong: finishes }); thud();
    } else {
      el.animate([{ backgroundColor: CLEAR }, { backgroundColor: SCRIM }], { duration: 420, easing: 'ease-out' });
      const s = stage.getBoundingClientRect();
      ({ big, mark } = await stamp({
        box, at: [s.left + s.width / 2, s.top + s.height / 2], fx: $('fx'), shakeEl: $('splash'), finishes,
        onLift: () => haptic(),
        onContact: () => { playSound(undefined, { strong: finishes }); thud(); },
      }));
    }
    setDone(step, it, true);
    const at = stamps(); at[keyOf(step, it)] = new Date().toISOString(); setExtra('map!at', at);
    paint();
    const after = doneKeys();
    const [n, of] = totals(data);
    $('cap-n').textContent = `Settled · ${when(at[keyOf(step, it)])} · ${step.items.filter((x) => isDone(step, x)).length}/${step.items.length} in the step · ${n}/${of} in the track`;
    cap.classList.add('show');
    await sleep(reduced ? 0 : 650);                                   // let it weigh

    // the box becomes its room: the map starts with that room exactly where the box is
    const from = big ? big.getBoundingClientRect() : null;
    const played = world.play(stage, { data, before, after, step, item: it, reduced, from });
    if (big) {
      stage.animate([{ opacity: 0 }, { opacity: 1 }], { duration: 380, fill: 'forwards' }).finished.then(() => { stage.style.opacity = ''; });
      for (const x of [big, mark]) x.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 420, fill: 'forwards' }).finished.then(() => x.remove());
    } else stage.style.opacity = '';
    const { unlocked = [] } = (await played) ?? {};

    // what it unlocked out in The Wasteland
    const f = fresh();
    for (const u of unlocked) f.add(u.key ?? u.step);
    saveSet('map!fresh', f);
    const un = $('unlock');
    un.replaceChildren(...unlocked.map((u) => h('span', {},
      h('i', { text: u.cache ? 'Cache opened' : `Unlocked · ${KINDS[u.kind]?.label ?? ''}` }), h('b', { text: u.title }))));
    $('see').hidden = !unlocked.length;
    cont.classList.add('show');
    const choice = await choose();

    // and the map settles into the header
    if (!reduced) {
      await Promise.all([
        stage.animate([{ transform: 'none', opacity: 1 }, { transform: flipFrom(stage, $('mini')), opacity: 0.2 }],
          { duration: 520, easing: 'cubic-bezier(.5,0,.2,1)', fill: 'forwards' }).finished,
        el.animate([{ backgroundColor: SCRIM }, { backgroundColor: CLEAR }], { duration: 520, fill: 'forwards' }).finished,
        cap.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, fill: 'forwards' }).finished,
        cont.animate([{ opacity: 1 }, { opacity: 0 }], { duration: 200, fill: 'forwards' }).finished,
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
    // the box drops back into its row, pressed in for good, and its date writes in
    if (!reduced) await landInRow(box, { ink: getComputedStyle(document.documentElement).getPropertyValue('--ink').trim() || '#000', onLand: () => { landSound(); haptic(true); } });
    else box.style.visibility = '';
    const st = row.querySelector('.stamp');
    st.classList.remove('new'); void st.offsetWidth; st.classList.add('new');
    if (choice === 'see' && unlocked.length) openExplore(unlocked[0]);
  } finally { busy = false; }
}

function choose() {
  return new Promise((ok) => {
    const offs = [];
    const done = (v) => { offs.forEach((f) => f()); ok(v); };
    for (const [id, v] of [['go-on', 'go'], ['see', 'see']]) {
      const b = $(id);
      const f = (e) => { e.stopPropagation(); haptic(); done(v); };
      b.addEventListener('pointerup', f); offs.push(() => b.removeEventListener('pointerup', f));
    }
    const s = $('splash');
    const g = (e) => { if (!e.target.closest('button')) done('go'); };
    s.addEventListener('pointerup', g); offs.push(() => s.removeEventListener('pointerup', g));
  });
}

/** The transform that puts `stage` over `target` (for flying it into the header). */
function flipFrom(stage, target) {
  const s = stage.getBoundingClientRect(), t = target.getBoundingClientRect();
  const k = Math.max(0.04, t.width / s.width);
  const dx = t.left + t.width / 2 - (s.left + s.width / 2), dy = t.top + t.height / 2 - (s.top + s.height / 2);
  return `translate(${dx}px, ${dy}px) scale(${k})`;
}

// --- The Wasteland: the explore view, a find's card ---
let ex = null;
function openExplore(focus = null) {
  const host = $('explore');
  host.classList.add('show'); host.setAttribute('aria-hidden', 'false');
  document.body.classList.add('locked');
  haptic();
  ex?.destroy?.();
  ex = world.explore(host, data, doneKeys(), {
    fresh: fresh(), taken: taken(),
    onFind: (f) => showCard(f),
    onSignal: (f) => showSignal(f),
    onClose: closeExplore,
  });
  if (focus) showCard(focus);
}
function closeExplore() {
  ex?.destroy?.(); ex = null;
  const host = $('explore');
  host.classList.remove('show'); host.setAttribute('aria-hidden', 'true'); host.replaceChildren();
  document.body.classList.remove('locked');
  mini();
}

let cardOpen = null;
function cardHost() {
  const host = $('card');
  cardOpen?.destroy?.();
  host.replaceChildren();
  host.classList.add('show'); host.setAttribute('aria-hidden', 'false');
  return host;
}
function closeCard() {
  cardOpen?.destroy?.(); cardOpen = null;
  const host = $('card');
  host.classList.remove('show'); host.setAttribute('aria-hidden', 'true'); host.replaceChildren();
  ex?.refresh?.(doneKeys(), { fresh: fresh(), taken: taken() });
}
function showCard(f) {
  const fr = fresh();
  if (fr.delete(f.key ?? f.step)) { saveSet('map!fresh', fr); mini(); }   // looked at: no longer new
  const host = cardHost();
  cardOpen = openCard(host, f, {
    data, taken: taken().has(f.key ?? f.step),
    onTake: (on) => {
      const t = taken(), k = f.key ?? f.step;
      if (on) t.add(k); else t.delete(k);
      saveSet('map!taken', t);
      if (on) { thud(); playSound(); }
    },
    onWork: (key) => goWork(key),
    onClose: closeCard,
  });
}
function showSignal(f) {
  const host = cardHost();
  cardOpen = openSignal(host, f, { data, onWork: (key) => goWork(key), onClose: closeCard });
}
function goWork(key) {
  const [step, it] = stepOf(key);
  closeCard(); closeExplore();
  if (step && it) { opened.add(step.id); paint(); work(step, it); }
}

// --- the sound sheet ---
let pick = null;
function openSheet() {
  const sh = $('sheet');
  sh.classList.add('show'); sh.setAttribute('aria-hidden', 'false');
  pick?.destroy?.();
  pick = picker($('picker'), { onPick: () => paintSnd() });
}
function closeSheet() {
  const sh = $('sheet');
  sh.classList.remove('show'); sh.setAttribute('aria-hidden', 'true');
  pick?.destroy?.(); pick = null;
  paintSnd();
}
function paintSnd() {
  const b = $('snd');
  b.setAttribute('aria-pressed', String(soundOn()));
  b.setAttribute('aria-label', `Check sound: ${soundOn() ? (SOUNDS.find((x) => x.id === soundId())?.label ?? '') : 'off'}`);
}

onTap($('snd'), () => { wake(); haptic(); openSheet(); });
onTap($('sheet-close'), closeSheet);
onTap($('sheet'), (e) => { if (e.target.id === 'sheet') closeSheet(); });
onTap($('mini'), () => { wake(); if (!busy) openExplore(); });
onTap($('reset'), () => { resetAll(); haptic(true); paint(); mini(); });
particlesOn($("particles"));
loadSounds();                                                     // decoded ahead, so the first check plays at once
paintSnd();

loadTrack().then((d) => {
  data = d;
  $('track').textContent = d.track;
  const cur = current(d);
  if (cur) opened.add(cur.id);
  render();
  mini();
  // ?item=kick.drive opens that item's widget; ?explore=1 opens The Wasteland; ?card=kick.drive a find's card
  const q = new URLSearchParams(location.search);
  if (q.get('item')) { const [step, it] = stepOf(q.get('item')); if (it) { opened.add(step.id); paint(); work(step, it); } }
  else if (q.get('explore')) openExplore();
  else if (q.get('card')) { const f = findFor(q.get('card')) ?? cacheFor(q.get('card')); if (f) { openExplore(); showCard(f); } }
}).catch((err) => { $('steps').append(h('p', { text: String(err.message || err) })); });
