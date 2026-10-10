// One element per message, built once and patched in place on every upsert.
//
// Controls carry data-action; the chat view handles clicks for the whole list (one listener), so a
// bubble never holds a stale copy of its message.
import { normaliseAb } from './ab.js';
import { fmtClock, fmtMs, h, setText } from './dom.js';
import { icon } from './icons.js';

const parts = new WeakMap();            // element -> its live sub-elements
export const MAX_LOOPS = 16;

export function createBubble(msg) {
  const build = BUILD[msg.kind] ?? unknownRow;
  const el = build(msg);
  el.dataset.seq = String(msg.seq);
  updateBubble(el, msg);
  return el;
}

export function updateBubble(el, msg) {
  UPDATE[msg.kind]?.(el, msg.data ?? {}, parts.get(el));
  el.dataset.rev = String(msg.rev ?? 0);
}

export const isActivity = (msg) => msg.kind === 'activity';

/** Mark the bubble whose audio is playing; its button stops it, even before its replay file exists. */
export function setPlaying(el, on) {
  el.classList.toggle('is-playing', on);
  syncPlay(el);
}

/** No replay button without a replay file; while its live stream plays, the button is there to stop it. */
function syncPlay(el) {
  const play = parts.get(el)?.play;
  if (play) play.hidden = !(el.dataset.audio || el.classList.contains('is-playing'));
}

function setAudio(el, ref) {
  if (ref?.url) el.dataset.audio = ref.url;
  else delete el.dataset.audio;
  syncPlay(el);
}

// --- user and agent: a voice line with replay, and the caption folded ------------------------

function playButton(label, size = '') {
  return h('button', { class: `play ${size}`.trim(), type: 'button', 'data-action': 'play', 'aria-label': label },
    icon('play', 'when-idle'), icon('stop', 'when-playing'));
}

function voiceBubble(msg) {
  const user = msg.kind === 'user';
  const play = playButton(user ? 'Play your recording' : 'Play Claude’s answer');
  const dur = h('span', { class: 'dur' });
  const who = h('span', { class: 'who', text: user ? 'You' : 'Claude' });
  const eq = h('span', { class: 'eq', 'aria-hidden': 'true' }, h('i'), h('i'), h('i'), h('i'));
  const voice = h('div', { class: 'voice' }, play, h('span', { class: 'voice-meta' }, who, dur), eq);
  const inline = h('p', { class: 'inline-text' });
  const captionText = h('p', { class: 'caption-text' });
  const caption = h('details', { class: 'caption' },
    h('summary', {}, h('span', { text: 'Caption' }), icon('chevron', 'chev')), captionText);
  const intent = h('span', { class: 'intent' });
  const el = h('li', { class: `msg msg--${msg.kind}` }, h('div', { class: 'bubble' }, voice, inline, caption, intent));
  parts.set(el, { play, dur, voice, inline, captionText, caption, intent });
  return el;
}

function updateUser(el, d, p) {
  const typed = d.source === 'typed';
  const text = d.text ?? '';
  el.classList.toggle('is-typed', typed);
  p.voice.hidden = typed;
  setAudio(el, d.audio);
  setText(p.dur, fmtClock(d.duration));
  setText(p.inline, typed ? text : '');
  p.inline.hidden = !typed;
  setText(p.captionText, typed ? '' : text);
  p.caption.hidden = typed || !text;
  const intent = INTENTS[d.intent] ?? (d.intent ? 'Handled by the app' : '');
  setText(p.intent, intent);
  p.intent.hidden = !intent;
}

const INTENTS = { play: 'Played by the app', stop: 'Stopped by the app' };

/**
 * Claude's bubbles. A reply is spoken: its words are the caption, folded. A narration (what Claude is
 * doing, in a few words) and a note (written outside a turn of Anthony's, never spoken) show their
 * words as they are.
 */
function updateAgent(el, d, p) {
  const role = d.role ?? 'reply';
  const text = d.text ?? '';
  const unfolded = role !== 'reply';
  el.classList.toggle('msg--narration', role === 'narration');
  el.classList.toggle('msg--note', role === 'note');
  el.classList.toggle('is-streaming', !!d.streaming);
  setText(p.inline, unfolded ? text : '');
  p.inline.hidden = !unfolded;
  setText(p.captionText, unfolded ? '' : text);
  p.caption.hidden = unfolded || !text;
  setAudio(el, d.audio);
  setText(p.dur, d.duration ? fmtClock(d.duration) : d.streaming ? 'Speaking…' : '');
  p.intent.hidden = true;
}

// --- music: a card with transport, loops, plays and the A/B indicator --------------------------

