// The lab's boot: params, the store, the engine, the workflow tabs, the transport, snapshots and the menu.
//
// A surface is a module in surfaces/ whose default export is
//   {id, title, n, icon, about, full?, mount(root, ctx)}
// mount() builds into `root` and registers cleanups with ctx.own(fn); they run when another tab opens.

import { Engine } from './audio/engine.js';
import { installSketches } from './audio/sketches.js';
import { loadParams } from './params.js';
import { Store } from './store.js';
import { h, haptic, initInspector, longPress, toast } from './ui.js';
import collage from './surfaces/collage.js';
import arrange from './surfaces/arrange.js';
import kick from './surfaces/kick.js';
import mix from './surfaces/mix.js';
import play from './surfaces/play.js';

const SURFACES = [collage, arrange, kick, mix, play];

async function boot() {
  const params = await loadParams();
  const store = new Store(params);
  const engine = new Engine({ audioBase: new URL('./audio/', location.href).href });
  installSketches(engine);
  engine.bind(store);
  initInspector(store);
  const app = { params, store, engine, current: null, cleanups: [] };
  window.lab = app;                                       // for tests and the console
  tabs(app);
  transport(app);
  slots(app);
  menu(app);
  const want = new URLSearchParams(location.search).get('s') || sessionStorage.getItem('lab:surface') || 'kick';
  open(app, SURFACES.find((x) => x.id === want) ?? SURFACES[2]);
  gate(app);
}

function gate(app) {
  const status = h('div', { class: 'load' });
  const go = h('button', { type: 'button', text: 'Start the engine' });
  const el = h('div', { class: 'gate' }, h('div', {},
    h('h1', {}, 'HW002', h('br'), h('span', { text: 'lab' })),
    h('p', { text: 'The set\'s knobs as playable surfaces. Its own stems play under every control.' }),
    go, status));
  go.addEventListener('click', async () => {
    go.disabled = true;
    try {
      await app.engine.unlock();
      status.textContent = 'Loading HW002…';
      await app.engine.loadManifest();
      await app.engine.stems.load();
      el.remove();
      haptic(true);
      app.engine.start();
    } catch (err) {
      status.textContent = String(err.message || err);
      go.disabled = false;
      go.textContent = 'Go in without sound';
      go.onclick = () => el.remove();
    }
  }, { once: true });
  document.body.append(el);
}

function tabs(app) {
  const nav = document.getElementById('tabs');
  for (const sfc of SURFACES) {
    const b = h('button', {
      type: 'button', class: 'tab', dataset: { id: sfc.id }, style: { '--c': `var(--stage-${sfc.id})` },
      onclick: () => { haptic(); open(app, sfc); },
    });
    b.innerHTML = `<svg viewBox="0 0 24 24" aria-hidden="true">${sfc.icon}</svg>`;
    b.append(h('span', {}, sfc.title), h('span', { class: 'n', text: sfc.n }));
    nav.append(b);
  }
}

function open(app, sfc) {
  for (const fn of app.cleanups.splice(0)) { try { fn(); } catch (err) { console.error(err); } }
  const root = document.getElementById('surface');
  root.replaceChildren();
  root.dataset.stage = sfc.id;
  root.classList.toggle('is-full', !!sfc.full);
  root.scrollTop = 0;
  for (const t of document.querySelectorAll('.tab')) {
    if (t.dataset.id === sfc.id) t.setAttribute('aria-current', 'page'); else t.removeAttribute('aria-current');
  }
  sessionStorage.setItem('lab:surface', sfc.id);
  app.current = sfc;
  const ctx = {
    store: app.store, params: app.params, engine: app.engine, stage: sfc.id,
    own: (fn) => { if (typeof fn === 'function') app.cleanups.push(fn); return fn; },
  };
  try {
    sfc.mount(root, ctx);
  } catch (err) {
    console.error(err);
    root.append(h('div', { class: 'rack' }, h('p', { class: 'rack-note', text: `This surface broke: ${err.message}` })));
  }
}

