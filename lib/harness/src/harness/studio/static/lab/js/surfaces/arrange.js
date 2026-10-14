// Arrange (III): a placeholder until its surface is built. Shows every param of the stage as racks of knobs.

import { allRacks, stageHead } from './racks.js';

export default {
  id: 'arrange',
  title: 'Arrange',
  n: 'III',
  icon: '<path d="M3 6h7M12 6h9M3 12h11M16 12h5M3 18h4M9 18h12"/>',
  mount(root, ctx) {
    root.append(stageHead("Arrange", "the Short's shape", "A 33-50 s cut with an arc, on a 4/8-bar grid. It opens on the scooped kick."), ...allRacks(ctx));
  },
};
