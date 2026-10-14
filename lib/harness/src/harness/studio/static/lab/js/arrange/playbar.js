// "Play the Short": a bar of count-in clicks, then the Short once (or on a loop), with a progress bar in seconds
// against the 33-50 s target. The transport's own play button plays it too (no count-in).

import { h, haptic } from '../ui.js';
import { ledButton } from './controls.js';
import { TARGET, BAR_S } from './model.js';

export function playbar(ctx, arranger) {
  const e = ctx.engine;
  let loop = true;
  try { loop = localStorage.getItem('lab:arr:loop') !== '0'; } catch { /* private mode */ }
  arranger.loop = loop;
  const icon = h('span', { class: 'pb-ic', 'aria-hidden': 'true' });
  icon.innerHTML = '<svg viewBox="0 0 24 24"><path class="i-play" d="M8 5v14l11-7z"/><path class="i-stop" d="M7 7h10v10H7z"/></svg>';
  const label = h('span', { class: 'pb-label', text: 'Play the Short' });
  const go = h('button', { type: 'button', class: 'arr-play', 'aria-pressed': 'false' }, icon, label);
  const loopBtn = ledButton('Loop', { on: loop, onToggle: (on) => {
    loop = on; arranger.loop = on;
    try { localStorage.setItem('lab:arr:loop', on ? '1' : '0'); } catch { /* private mode */ }
    arranger.apply();
  } });
  const fill = h('i', { class: 'pb-fill' });
  const zone = h('i', { class: 'pb-zone' });
  const head = h('i', { class: 'pb-head' });
  const end = h('i', { class: 'pb-end' });
  const track = h('div', { class: 'pb-track' }, zone, fill, end, head,
    h('span', { class: 'pb-t pb-t33', text: '33' }), h('span', { class: 'pb-t pb-t50', text: '50 s' }));
  const lcd = h('span', { class: 'pb-lcd lcd-s', text: '0.0 / 30 s' });
  const el = h('div', { class: 'arr-pb' }, h('div', { class: 'pb-row' }, go, loopBtn), h('div', { class: 'pb-prog' }, track, lcd));
  const MAX = 64;                                        // seconds across the track

  go.addEventListener('click', async () => {
    haptic(true);
    if (e.playing) { e.stop(); return; }
    if (arranger.mode !== 'short') return;
    arranger.countIn = true;
    arranger.rotated = false; arranger.offset = 0;
    arranger.apply();
    await e.start(0);
  });

  zone.style.left = `${TARGET.lo / MAX * 100}%`;
  zone.style.width = `${(TARGET.hi - TARGET.lo) / MAX * 100}%`;
  let last = '';
  el.tick = (w) => {
    const sec = arranger.seq.length * BAR_S;
    const playing = e.playing && arranger.mode === 'short';
    go.setAttribute('aria-pressed', String(playing));
    const t = w && w.i >= 0 ? Math.min(w.t, w.L) * BAR_S : 0;
    const txt = w && w.i < 0 ? `COUNT ${w.count}` : `${t.toFixed(1)} / ${sec.toFixed(0)} s`;
    const key = `${txt}|${playing}|${sec}`;
    if (key === last) return;
    last = key;
    label.textContent = playing ? (w && w.i < 0 ? `Count ${w.count}` : 'Stop') : 'Play the Short';
    lcd.textContent = txt;
    lcd.classList.toggle('is-in', sec >= TARGET.lo && sec <= TARGET.hi);
    end.style.left = `${Math.min(100, sec / MAX * 100)}%`;
    fill.style.width = `${Math.min(100, t / MAX * 100)}%`;
    head.style.left = `${Math.min(100, t / MAX * 100)}%`;
    head.hidden = !playing;
  };
  return el;
}