function transport(app) {
  const { engine } = app;
  const play = document.getElementById('play');
  const pos = document.getElementById('pos');
  const meter = document.getElementById('master-meter');
  const cv = h('canvas', { class: 'tx-canvas' });
  meter.append(cv);
  play.addEventListener('click', async () => {
    haptic(true);
    if (engine.playing) engine.stop(); else await engine.start();
  });
  engine.onState((on) => play.setAttribute('aria-pressed', String(on)));
  let peakHold = -70, holdT = 0;
  const draw = () => {
    const p = engine.position();
    pos.textContent = p.playing ? `${String(p.bar + 1).padStart(3, '0')}.${p.beat + 1}` : '001.1';
    const r = meter.getBoundingClientRect();
    const dpr = devicePixelRatio || 1;
    if (cv.width !== Math.round(r.width * dpr)) { cv.width = Math.round(r.width * dpr); cv.height = Math.round(r.height * dpr); }
    const g = cv.getContext('2d');
    const W = cv.width, H = cv.height;
    g.clearRect(0, 0, W, H);
    const { lufs, peak } = engine.loudness();
    if (peak > peakHold || performance.now() - holdT > 1200) { peakHold = peak; holdT = performance.now(); }
    const x = (db) => Math.max(0, Math.min(1, (db + 36) / 36)) * W;
    // LUFS bar (top), peak bar (bottom)
    const lg = g.createLinearGradient(0, 0, W, 0);
    lg.addColorStop(0, '#2a3d10'); lg.addColorStop(0.62, '#c6ff3d'); lg.addColorStop(0.86, '#ffb547'); lg.addColorStop(1, '#ff2e4d');
    g.fillStyle = '#060606'; g.fillRect(0, 0, W, H);
    g.fillStyle = lg;
    g.fillRect(0, 2 * dpr, x(lufs), H / 2 - 4 * dpr);
    g.globalAlpha = 0.55; g.fillRect(0, H / 2 + 2 * dpr, x(peak), H / 2 - 4 * dpr); g.globalAlpha = 1;
    g.fillStyle = peakHold > -0.5 ? '#ff2e4d' : '#e9e7e2';
    g.fillRect(x(peakHold) - dpr, H / 2 + 2 * dpr, 2 * dpr, H / 2 - 4 * dpr);
    g.fillStyle = 'rgba(255,255,255,0.35)';
    for (const m of [-14, -8, -6]) g.fillRect(x(m), 0, dpr, H / 2);
    g.font = `${9 * dpr}px ui-monospace, monospace`; g.fillStyle = 'rgba(233,231,226,0.8)';
    g.fillText(engine.playing ? `${lufs.toFixed(1)} LUFS` : 'LUFS', 4 * dpr, H / 2 - 4 * dpr);
    requestAnimationFrame(draw);
  };
  requestAnimationFrame(draw);
  document.addEventListener('visibilitychange', () => { if (document.hidden && engine.playing) engine.stop(); });
}

function slots(app) {
  const box = document.getElementById('slots');
  const render = () => {
    box.replaceChildren(...app.store.slots.map((snap, i) => {
      const b = h('button', { type: 'button', class: `tx-slot${snap ? ' is-full' : ''}`, text: 'ABCD'[i], 'aria-label': `Snapshot ${'ABCD'[i]}` });
      b.addEventListener('click', () => {
        if (!app.store.slots[i]) { app.store.saveSlot(i); toast(`Saved to ${'ABCD'[i]}`); haptic(true); render(); return; }
        app.store.recallSlot(i); haptic(); toast(`${'ABCD'[i]} recalled`);
      });
      longPress(b, () => { app.store.saveSlot(i); toast(`Saved to ${'ABCD'[i]}`); render(); });
      return b;
    }));
  };
  render();
  app.store.on('*slots', render, { now: false });          // a slot saved from a surface (the cube's faces)
}

function menu(app) {
  const btn = document.getElementById('menu');
  btn.addEventListener('click', () => {
    const sheet = document.getElementById('inspector');
    const diff = app.store.diff();
    const close = () => { sheet.hidden = true; };
    const act = (text, fn, primary = false) => h('button', { type: 'button', class: primary ? 'primary' : '', text, onclick: () => { fn(); haptic(); } });
    const setMix = app.engine.stems;
    sheet.replaceChildren(
      h('div', { class: 'sheet-grip' }),
      h('h2', { text: 'HW002 lab' }),
      h('div', { class: 'live', text: `${diff.length} of ${app.params.list.length} controls moved from the set` }),
      h('div', { class: 'acts' },
        act('Undo', () => app.store.undo()), act('Redo', () => app.store.redo())),
      h('div', { class: 'acts', style: { marginTop: '8px' } },
        act(setMix.useMix ? 'Hear the sketch' : 'Hear the set\'s mix', () => { setMix.useMix = !setMix.useMix; toast(setMix.useMix ? 'The set\'s own mix' : 'The sketch'); close(); }),
        act('Copy changes', async () => {
          const text = JSON.stringify(diff.map(({ live, label, from, to, unit }) => ({ live, label, from, to: Math.round(to * 1000) / 1000, unit })), null, 1);
          try { await navigator.clipboard.writeText(text); toast('Copied, in Live\'s terms'); } catch { toast('Copy failed'); }
        })),
      h('div', { class: 'acts', style: { marginTop: '8px' } },
        act('Back to the set', () => { app.store.resetAll(); toast('Every control: the set\'s value'); close(); }, true),
        act('Close', close)),
      h('div', { class: 'acts', style: { marginTop: '8px' } },
        act('Studio', () => { app.engine.stop(); location.href = '/studio/'; })),
    );
    sheet.hidden = false;
  });
}

boot().catch((err) => {
  console.error(err);
  document.getElementById('surface').append(h('p', { class: 'rack-note', text: `The lab did not start: ${err.message}` }));
});
