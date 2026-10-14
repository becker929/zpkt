// studio, the page: builds the parts and routes the Mac's messages to them (docs/studio.md).
import { abSide } from './ab.js';
import * as api from './api.js';
import { AudioSession } from './audio-session.js';
import { AudioEngine } from './audio.js';
import {
  loopsOf, matchFor, optionMatch, optionPick, optionsOf, optionsTurn, setLoops, setOptionPick, toggleOptionMatch,
} from './bubbles.js';
import { Dock } from './dock.js';
import { reducedMotion } from './dom.js';
import { hydrateIcons } from './icons.js';
import { Lightbox } from './lightbox.js';
import { Menu } from './menu.js';
import { Mic } from './mic.js';
import { Socket, socketUrl } from './net.js';
import { PAGE_ONLY, Prefs } from './prefs.js';
import { MessageWindow, PAGE_SIZE, WINDOW_CAP } from './store.js';
import { Timing } from './timing.js';
import { Toasts } from './toasts.js';
import { TopBar } from './topbar.js';
import { Turn } from './turn.js';
import { ChatView } from './view.js';
import { ScreenWake } from './wake.js';

const $ = (id) => document.getElementById(id);
hydrateIcons();

const prefs = new Prefs();
const socket = new Socket(socketUrl(api.BASE), () => ({
  type: 'hello', client: clientId(), prefs: prefs.values, ua: navigator.userAgent,
}));
const timing = new Timing((msg) => socket.send(msg));
const session = new AudioSession({ timing, settleMs: settleOverride() });
const store = new MessageWindow();
const engine = new AudioEngine({
  session, timing, lookup: (seq) => store.get(seq) ?? api.message(seq), optionsMatch: matchFor,
});
const mic = new Mic({ engine, session, socket, timing, prefs });
const turn = new Turn({ socket, mic, engine, prefs, timing, wake: new ScreenWake() });
const toasts = new Toasts($('toasts'));
const view = new ChatView({
  scroller: $('chat'), list: $('messages'), loadEarlier: $('load-earlier'), startOf: $('start-of'),
  empty: $('empty'), jump: $('jump'), jumpCount: $('jump-count'),
}, store);
const topbar = new TopBar({
  conn: $('conn'), phase: $('phase'), phaseText: $('phase-text'), phaseDetail: $('phase-detail'),
  autoplay: $('autoplay'), shots: $('shots'), shotsValue: $('shots-value'),
}, { turn, engine, prefs, socket, store, onReveal: (seq) => view.reveal(seq) });
const dock = new Dock({
  turn: $('turn'), face: $('turn-face'), hint: $('turn-hint'), caption: $('live-caption'),
  keyboard: $('keyboard'), composer: $('composer'), input: $('composer-input'), send: $('send'),
}, { turn, socket });
const lightbox = new Lightbox({ dialog: $('lightbox'), img: $('lightbox-img'), caption: $('lightbox-caption'), stage: $('lightbox').querySelector('.lightbox-stage') });
const menu = new Menu({
  open: $('menu-open'), sheet: $('menu'), handsfree: $('handsfree'), keepMic: $('keep-mic'), phoneMic: $('phone-mic'), readySound: $('ready-sound'),
  newConversation: $('new-conversation'),
  newConversationTitle: $('new-conversation-title'), timings: $('timings'), timingsBody: $('timings-body'), foot: $('sheet-foot'),
}, { turn, prefs, onNewConversation });

// --- the Mac's messages ----------------------------------------------------------------------------

let version = null;
let jumping = null;            // live messages that arrive while Jump to latest fetches the newest page

socket.on('message', (msg) => {
  switch (msg.type) {
    case 'welcome': return welcome(msg);
    case 'reset': return reset();
    case 'phase': return turn.phaseChanged(msg);
    case 'listen': return turn.listen(msg);
    case 'unlisten': return turn.unlisten(msg);
    case 'owner': return turn.ownerChanged(msg);
    case 'caption': return turn.captionChanged(msg);
    case 'upsert': return upsert(msg.message);
    case 'speech': return msg.state === 'begin' ? engine.speechBegin(msg) : engine.speechEnd(msg.stream);
    case 'play': return engine.play(msg.seq, msg.loops ?? 1);
    case 'stop_audio': return engine.stopAudio();
    case 'notice': return toasts.show(msg.text, msg.level);
    default: return undefined;
  }
});
socket.on('speech', ({ stream, pcm }) => engine.speechData(stream, pcm));
socket.on('state', (state) => {
  turn.connection(state);
  if (state === 'closed') checkSignedIn();
  render();
});

