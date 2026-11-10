// Collage (I): found and library sounds chosen, cut, resampled and laid out as the track's bed.
//
// A shelf of HW002's eight source tapes (ARC Raiders, the rumble bounce, the noise splash, the chord loop, the two
// 2023 synth stems, the 2023-10-07 recording, the beatbox) and any resamples made here, over five modes:
//   GRAIN  scrub a tape with your fingers: each finger a grain voice (js/collage/panel-grain.js, grains.js)
//   SLICE  16 slices on MPC pads and a 16-step pattern (panel-slice.js, slicer.js)
//   TAPE   the tape machine: hold the reels to stop, drag to bend, varispeed, wow, flutter; RESAMPLE (panel-tape.js)
//   BED    six lanes over the stems' 24 bars, played under the stems on the grid (panel-bed.js, bed.js)
//   RACK   every tape's chain on the col.* knobs, the Break bus, the console (panel-rack.js, graph.js)
// The collage plays its sources fresh through its own buses, so its col.* sketches use full values (graph.js).

import { mountCollage } from '../collage/app.js';

export default {
  id: 'collage',
  title: 'Collage',
  n: 'I',
  icon: '<path d="M4 6h7v6H4zM13 3h7v7h-7zM8 14h9v7H8z"/>',
  full: true,
  about: 'Cut, resample and lay out the bed: the found sounds as instruments.',
  mount(root, ctx) {
    mountCollage(root, ctx);
  },
};