function musicCard() {
  const play = playButton('Play', 'play--big');
  const title = h('h3', { class: 'title' });
  const dur = h('span', { class: 'dur' });
  const fill = h('span', { class: 'progress-fill' });
  const progress = h('div', { class: 'progress', 'aria-hidden': 'true' }, fill);
  const side = (name) => h('span', { class: 'side', 'data-side': name }, h('b', { text: name }), h('small'));
  const ab = h('div', { class: 'ab', role: 'status', 'aria-label': 'A/B' }, side('A'), side('B'));
  const loopsValue = h('output', { class: 'loops-value' });
  const loops = h('div', { class: 'loops', role: 'group', 'aria-label': 'Loops' },
    h('button', { class: 'step', type: 'button', 'data-action': 'loops-down', 'aria-label': 'Fewer loops' }, icon('minus')),
    h('span', { class: 'loops-label' }, icon('loop'), loopsValue),
    h('button', { class: 'step', type: 'button', 'data-action': 'loops-up', 'aria-label': 'More loops' }, icon('plus')));
  const plays = h('span', { class: 'plays' });
  const noteText = h('p');
  const note = h('details', { class: 'note' }, h('summary', {}, h('span', { text: 'Notes' }), icon('chevron', 'chev')), noteText);
  const card = h('article', { class: 'card' },
    h('header', { class: 'card-head' }, h('span', { class: 'kicker' }, icon('note'), h('span', { text: 'Music' })), dur),
    title, ab,
    h('div', { class: 'transport' }, play, progress),
    h('footer', { class: 'card-foot' }, loops, plays),
    note);
  const el = h('li', { class: 'msg msg--music' }, card);
  parts.set(el, { play, title, dur, ab, loopsValue, plays, note, noteText, fill });
  setLoops(el, 1);
  return el;
}

function updateMusic(el, d, p) {
  setText(p.title, d.title || 'Untitled render');
  setText(p.dur, fmtClock(d.duration));
  setAudio(el, d.audio);
  p.play.setAttribute('aria-label', `Play ${d.title || 'the render'}`);
  const ab = normaliseAb(d.ab);
  p.ab.hidden = !ab;
  if (ab) {
    for (const s of p.ab.children) setText(s.querySelector('small'), ab.labels[s.dataset.side]);
    el.dataset.first = ab.first;
  }
  const plays = Number(d.plays) || 0;
  setText(p.plays, plays ? `Played ${plays}×` : 'Not played yet');
  setText(p.noteText, d.note ?? '');
  p.note.hidden = !d.note;
}

/** The loop count a tap on this card plays (1..MAX_LOOPS). */
export function loopsOf(el) {
  return Number(el.dataset.loops) || 1;
}

export function setLoops(el, n) {
  const loops = Math.max(1, Math.min(MAX_LOOPS, n));
  el.dataset.loops = String(loops);
  setText(parts.get(el).loopsValue, `×${loops}`);
  return loops;
}

/** Move a music card's playhead: progress through the current pass and the side that sounds. */
export function setPlayhead(el, fraction, side) {
  const p = parts.get(el);
  if (!p?.fill) return;
  p.fill.style.transform = `scaleX(${Math.max(0, Math.min(1, fraction)).toFixed(4)})`;
  if (side) el.dataset.side = side;
  else delete el.dataset.side;
}

// --- shots: the full screen with the zoom outlined, and the zoom --------------------------------

function shotsBubble() {
  const fullImg = h('img', { alt: 'The Mac’s screen', loading: 'lazy', decoding: 'async' });
  const zoomImg = h('img', { alt: 'A zoom on what changed', loading: 'lazy', decoding: 'async' });
  const rect = h('span', { class: 'rect', 'aria-hidden': 'true' });
  const full = h('button', { class: 'shot shot--full', type: 'button', 'data-action': 'shot', 'data-which': 'full',
    'aria-label': 'Open the screenshot' }, fullImg, rect);
  const zoom = h('button', { class: 'shot shot--zoom', type: 'button', 'data-action': 'shot', 'data-which': 'zoom',
    'aria-label': 'Open the zoom' }, zoomImg);
  const badge = h('span', { class: 'badge' });
  const caption = h('span', { class: 'shot-caption' });
  const el = h('li', { class: 'msg msg--shots' },
    h('figure', { class: 'shots' }, h('div', { class: 'pair' }, full, zoom), h('figcaption', {}, badge, caption)));
  parts.set(el, { fullImg, zoomImg, full, zoom, rect, badge, caption });
  return el;
}

function updateShots(el, d, p) {
  el.dataset.level = d.level ?? 'major';
  setImage(p.fullImg, d.full);
  setImage(p.zoomImg, d.zoom);
  // Equal heights side by side: each takes width in proportion to its aspect ratio.
  p.full.style.flexGrow = String(aspect(d.full));
  p.zoom.style.flexGrow = String(aspect(d.zoom));
  const r = rectPercent(d);
  p.rect.hidden = !r;
  if (r) Object.assign(p.rect.style, { left: `${r.left}%`, top: `${r.top}%`, width: `${r.width}%`, height: `${r.height}%` });
  setText(p.badge, d.level ?? 'major');
  setText(p.caption, d.caption ?? '');
}

