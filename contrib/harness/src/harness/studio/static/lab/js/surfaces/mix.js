// Mix (V): "Groups and buses processed, levels and sends set, colour and space."
//
// One page, meters up top, the thumb's work below them:
//   the meter bridge (pinned): momentary and short-term LUFS, integrated, true peak, PLR, crest, low-end correlation
//   the desk: kick, perc and SFX groups and the two returns; faders, LED meters, mute and solo, sends
//   the A/B: your mix against the set (its render, its knobs, or the last point), every 1 or 2 bars, level matched
//   the aspects: six axes from the experiments, drag a vertex to morph that aspect, a joint climb
//   tone: the spectrum against the references, with the three gaps; EQ curves for each bus
//   low end: a goniometer and the correlation below 120 Hz; the mono controls
//   drop power: the Main's glue, the master clipper and ceiling, the crest against the references
//   space: Supermassive on perc 2 as a room you stretch
//   loudness: the full meter, one turn per pass of the loop (24 bars)
//
// Everything audible goes through the store and the engine's sketches; the meters hang off the master while this
// surface is open (js/mix/taps.js) and are disconnected when another tab opens.

import { h } from '../ui.js';
import { stageHead } from './racks.js';
import { attachTaps } from '../mix/taps.js';
import { colours, frameLoop } from '../mix/util.js';
import { bridge } from '../mix/bridge.js';
import { desk } from '../mix/desk.js';
import { abSwitch } from '../mix/ab.js';
import { aspects } from '../mix/aspects.js';
import { tone } from '../mix/tone.js';
import { lowEnd } from '../mix/scope.js';
import { dropPower } from '../mix/drop.js';
import { space } from '../mix/space.js';
import { loudness } from '../mix/radar.js';

export default {
  id: 'mix',
  title: 'Mix',
  n: 'V',
  icon: '<path d="M6 3v18M12 3v18M18 3v18"/><rect x="3.5" y="13" width="5" height="3" rx="1"/><rect x="9.5" y="6" width="5" height="3" rx="1"/><rect x="15.5" y="10" width="5" height="3" rx="1"/>',
  about: 'Groups and buses: levels, sends, colour and space, drop power, against the references.',
  mount(root, ctx) {
    const loop = frameLoop();
    const rt = { ctx, C: colours(), loop, taps: null, meter: null, meterFns: new Set(), dead: false, lastClimb: null };
    const parts = {};
    if (window.lab) window.lab.mix = rt;                  // for tests and the console

    // teardown first, so it runs first: the A/B lets go, the desk clears its solos, then the taps come off
    ctx.own(() => {
      rt.dead = true;
      try { parts.ab?.stop(); } catch (err) { console.error(err); }
      try { parts.desk?.clear(); } catch (err) { console.error(err); }
      try { parts.space?.stop?.(); } catch (err) { console.error(err); }
      rt.taps?.detach();
      rt.taps = null;
      rt.meterFns.clear();
      loop.stop();
      if (window.lab?.mix === rt) delete window.lab.mix;
    });

    const jump = (key) => parts[key]?.el?.scrollIntoView({ behavior: 'smooth', block: 'start' });

    parts.bridge = bridge(rt, { onTap: () => jump('loud') });
    parts.desk = desk(rt, {
      onSelect: (strip) => {
        if (strip.ret) { jump('space'); return; }
        parts.tone.select(strip.bus);
        parts.tone.el.querySelector('.mx-eq-head')?.scrollIntoView({ behavior: 'smooth', block: 'start' });
      },
    });
    parts.ab = abSwitch(rt);
    parts.aspects = aspects(rt);
    parts.tone = tone(rt);
    parts.low = lowEnd(rt);
    parts.drop = dropPower(rt);
    parts.space = space(rt);
    parts.loud = loudness(rt);

    const chips = [['aspects', 'Aspects'], ['tone', 'Tone'], ['low', 'Low end'], ['drop', 'Drop'], ['space', 'Space'], ['loud', 'Loudness']]
      .map(([key, text]) => h('button', { type: 'button', class: 'mx-chip', text, onclick: () => jump(key) }));

    root.append(
      parts.bridge.el,
      parts.desk.el,
      parts.ab.el,
      stageHead('Mix', 'colour and space', 'The gaps to the references are in the mix: scooped mids, missing deep sub, too much air, a wide low end, a sparse peak. Close them here, by ear and by meter.'),
      h('nav', { class: 'mx-jump', 'aria-label': 'Mix sections' }, ...chips),
      parts.aspects.el,
      parts.tone.el,
      parts.low.el,
      parts.drop.el,
      parts.space.el,
      parts.loud.el,
    );

    // the ears, once the engine has a context (the gate's tap)
    ctx.own(ctx.engine.onReady((engine) => {
      if (rt.dead || rt.taps) return;
      rt.taps = attachTaps(engine, (msg) => {
        rt.meter = msg;
        for (const fn of rt.meterFns) { try { fn(msg); } catch (err) { console.error(err); } }
      });
      parts.desk.apply();
      parts.tone.attach?.();
    }));
  },
};
