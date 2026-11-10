// Concept A, the stamp rally: each step is a card of card stock, each item a slot with its stamp's outline. Holding a
// slot brings the stamp down (the pressure builds where you can see it) and lifting past the threshold prints it;
// lifting early prints nothing. Each print is the item's own: shape, angle, offset, ink and the voids in it all come
// from hash(track.step.item), so the same item prints the same everywhere. What the agent has inked ahead of you
// shows as a ghost of that exact print. The overview is a passport of the seven cards. Nothing is locked.
import {
  TRACK, loadTrack, onChange, onTap, stateOf, isDone, setDone, roles, current, totals, cleared, studioHref, hash, rng,
  haptic,
} from './model.js';

const HOLD_MS = 480;
const MOVE_PX = 10;
const reduced = matchMedia('(prefers-reduced-motion: reduce)').matches;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]);
const f = (x) => x.toFixed(2);

function h(tag, attrs = {}, ...kids) {
  const el = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === 'class') el.className = v;
    else if (k === 'text') el.textContent = v;
    else if (k === 'html') el.innerHTML = v;
    else el.setAttribute(k, v);
  }
  for (const kid of kids.flat()) if (kid != null) el.append(kid);
  return el;
}

// --- the stamp: one per item, drawn the same way every time ---

const KINDS = ['round', 'rect', 'oct'];
const MARK = TRACK.toUpperCase();
const word = (title) => title.replace(/["'():,.%]/g, '').split(/\s+/).filter((w) => !/^(the|a|an|of|on|and|to|its|you|your)$/i.test(w));

/** What an item's stamp is: its shape, where it lands and how the ink takes, from the item's hash alone. */
function spec(step, it, i) {
  const r = rng(hash(`${TRACK}.${step.id}.${it.id}`));
  const kind = it.gate ? 'rect' : KINDS[Math.floor(r() * KINDS.length)];
  return {
    kind, r,
    rot: (r() * 2 - 1) * 11, dx: (r() * 2 - 1) * 4, dy: (r() * 2 - 1) * 4,
    density: 0.8 + r() * 0.16, tilt: r() * 360, fall: 0.5 + r() * 0.25,
    n: step.n, no: String(i + 1).padStart(2, '0'),
    ring: `${MARK} · ${step.name} · ${word(it.title).slice(0, 3).join(' ')} · `.toUpperCase(),
    head: (it.gate ? 'Decided' : word(it.title)[0] || it.id).toUpperCase().slice(0, 11),
  };
}

const MONO = 'font-family="ui-monospace,Menlo,monospace"';
const SERIF = 'font-family="Georgia,\'Times New Roman\',serif"';

/** The stamp's face: its lines (`line` is the stroke attributes) and its words (`ink` the text fill). */
function face(s, uid, line, ink) {
  const t = (x, y, size, text, extra = '') => `<text x="${x}" y="${y}" font-size="${size}" text-anchor="middle" ${ink} ${extra}>${esc(text)}</text>`;
  const fit = (w) => `textLength="${w}" lengthAdjust="spacingAndGlyphs"`;
  if (s.kind === 'round') {
    return `<circle cx="50" cy="50" r="46" ${line} stroke-width="3"/><circle cx="50" cy="50" r="40" ${line} stroke-width="1.1"/>`
      + `<circle cx="50" cy="50" r="27" ${line} stroke-width="0.9"/>`
      + `<path id="t-${uid}" d="M50,50 m-33,0 a33,33 0 1,1 66,0 a33,33 0 1,1 -66,0" fill="none"/>`
      + `<text font-size="6.4" font-weight="600" letter-spacing="0.6" ${MONO} ${ink}><textPath href="#t-${uid}" textLength="203" lengthAdjust="spacing">${esc(s.ring)}</textPath></text>`
      + t(50, 56, 19, s.n, `font-weight="700" ${SERIF}`) + t(50, 68, 5.6, `NO ${s.no}`, `letter-spacing="1" ${MONO}`);
  }
  if (s.kind === 'oct') {
    const oct = (r) => Array.from({ length: 8 }, (_, k) => {
      const a = (Math.PI / 8) * (2 * k + 1);
      return `${f(50 + r * Math.cos(a))},${f(50 + r * Math.sin(a))}`;
    }).join(' ');
    return `<polygon points="${oct(47)}" ${line} stroke-width="2.6"/><polygon points="${oct(41)}" ${line} stroke-width="1"/>`
      + `<line x1="22" y1="38" x2="78" y2="38" ${line} stroke-width="0.8"/><line x1="22" y1="66" x2="78" y2="66" ${line} stroke-width="0.8"/>`
      + t(50, 33, 6.4, s.head, `font-weight="700" ${MONO} ${fit(Math.min(52, s.head.length * 5.2))}`)
      + t(50, 60, 22, s.n, `font-weight="700" ${SERIF}`)
      + t(50, 76, 5.6, `${MARK} · ${s.no}`, `letter-spacing="1" ${MONO}`);
  }
  return `<rect x="5" y="20" width="90" height="60" rx="5" ${line} stroke-width="3"/><rect x="10" y="25" width="80" height="50" rx="2.5" ${line} stroke-width="1"/>`
    + t(50, 36, 6, `${MARK} · ${s.n}`, `letter-spacing="1.2" ${MONO}`)
    + t(50, 56, 15, s.head, `font-weight="800" ${MONO} ${fit(Math.min(70, s.head.length * 10))}`)
    + t(50, 69, 5.6, `NO ${s.no}`, `letter-spacing="1.2" ${MONO}`);
}

/** The ink's texture: one side lighter (the hand pressed unevenly), voids, a few blots and dry streaks. */
function texture(s, uid) {
  const r = rng(hash(`${TRACK}.${uid}.ink`));
  let voids = '';
  const n = 60 + Math.floor(r() * 50);
  for (let k = 0; k < n; k++) voids += `<circle cx="${f(r() * 100)}" cy="${f(r() * 100)}" r="${f(0.2 + r() * r() * 1.3)}"/>`;
  for (let k = 0, m = 3 + Math.floor(r() * 4); k < m; k++) voids += `<circle cx="${f(r() * 100)}" cy="${f(r() * 100)}" r="${f(1.6 + r() * 2.4)}" opacity="${f(0.25 + r() * 0.35)}"/>`;
  for (let k = 0, m = 2 + Math.floor(r() * 3); k < m; k++) {
    voids += `<ellipse cx="${f(10 + r() * 80)}" cy="${f(10 + r() * 80)}" rx="${f(5 + r() * 12)}" ry="${f(0.35 + r() * 0.6)}" transform="rotate(${f(r() * 180)} 50 50)" opacity="${f(0.4 + r() * 0.4)}"/>`;
  }
  const lo = Math.round(255 * s.fall).toString(16).padStart(2, '0');
  return `<linearGradient id="g-${uid}" gradientTransform="rotate(${f(s.tilt)} 0.5 0.5)"><stop offset="0" stop-color="#fff"/><stop offset="1" stop-color="#${lo}${lo}${lo}"/></linearGradient>`
    + `<mask id="m-${uid}" maskUnits="userSpaceOnUse" x="-10" y="-10" width="120" height="120"><rect x="-10" y="-10" width="120" height="120" fill="url(#g-${uid})"/><g fill="#000">${voids}</g></mask>`;
}

/** An item's stamp as SVG: the print (inked, textured), its ghost (the same print, outlined and dotted) or its clean
 * face (the stamp in the hand, coming down). */
function stampSVG(step, it, i, mode, uid) {
  const s = spec(step, it, i);
  const place = `translate(${f(s.dx)} ${f(s.dy)}) rotate(${f(s.rot)} 50 50)`;
  if (mode === 'ghost') {
    return `<svg class="stamp ghost" viewBox="0 0 100 100" aria-hidden="true"><g transform="${place}">`
      + face(s, uid, 'fill="none" stroke="currentColor" stroke-width="0.8" stroke-dasharray="1.2 2.2"', 'fill="currentColor" opacity="0.55"') + '</g></svg>';
  }
  if (mode === 'face') {
    return `<svg class="stamp face" viewBox="0 0 100 100" aria-hidden="true"><g transform="${place}">`
      + face(s, uid, 'fill="none" stroke="currentColor"', 'fill="currentColor"') + '</g></svg>';
  }
  return `<svg class="stamp print" viewBox="0 0 100 100" aria-hidden="true" data-print="${esc(`${step.id}.${it.id}`)}"><defs>${texture(s, uid)}</defs>`
    + `<g transform="${place}" opacity="${f(s.density)}" mask="url(#m-${uid})">`
    + face(s, uid, 'fill="none" stroke="currentColor"', 'fill="currentColor"') + '</g></svg>';
}

/** The slot's outline: where the stamp goes, square to the card. */
function guideSVG(step, it, i) {
  const { kind } = spec(step, it, i);
  const shape = kind === 'round' ? '<circle cx="50" cy="50" r="46"/>'
    : kind === 'oct' ? `<polygon points="${Array.from({ length: 8 }, (_, k) => { const a = (Math.PI / 8) * (2 * k + 1); return `${f(50 + 47 * Math.cos(a))},${f(50 + 47 * Math.sin(a))}`; }).join(' ')}"/>`
      : '<rect x="5" y="20" width="90" height="60" rx="5"/>';
  return `<svg class="guide" viewBox="0 0 100 100" aria-hidden="true">${shape}</svg>`;
}

// --- the passport ---

let data;
let openStep = null;     // the card that is open, if any
let pushed = false;      // whether opening it added a history entry (so back can pop it)

const ROLE_TEXT = { you: 'Your move', ready: 'Inked by the agent', clearing: 'Agent inking (mocked)' };

function passport() {
  const [n, of] = totals(data);
  $('track').textContent = data.track;
  $('total-n').textContent = n; $('total-of').textContent = of;
  document.title = `${data.track} Stamp Rally`;
  const cur = current(data);
  $('cards').replaceChildren(...data.steps.map((step) => {
    const r = roles(step);
    const k = cleared(step);
    const minis = step.items.map((it, i) => {
      const role = r[i];
      return h('span', { class: 'mini', 'data-role': role, html: role === 'done' ? stampSVG(step, it, i, 'print', `${step.id}-${it.id}-mini`) : '' });
    });
    const card = h('button', { type: 'button', class: 'pcard', 'data-step': step.id, 'data-state': k === step.items.length ? 'full' : step === cur ? 'next' : 'open' },
      h('span', { class: 'pc-n', text: step.n }),
      h('span', { class: 'pc-name', text: step.name }),
      h('span', { class: 'pc-count', text: `${k}/${step.items.length}` }),
      step === cur ? h('span', { class: 'pc-tag', text: 'Suggested next' }) : null,
      h('span', { class: 'pc-row' }, minis));
    onTap(card, () => { haptic(); open(step.id, true); });
    return h('li', {}, card);
  }));
}

// --- a card, open ---

function sheet() {
  const step = data.steps.find((s) => s.id === openStep);
  if (!step) return;
  const r = roles(step);
  $('sheet-name').textContent = `${step.n}  ${step.name}`;
  $('sheet-sub').textContent = `${data.track} · stamp card`;
  $('sheet-count').innerHTML = `<b>${cleared(step)}</b><span>/</span><span>${step.items.length}</span>`;
  $('slots').replaceChildren(...step.items.map((it, i) => slot(step, it, i, r[i])));
}

function slot(step, it, i, role) {
  const done = role === 'done';
  const uid = `${step.id}-${it.id}`;
  const well = h('div', {
    class: 'well', role: 'button', tabindex: '0',
    'aria-label': `${step.n}.${i + 1} ${it.title}: ${done ? 'hold to lift the stamp' : 'hold to stamp'}`,
    html: guideSVG(step, it, i)
      + (role === 'ready' || role === 'clearing' ? stampSVG(step, it, i, 'ghost', `${uid}-ghost`) : '')
      + (done ? stampSVG(step, it, i, 'print', uid) : stampSVG(step, it, i, 'face', `${uid}-face`))
      + '<span class="gauge"><i></i></span>',
  });
  const why = role !== 'done' && it.why ? it.why : role === 'ready' ? 'Waiting on your move above (mocked)' : '';
  const studio = h('a', { class: 'studio', href: studioHref(step, it) }, 'Studio', h('span', { html: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h13M13 6l6 6-6 6"/></svg>' }));
  studio.addEventListener('pointerdown', (e) => e.stopPropagation());
  onTap(studio, () => { location.href = studio.href; });
  const li = h('li', { class: 'slot', 'data-id': it.id, 'data-role': role, 'data-state': stateOf(step, it) },
    well,
    h('div', { class: 'cap' },
      h('span', { class: 'no', text: `${step.n}.${i + 1}${it.gate ? ' · decision' : ''}` }),
      h('span', { class: 'ttl', text: it.title }),
      ROLE_TEXT[role] ? h('span', { class: 'tag', text: ROLE_TEXT[role] }) : null,
      why ? h('span', { class: 'why', text: why }) : null,
      studio));
  press(well, li, step, it);
  return li;
}

// --- pressing: the stamp comes down while you hold, and prints if you held long enough ---

function press(well, li, step, it) {
  let t0 = 0, x0 = 0, y0 = 0, raf = 0, armed = false;
  const set = (p) => li.style.setProperty('--p', p.toFixed(3));
  const lift = () => {
    cancelAnimationFrame(raf);
    li.classList.remove('pressing', 'armed');
    li.classList.add('lifting');
    set(0);
    setTimeout(() => li.classList.remove('lifting'), 260);
    t0 = 0;
  };
  well.addEventListener('pointerdown', (e) => {
    if (e.button > 0) return;
    t0 = performance.now(); x0 = e.clientX; y0 = e.clientY; armed = false;
    li.classList.add('pressing');
    haptic();
    const tick = () => {
      if (!t0) return;
      const p = Math.min(1, (performance.now() - t0) / HOLD_MS);
      set(p);
      if (p >= 1 && !armed) { armed = true; li.classList.add('armed'); haptic(); }
      if (p < 1) raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
  });
  well.addEventListener('pointermove', (e) => {
    if (t0 && Math.hypot(e.clientX - x0, e.clientY - y0) > MOVE_PX) { armed = false; lift(); }
  });
  well.addEventListener('pointerup', () => {
    if (!t0) return;
    const print = armed || performance.now() - t0 >= HOLD_MS;
    if (!print) { lift(); return; }
    t0 = 0;
    cancelAnimationFrame(raf);
    stamp(step, it);
  });
  well.addEventListener('pointercancel', () => { if (t0) lift(); });
  well.addEventListener('contextmenu', (e) => e.preventDefault());
  well.addEventListener('keydown', (e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); stamp(step, it); } });
}

/** Print the stamp (or lift it), and let the new print settle into the card. */
function stamp(step, it) {
  const was = isDone(step, it);
  setDone(step, it, !was);              // onChange redraws the card
  haptic(!was);
  const li = $('slots').querySelector(`.slot[data-id='${it.id}']`);
  if (li && !reduced) { li.classList.add(was ? 'lifted' : 'just'); setTimeout(() => li.classList.remove('just', 'lifted'), 500); }
}

// --- opening and closing a card (by the hash, so back works and a card can be linked) ---

function open(id, push) {
  if (push) { pushed = true; location.hash = id; } else show(id);
}
function show(id) {
  const step = data.steps.find((s) => s.id === id);
  openStep = step ? step.id : null;
  const el = $('sheet');
  el.classList.toggle('open', !!step);
  el.setAttribute('aria-hidden', String(!step));
  $('passport').setAttribute('aria-hidden', String(!!step));
  document.body.classList.toggle('sheet-open', !!step);
  if (step) { sheet(); el.scrollTop = 0; } else { pushed = false; passport(); }
}
onTap($('sheet-back'), () => {
  haptic();
  if (pushed) history.back();
  else { history.replaceState(null, '', location.pathname + location.search); show(null); }
});
addEventListener('hashchange', () => show(location.hash.slice(1)));
onTap($('to-checklist'), () => { location.href = $('to-checklist').href; });

onChange(() => { if (!data) return; passport(); if (openStep) sheet(); });

loadTrack()
  .then((d) => { data = d; passport(); show(location.hash.slice(1)); })
  .catch((err) => { $('cards').append(h('li', { class: 'err', text: String(err.message || err) })); });
