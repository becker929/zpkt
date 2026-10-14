// Kick (IV): a placeholder until its surface is built. Shows every param of the stage as racks of knobs.

import { allRacks, stageHead } from './racks.js';

export default {
  id: 'kick',
  title: 'Kick',
  n: 'IV',
  icon: '<circle cx="12" cy="12" r="8"/><circle cx="12" cy="12" r="3"/><path d="M12 1v3M12 20v3M1 12h3M20 12h3"/>',
  mount(root, ctx) {
    root.append(stageHead("Kick", "scoop, distortion, compression", "The kick and rumble get their own chain. It is its own step because the kick carries the genre."), ...allRacks(ctx));
  },
};