function welcome(msg) {
  socket.confirm();
  if (version !== null && msg.version !== version) {
    toasts.show('studio was updated.', 'info', { ms: 0, key: 'update', action: { label: 'Reload', run: () => location.reload() } });
  }
  version = msg.version;
  view.scrollToLatest();
  store.replace(msg.page?.items ?? [], !!msg.page?.has_more);
  view.ready = true;
  turn.welcome(msg);
  menu.setFooter(`Version ${msg.version ?? '?'} · conversation ${msg.conversation?.id ?? '?'}`);
}

function reset() {
  engine.reset();
  view.scrollToLatest();
  store.replace([], false);
}

function upsert(message) {
  jumping?.push(message);
  store.upsert(message);
  if (message.kind === 'music' && prefs.get('autoplay')) engine.prefetch(message);
}

store.on('change', ({ added = [], removed = [] }) => {
  engine.release(removed);
  for (const seq of added) {
    const msg = store.get(seq);
    if (msg?.kind === 'music' && msg.data?.options) preloadOptions(msg);
  }
});

/** A card of options switches only as fast as its file is in memory: fetch it as soon as the card is in the chat. */
function preloadOptions(msg) {
  view.setOptionsState(msg.seq, 'loading');
  engine.preload(msg).then(() => view.setOptionsState(msg.seq, 'ready'), () => view.setOptionsState(msg.seq, 'error'));
}

// --- the page's own controls -----------------------------------------------------------------------

view.on('action', ({ action, seq, el, control, index }) => {
  const msg = store.get(seq);
  if (!msg) return;
  if (action === 'play') {
    engine.unlock();
    if (engine.nowPlaying?.seq === seq) engine.stop();
    else if (optionsOf(el)) engine.playNow(msg, 1, { pick: optionPick(el), match: optionMatch(el) });
    else engine.playNow(msg, msg.kind === 'music' ? loopsOf(el) : 1);
  } else if (action === 'pick') {
    // Touching an option plays it; with the card playing, the switch happens on the phone's audio clock.
    setOptionPick(el, index ?? Number(control.dataset.index));
    engine.unlock();
    if (!engine.pickOption(seq, optionPick(el))) engine.playNow(msg, 1, { pick: optionPick(el), match: optionMatch(el) });
  } else if (action === 'opt-match') {
    engine.setMatch(seq, toggleOptionMatch(el));
  } else if (action === 'opt-keep' || action === 'opt-finer') {
    if (engine.nowPlaying?.seq === seq) engine.stop();
    socket.send({ type: 'say', text: optionsTurn(el, action, msg.data.title) });
  } else if (action === 'loops-down' || action === 'loops-up') {
    engine.setLoops(seq, setLoops(el, loopsOf(el) + (action === 'loops-up' ? 1 : -1)));
  } else if (action === 'shot') {
    lightbox.open(msg.data, control.dataset.which);
  }
});

view.on('load-earlier', async () => {
  const first = store.first;
  if (!first) return;
  view.setLoading(true);
  try {
    const page = await api.messages({ before: first.seq, limit: PAGE_SIZE });
    store.prepend(page.items, page.has_more);
  } catch (err) {
    toasts.show(`Couldn’t load earlier messages: ${err.message}`, 'error');
  } finally {
    view.setLoading(false);
  }
});

view.on('jump', async () => {
  if (!store.detached) {
    view.scrollToLatest({ smooth: !reducedMotion() });
    return;
  }
  jumping = [];
  try {
    const page = await api.messages({ limit: WINDOW_CAP });
    view.scrollToLatest();
    store.replace(page.items, page.has_more);
    for (const message of jumping) store.upsert(message);
  } catch (err) {
    toasts.show(`Couldn’t load the latest messages: ${err.message}`, 'error');
  } finally {
    jumping = null;
  }
});

async function onNewConversation() {
  try {
    await api.newConversation();      // the Mac answers on the socket with `reset`
    return true;
  } catch (err) {
    toasts.show(err.message, 'error');
    return false;
  }
}

prefs.on('change', ({ key }) => {
  if (!PAGE_ONLY.includes(key)) socket.send({ type: 'prefs', prefs: prefs.values });
  view.setShotLevel(prefs.get('shots'));
  render();
});

