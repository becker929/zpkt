// Play (∞): a placeholder until its surface is built. Shows every param of the stage as racks of knobs.

import { allRacks, stageHead } from './racks.js';

export default {
  id: 'play',
  title: 'Play',
  n: '∞',
  icon: '<path d="M12 2.5l8.5 4.8v9.4L12 21.5l-8.5-4.8V7.3z"/><path d="M12 12l8.5-4.7M12 12v9.5M12 12L3.5 7.3"/>',
  mount(root, ctx) {
    root.append(stageHead("Play", "the lab's strange machines", "Every surface at once, through stranger instruments."), ...allRacks(ctx, 'kick'));
  },
};