function setImage(img, ref) {
  if (!ref?.url) return;
  if (ref.w && ref.h) {
    img.width = ref.w;
    img.height = ref.h;
  }
  if (img.getAttribute('src') !== ref.url) img.src = ref.url;
}

const aspect = (ref) => (ref?.w && ref?.h ? ref.w / ref.h : 16 / 10);

/** The zoom rectangle as percentages of the full screenshot. `rect` is [x, y, w, h] in screen pixels. */
export function rectPercent(d) {
  const rect = Array.isArray(d.rect) ? d.rect : d.rect && [d.rect.x, d.rect.y, d.rect.w, d.rect.h];
  if (!rect || rect.some((v) => !Number.isFinite(v))) return null;
  const [sw, sh] = Array.isArray(d.screen) ? d.screen : [d.screen?.w ?? d.full?.w, d.screen?.h ?? d.full?.h];
  if (!(sw > 0 && sh > 0)) return null;
  const [x, y, w, hh] = rect;
  return { left: (x / sw) * 100, top: (y / sh) * 100, width: (w / sw) * 100, height: (hh / sh) * 100 };
}

// --- activity: one-line rows, grouped by the view into "N steps" ---------------------------------

function statusIcon() {
  return h('span', { class: 'status', 'aria-hidden': 'true' },
    h('span', { class: 'spinner' }), icon('check', 'st-ok'), icon('cross', 'st-error'));
}

function activityRow() {
  const status = statusIcon();
  const tool = h('span', { class: 'tool' });
  const title = h('span', { class: 'title' });
  const ms = h('span', { class: 'ms' });
  const detail = h('pre', { class: 'detail' });
  const output = h('pre', { class: 'detail detail--output' });
  const el = h('li', { class: 'act' }, h('details', {}, h('summary', {}, status, tool, title, ms), detail, output));
  parts.set(el, { tool, title, ms, detail, output });
  return el;
}

function updateActivity(el, d, p) {
  el.dataset.status = d.status ?? 'running';
  setText(p.tool, (d.tool ?? '').replace(/^mcp__studio__/, ''));
  setText(p.title, d.title ?? '');
  setText(p.ms, Number.isFinite(d.ms) ? fmtMs(d.ms) : '');
  setText(p.detail, d.detail ?? '');
  setText(p.output, d.output ?? '');
  p.detail.hidden = !d.detail;
  p.output.hidden = !d.output;
  el.classList.toggle('has-detail', !!(d.detail || d.output));
}

/** A run of consecutive activity rows. With one row it shows just the row; with more, "N steps". */
export function createSteps() {
  const count = h('span', { class: 'steps-count' });
  const last = h('span', { class: 'steps-last' });
  const ms = h('span', { class: 'ms' });
  const list = h('ol', { class: 'steps-list' });
  const box = h('details', { class: 'steps-box' },
    h('summary', { class: 'steps-head' }, statusIcon(), count, last, ms, icon('chevron', 'chev')), list);
  const el = h('li', { class: 'steps' }, box);
  parts.set(el, { box, list, count, last, ms });
  return el;
}

export const stepsList = (group) => parts.get(group).list;

export function refreshSteps(group, messages) {
  const p = parts.get(group);
  const n = messages.length;
  const single = n === 1;
  if (single !== group.classList.contains('single')) {
    group.classList.toggle('single', single);
    p.box.open = single;              // one row shows as itself; a new run of several starts folded
  }
  const statuses = messages.map((m) => m.data?.status ?? 'running');
  group.dataset.status = statuses.includes('running') ? 'running' : statuses.includes('error') ? 'error' : 'ok';
  const current = messages.findLast((m) => m.data?.status === 'running') ?? messages[n - 1];
  setText(p.count, `${n} steps`);
  setText(p.last, current?.data?.title ?? '');
  const total = messages.reduce((sum, m) => sum + (Number(m.data?.ms) || 0), 0);
  setText(p.ms, total ? fmtMs(total) : '');
}

// --- notice and anything unknown -------------------------------------------------------------------

function noticeRow() {
  const text = h('p');
  const el = h('li', { class: 'msg msg--notice' }, text);
  parts.set(el, { text });
  return el;
}

function updateNotice(el, d, p) {
  el.dataset.level = d.level ?? 'info';
  setText(p.text, d.text ?? '');
}

function unknownRow() {
  return h('li', { class: 'msg msg--unknown', hidden: true });
}

const BUILD = { user: voiceBubble, agent: voiceBubble, music: musicCard, shots: shotsBubble, activity: activityRow, notice: noticeRow };
const UPDATE = { user: updateUser, agent: updateAgent, music: updateMusic, shots: updateShots, activity: updateActivity, notice: updateNotice };