engine.on('busy', ({ done }) => socket.send({ type: 'playback', state: 'busy', done }));
engine.on('idle', ({ done }) => socket.send({ type: 'playback', state: 'idle', done }));
engine.on('nowplaying', (playing) => {
  view.setNowPlaying(playing?.seq ?? null);
  animate();
  render();
});
engine.on('error', ({ seq, error }) => {
  const why = error?.message ?? String(error ?? 'unknown error');
  toasts.show(`That audio didn’t play: ${why}`, 'error', { key: 'audio-error' });
  socket.send({ type: 'log', text: `audio #${seq} didn’t play: ${error?.name ?? 'Error'}: ${why}` });
});
// Any tap is a gesture iOS accepts: use it to start the audio, or bring it back after the page has been away.
document.addEventListener('click', () => {
  if (engine.needsUnlock) engine.unlock();
}, { capture: true });
engine.on('context', (state) => {
  if (state === 'running') toasts.dismiss('audio');
  else if (turn.started && document.visibilityState === 'visible') {
    toasts.show('The phone paused the audio.', 'warn', { ms: 0, key: 'audio', action: { label: 'Resume', run: () => engine.unlock() } });
  }
});
mic.on('state', () => animate());
mic.on('error', (err) => {
  const blocked = err?.name === 'NotAllowedError' || err?.name === 'SecurityError';
  toasts.show(blocked ? 'The mic is blocked for this page. Allow it in the browser’s settings, or type instead.'
    : `The mic didn’t open: ${err?.message ?? err}`, 'error', { key: 'mic', ms: 8000 });
});
turn.on('change', () => render());

// --- drawing ----------------------------------------------------------------------------------------

let renderFrame = 0;
function render() {
  if (!renderFrame) renderFrame = requestAnimationFrame(() => {
    renderFrame = 0;
    topbar.render();
    dock.render();
    menu.render();
  });
}

// While the mic is open or music plays: the level meter, the playhead and the A/B side, every frame.
const meters = [$('phase'), $('turn')];
let animating = false;
let level = 0;
function animate() {
  if (animating) return;
  animating = true;
  requestAnimationFrame(function frame() {
    level = level * 0.55 + (mic.state === 'open' ? mic.level : 0) * 0.45;
    for (const el of meters) el.style.setProperty('--level', level.toFixed(3));
    const pos = engine.position();
    const side = pos?.ab ? abSide(pos.ab, pos.t) : null;
    if (pos) view.updatePlayhead(pos.seq, pos.t / pos.duration, side, pos.option ?? null, !!pos.sweeping);
    topbar.setSide(side);
    if (mic.state === 'open' || engine.nowPlaying || level > 0.01) requestAnimationFrame(frame);
    else animating = false;
  });
}

// iOS keeps the layout viewport when the keyboard opens: lift the dock above it.
visualViewport?.addEventListener('resize', () => {
  const covered = Math.max(0, innerHeight - visualViewport.height - visualViewport.offsetTop);
  document.body.style.setProperty('--keyboard', `${covered}px`);
});

// --- helpers ----------------------------------------------------------------------------------------

/** One id per tab: a reconnecting page keeps its id (the Mac hands ownership back), a new tab gets its own. */
function clientId() {
  try {
    let id = sessionStorage.getItem('studio.client');
    if (!id) sessionStorage.setItem('studio.client', (id = crypto.randomUUID()));
    return id;
  } catch {
    return (clientId.fallback ??= crypto.randomUUID());
  }
}

/** ?settle=<ms> overrides the route settle delay, for tuning it on the phone. */
function settleOverride() {
  const value = new URLSearchParams(location.search).get('settle');
  return value !== null && Number.isFinite(Number(value)) ? Number(value) : null;
}

/** The socket cannot see a 401; the API can. A signed-out page goes to the sign-in page. */
let lastCheck = 0;
async function checkSignedIn() {
  if (Date.now() - lastCheck < 30000) return;
  lastCheck = Date.now();
  try {
    await api.messages({ limit: 1 });
  } catch (err) {
    if (err.status === 401) location.assign(`/login?next=${encodeURIComponent(location.pathname)}`);
  }
}

/** The newest page of history comes inside the page (#boot): shown at once, before the socket is up. The welcome
 * replaces it, keeping the bubbles that did not change. */
function showBoot() {
  let boot = null;
  try {
    boot = JSON.parse(document.getElementById('boot')?.textContent || 'null');
  } catch {
    // No history yet then: the welcome brings it.
  }
  if (!Array.isArray(boot?.items)) return;
  view.scrollToLatest();
  store.replace(boot.items, !!boot.has_more);
  view.ready = true;
}

view.setShotLevel(prefs.get('shots'));
showBoot();
render();
socket.connect();

// For debugging on the phone (and for the browser tests).
window.studio = { prefs, socket, store, view, engine, mic, turn, timing, session };
