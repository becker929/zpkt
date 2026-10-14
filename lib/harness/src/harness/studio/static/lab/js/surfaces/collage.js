// Collage (I): a placeholder until its surface is built. Shows every param of the stage as racks of knobs.

import { allRacks, stageHead } from './racks.js';

export default {
  id: 'collage',
  title: 'Collage',
  n: 'I',
  icon: '<path d="M4 6h7v6H4zM13 3h7v7h-7zM8 14h9v7H8z"/>',
  mount(root, ctx) {
    root.append(stageHead("Collage", "cut, resample, lay the bed", "The bed of found sounds: ARC Raiders, the dated recordings, the bodhi synths, the beatbox, the chord loop."), ...allRacks(ctx));
  },
};
