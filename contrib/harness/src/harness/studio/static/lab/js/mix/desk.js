// The desk: five channel strips, the three group stems and the two returns. Each strip has a name plate (tap: open
// that bus's EQ and colour further down), mute and solo, the send its group has in the set (FlexVerb on the kick,
// Supermassive on perc 2, Hybrid on the SFX; on a return, its room size or its repeats), and a long fader beside an
// LED meter with peak hold.
//
// Mute and solo are the phone's (data/extras-mix.json). Solo is in place: a soloed group keeps its space on the
// returns; a soloed return plays what the groups send it, without their dry sound. Leaving the surface clears them.

import { h, haptic, inspect, longPress } from '../ui.js';
import { fader } from '../widgets/fader.js';
import { knob } from '../widgets/knob.js';
import { levelOf } from './taps.js';
import { canvas, dbToLin, fit, rgba } from './util.js';

export const STRIPS = [
  { key: 'kick', name: 'Kick', sub: 'group', bus: 'kick', level: 'mix.kick', send: 'kick.verb', sendLabel: 'Flexverb', mute: 'mix.muteKick', solo: 'mix.soloKick', col: '--stage-kick' },
  { key: 'perc', name: 'Perc', sub: 'group', bus: 'perc', level: 'mix.perc', send: 'mix.spaceMix', sendLabel: 'Space', mute: 'mix.mutePerc', solo: 'mix.soloPerc', col: '--cold' },
  { key: 'sfx', name: 'SFX', sub: 'group', bus: 'sfx', level: 'mix.sfx', send: 'mix.sfxVerb', sendLabel: 'Hybrid', mute: 'mix.muteSfx', solo: 'mix.soloSfx', col: '--stage-collage' },
  { key: 'retA', name: 'Ret A', sub: 'room', ret: 'A', level: 'mix.retA', send: 'mix.spaceDensity', sendLabel: 'Size', mute: 'mix.muteRetA', solo: 'mix.soloRetA', col: '--text-2' },
  { key: 'retB', name: 'Ret B', sub: 'echo', ret: 'B', level: 'mix.retB', send: 'mix.spaceFeedback', sendLabel: 'Repeats', mute: 'mix.muteRetB', solo: 'mix.soloRetB', col: '--text-2' },
];

const FADER = 176;

