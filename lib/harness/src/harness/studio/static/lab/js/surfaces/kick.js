// Kick (IV): "The kick and rumble get their own chain: scoop, distortion, compression. It is its own step because
// the kick carries the genre."
//
// The first screen plays: what the kick is doing now on top (a live trace of the last beat, beat LEDs, gain
// reduction), and in thumb reach the source (the set's stem, the phone's kick synth, both, or A/B a bar each), the
// heat fader (COLDFIRE and the Decapitator together, the 8.1 target zone drawn), the A/B/C tapper (37 / 43.5 / 50 %,
// a bar each) and the scoop (hold, or latch 4 bars on the bar). Below, the kick designed: one hit rendered and
// measured against the references, the envelopes, the layers, the distortion, the bus EQ, the transient shaper,
// the compressor, the rumble and the scoop map. The synth (js/kick/) follows every kick param at its full value.

import { h } from '../ui.js';
import { createRig } from '../kick/rig.js';
import { Painter } from '../kick/util.js';
import { abcTapper, header, heatFader, scoopBlock, sourceSwitch } from '../kick/deck.js';
import { hitScope } from '../kick/scope.js';
import { envelopes } from '../kick/env.js';
import { layers } from '../kick/layers.js';
import { distortion } from '../kick/style.js';
import { eqCurve } from '../kick/eq.js';
import { transient } from '../kick/shape.js';
import { compressor } from '../kick/comp.js';
import { rumbleRack } from '../kick/rumble.js';
import { scoopMap } from '../kick/map.js';

export default {
  id: 'kick',
  title: 'Kick',
  n: 'IV',
  icon: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 1v3M12 20v3M1 12h3M20 12h3"/>',
  mount(root, ctx) {
    const rig = createRig(ctx);
    const painter = new Painter(ctx);
    const deck = h('div', { class: 'kx-deck' },
      header(ctx, rig, painter),
      sourceSwitch(ctx, rig),
      heatFader(ctx, rig, painter),
      abcTapper(ctx, rig, painter),
      scoopBlock(ctx, rig, painter));
    const below = h('div', { class: 'kx-below' },
      h('div', { class: 'kx-divider' }, h('span', { text: 'DESIGN THE KICK' }), h('i', {})),
      hitScope(ctx, rig, painter),
      envelopes(ctx, rig, painter),
      layers(ctx, rig),
      distortion(ctx),
      eqCurve(ctx, rig, painter),
      transient(ctx, rig, painter),
      compressor(ctx, rig, painter),
      rumbleRack(ctx, rig, painter),
      scoopMap(ctx, rig, painter));
    root.append(h('div', { class: 'kx' }, deck, below));

    // the deck fills the first screen, whatever the phone
    const fit = () => {
      const cs = getComputedStyle(root);
      const pad = parseFloat(cs.paddingTop) || 0;
      deck.style.minHeight = `${Math.max(520, root.clientHeight - pad - 10)}px`;
    };
    const ro = new ResizeObserver(fit);
    ro.observe(root);
    ctx.own(() => ro.disconnect());
    fit();
  },
};
