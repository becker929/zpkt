// The lab's widget library in one import:
//
//   import * as W from '../widgets/index.js';
//   root.append(W.xyPad(ctx, ['kick.colourFreq', 'kick.colour']), W.macro(ctx, ['kick.drive', 'rumble.drive']));
//
// Every widget is fn(ctx, id | ids | source, opts) -> HTMLElement, follows the store, writes one undo step per
// gesture, shows the set's value in acid and the tried range pale, and registers its cleanups with ctx.own.
// Each file's header says what the widget does and its options.

export { knob } from './knob.js';                                 // knob(ctx, id, {size, skin, label})
export { fader, toggle } from './fader.js';                       // fader(ctx, id, {length, horizontal, label, thin}); toggle(ctx, id, {label, wide})
export { xyPad } from './xy.js';                                  // xyPad(ctx, [idX, idY], {size, height, label, trail})
export { multislider } from './multislider.js';                   // multislider(ctx, ids, {height, barWidth, labels, label})
export { numberBox } from './numbox.js';                          // numberBox(ctx, id, {label, width, unit})
export { segmented, pictslider } from './segmented.js';           // segmented(ctx, id, {label, options, steps}); pictslider(ctx, id, {label, steps, length})
export { encoder } from './encoder.js';                           // encoder(ctx, id, {size, detents, steps, label})
export { crossfader, ribbon } from './ribbon.js';                 // crossfader(ctx, id, {length, labels, label}); ribbon(ctx, id, {length, mode, label})
export { padGrid } from './pads.js';                              // padGrid(ctx, ids, {cols, depth, decay, labels, label, onHit})
export { stepGrid } from './steps.js';                            // stepGrid(ctx, ids, {steps, depth, labels, label, key, state, onState})
export { matrixctrl } from './matrix.js';                         // matrixctrl(ctx, grid, {rows, cols, label})
export { nodes, defaultSnapshots } from './nodes.js';             // nodes(ctx, ids, {snapshots, size, label, key, state, onState})
export { pie, radial } from './radial.js';                        // pie(x, y, items, {title, current}) -> Promise; radial(ctx, id, {label, size})
export { vu, ledLadder, scope, spectrum } from './meters.js';     // vu(ctx, source, {width, label, ref}); ledLadder(ctx, source, {height, segments, label}); scope/spectrum(ctx, source, {width, height, label})
export { macro, macroTargets, curveOf } from './macro.js';        // macro(ctx, targets, {label, size, key, state, onState})
export { link } from './link.js';                                 // link(ctx, [idA, idB], {label, size, ratio, linked})
export { abcTapper, abcSnaps } from './abc.js';                   // abcTapper(ctx, ids, {bars, labels, snaps, label, key, state, onState})
export {
  modSource, localCtx, LocalStore, tick, frameCount, touches, chooser, writers, keep, later, barClock, analyserOf,
} from './kit.js';