export function desk(rt, { onSelect } = {}) {
  const { ctx, C, loop } = rt;
  const { store, engine } = ctx;
  const on = (id) => store.real(id) > 0.5;
  const meters = [];

  // --- mute / solo / return levels -> the engine -------------------------------------------------------------
  const apply = () => {
    if (!engine.ctx) return;
    const groups = STRIPS.filter((s) => s.bus), rets = STRIPS.filter((s) => s.ret);
    const soloG = groups.some((s) => on(s.solo)), soloR = rets.some((s) => on(s.solo));
    for (const s of groups) {
      const muted = on(s.mute);
      const sends = !muted && (!soloG || on(s.solo));
      const dry = !muted && (!(soloG || soloR) || on(s.solo));
      const ch = engine.bus(s.bus);
      ch.set('mute', !sends);
      ch.output.gain.setTargetAtTime(dry ? 1 : 0, engine.ctx.currentTime, 0.015);
    }
    for (const s of rets) {
      const audible = !on(s.mute) && (!soloR || on(s.solo));
      const lin = audible ? dbToLin(store.real(s.level)) : 0;
      if (s.ret === 'A') engine.setMaster('reverbLevel', lin);
      else rt.taps?.setRetB(lin);
    }
    for (const st of strips) {
      st.el.classList.toggle('is-muted', on(st.s.mute));
      st.el.classList.toggle('is-solo', on(st.s.solo));
      const silent = st.s.bus ? (on(st.s.mute) || ((soloG || soloR) && !on(st.s.solo))) : (on(st.s.mute) || (soloR && !on(st.s.solo)));
      st.el.classList.toggle('is-silent', silent);
    }
  };
  rt.applyDesk = apply;

  /** Leaving the desk: mutes and solos off, every strip back to sound. */
  const clear = () => {
    const ids = STRIPS.flatMap((s) => [s.mute, s.solo]).filter((id) => store.get(id) > 0.5);
    for (const id of ids) store.set(id, 0, { source: 'desk', record: false });
    if (engine.ctx) {
      for (const s of STRIPS) if (s.bus) { const ch = engine.bus(s.bus); ch.set('mute', 0); ch.output.gain.setTargetAtTime(1, engine.ctx.currentTime, 0.015); }
      engine.setMaster('reverbLevel', dbToLin(store.real('mix.retA')));
      engine.setMaster('delayLevel', dbToLin(store.real('mix.retB')));
    }
  };

  // --- strips ------------------------------------------------------------------------------------------------
  const button = (id, letter, cls) => {
    const b = h('button', { type: 'button', class: `mx-btn ${cls}`, 'aria-label': ctx.params.get(id).label, 'aria-pressed': 'false' }, h('i'), h('span', { text: letter }));
    ctx.own(store.on(id, (v) => { b.classList.toggle('is-on', v > 0.5); b.setAttribute('aria-pressed', String(v > 0.5)); }));
    b.addEventListener('click', () => {
      store.begin(); store.set(id, store.get(id) > 0.5 ? 0 : 1, { source: 'desk' }); store.end();
      haptic(true);
    });
    longPress(b, () => inspect(id));
    return b;
  };

  const strips = STRIPS.map((s) => {
    const led = canvas('mx-led', loop);
    led.style.height = `${FADER}px`;
    const f = fader(ctx, s.level, { length: FADER, label: '' });
    const plate = h('button', {
      type: 'button', class: 'mx-plate', 'aria-label': `${s.name}: open its colour`,
      onclick: () => { haptic(); onSelect?.(s); },
    }, h('i', { class: 'mx-plate-led' }), h('b', { text: s.name }), h('span', { text: s.sub }));
    const el = h('div', { class: `mx-strip${s.ret ? ' is-ret' : ''}`, dataset: { key: s.key }, style: { '--sc': `var(${s.col})` } },
      plate,
      h('div', { class: 'mx-ms' }, button(s.mute, 'M', 'mx-m'), button(s.solo, 'S', 'mx-s')),
      knob(ctx, s.send, { size: 38, label: s.sendLabel }),
      h('div', { class: 'mx-fadebox' }, led, f));
    const st = { s, el, led, hold: -90, holdT: 0, rms: -90, peak: -90 };
    meters.push(st);
    return st;
  });

  const el = h('section', { class: 'mx-desk', 'aria-label': 'Mix desk' }, ...strips.map((x) => x.el));
  ctx.own(engine.sketch('mixx.ms', apply));
  ctx.own(engine.sketch('mixx.ret', apply));

  // --- meters --------------------------------------------------------------------------------------------------
  const buf = new Float32Array(1024);
  const LO = -48, HI = 3;
  loop.add({
    el,
    draw(now) {
      const playing = engine.playing && engine.ctx;
      for (const st of meters) {
        let lv = { rms: -120, peak: -120 };
        if (playing) {
          if (st.s.bus) lv = engine.bus(st.s.bus).level();
          else if (rt.taps) lv = levelOf(st.s.ret === 'A' ? rt.taps.retA : rt.taps.retB, buf);
        }
        st.peak = lv.peak > st.peak ? lv.peak : st.peak - 0.9;
        st.rms = lv.rms > st.rms ? st.rms + (lv.rms - st.rms) * 0.5 : st.rms - 0.45;
        if (st.peak > st.hold || now - st.holdT > 1400) { st.hold = st.peak; st.holdT = now; }
        const { g, w, h: H } = fit(loop, st.led);
        if (!w) continue;
        g.clearRect(0, 0, w, H);
        const n = 34, sh = H / n;
        const y = (db) => H - (Math.max(LO, Math.min(HI, db)) - LO) / (HI - LO) * H;
        for (let i = 0; i < n; i++) {
          const db = LO + (i + 0.5) / n * (HI - LO);
          const top = H - (i + 1) * sh;
          const col = db > -0.5 ? C.alarm : db > -9 ? C.lcd : C.acid;
          const lit = db <= st.peak;
          const body = db <= st.rms;
          g.fillStyle = lit ? (body ? col : rgba(col, 0.45)) : 'rgba(255,255,255,0.045)';
          g.fillRect(1, top + 0.8, w - 2, sh - 1.6);
        }
        if (st.hold > LO) {
          g.fillStyle = st.hold > -0.5 ? C.alarm : C.text;
          g.fillRect(0, y(st.hold) - 1, w, 2);
        }
      }
    },
  });

  return { el, clear, apply, select: (key) => strips.find((x) => x.s.key === key) };
}
