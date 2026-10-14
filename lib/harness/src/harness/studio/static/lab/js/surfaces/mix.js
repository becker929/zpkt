// Mix (V): a placeholder until its surface is built. Shows every param of the stage as racks of knobs.

import { allRacks, stageHead } from './racks.js';

export default {
  id: 'mix',
  title: 'Mix',
  n: 'V',
  icon: '<path d="M6 3v18M12 3v18M18 3v18"/><rect x="3.5" y="13" width="5" height="3" rx="1"/><rect x="9.5" y="6" width="5" height="3" rx="1"/><rect x="15.5" y="10" width="5" height="3" rx="1"/>',
  mount(root, ctx) {
    root.append(stageHead("Mix", "colour and space", "Groups and buses: levels, mono low end, colour, space, drop power."), ...allRacks(ctx));
  },
};
