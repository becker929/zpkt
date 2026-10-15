// The wanderer: a hooded figure in a white cloak with a pack (what is carried home rides in it) and a gold scarf
// whose tail streams behind. Four facings (left is right, mirrored), a four-frame walk, a breath when standing.
//
//   frames(face, n, flip, ghost)  the sprite for a facing ('down' | 'up' | 'side'), a walk frame (0 stands, 1..4
//                                 walk, -1 breathes in), mirrored for the left, or as a ghost (seen through a wall)
//   new Scarf()      the scarf's tail: a few points that follow the neck with lag and flutter
import { Pix } from './pix.js';

// '.' nothing, 'w' cloak, 'k' black, 'g' the scarf. Rows 0-6 the hood, 7-11 the cloak and pack, 12-15 the legs.
const HEAD = {
  down: [
    '...kkkkk...',
    '..kwwwwwk..',
    '.kwwwwwwwk.',
    '.kwwkkkwwk.',
    '.kwkwkwkwk.',
    '.kwkkkkkwk.',
    '..kgggggk..',
  ],
  up: [
    '...kkkkk...',
    '..kwwwwwk..',
    '.kwwwwwwwk.',
    '.kwwwwwwwk.',
    '.kwwwwwwwk.',
    '.kwwwwwwwk.',
    '..kgggggk..',
  ],
  side: [
    '...kkkkk...',
    '..kwwwwwk..',
    '.kwwwwwwwk.',
    '.kwwwwkkwk.',
    '.kwwwwkwwk.',
    '.kwwwwkkwk.',
    '..kggggggk.',
  ],
};
const BODY = {
  down: [
    '.kwwwgwwwk.',
    'kwwwwgwwwwk',
    'kwwwwwwwwwk',
    'kwwwwwwwwwk',
    '.kkkkkkkkk.',
  ],
  up: [
    '.kwkkkkkwk.',
    'kwwkwwwkwwk',
    'kwwkwwwkwwk',
    'kwwkkkkkwwk',
    '.kkkkkkkkk.',
  ],
  side: [
    'kkkkwwwwk..',
    'kwwkwwwwwk.',
    'kwwkwwwwwk.',
    'kkkkwwwwwwk',
    '..kkkkkkkk.',
  ],
};
// legs: standing, then the four steps of a walk (a stride, passing, the other stride, passing)
const STAND = ['..kwwkwwk..', '..kwwkwwk..', '..kwwkwwk..', '..kkkkkkk..'];
const SIDE = ['....kwwk...', '....kwwk...', '....kwwwk..', '....kkkkk..'];
const STRIDE = ['...kwwwwk..', '..kwwkkwwk.', '.kwwk..kwwk', '.kkk....kkk'];
const LEGS = {
  front: [
    STAND,
    ['..kwwkwwk..', '..kwwkwwk..', '..kwwkkkk..', '..kkkk.....'],
    STAND,
    ['..kwwkwwk..', '..kwwkwwk..', '..kkkkwwk..', '.....kkkk..'],
    STAND,
  ],
  side: [SIDE, STRIDE, SIDE, STRIDE, SIDE],
};

export const HERO_W = 11, HERO_H = 16;
const cache = new Map();
/** The sprite canvas for a facing and frame; its anchor (the feet) is at (5, 15). */
export function frames(face, n, flip = false, ghost = false) {
  const key = `${face}${n}${flip ? 'f' : ''}${ghost ? 'g' : ''}`;
  let c = cache.get(key);
  if (!c) {
    const p = new Pix(HERO_W, HERO_H);
    // the body sinks a pixel on the two stride frames, and on a breath
    const bob = n === 1 || n === 3 ? 1 : 0;
    const breath = n === -1 ? 1 : 0;   // the hood dips as he breathes out
    const legs = (face === 'side' ? LEGS.side : LEGS.front)[Math.max(0, n)];
    p.stamp(legs, 0, 12, flip);
    p.stamp(BODY[face], 0, 7 + bob, flip);
    p.stamp(HEAD[face], 0, bob + breath, flip);
    if (ghost) for (let i = 0; i < p.d.length; i++) if ((i % HERO_W + Math.floor(i / HERO_W)) % 2 || p.d[i] === 2) p.d[i] = 0;
    c = p.canvas();
    cache.set(key, c);
  }
  return c;
}

/** The scarf's tail: N points hung from the neck, each kept a set distance from the one before, pushed by the wind
 * and by walking, with a flutter. Drawn as gold pixels. */
export class Scarf {
  constructor(x, y, n = 6) { this.p = Array.from({ length: n }, (_, i) => [x - i, y]); this.t = 0; }
  update(nx, ny, vx, vy, dt) {
    this.t += dt;
    const p = this.p, len = 1.6;
    p[0] = [nx, ny];
    const speed = Math.hypot(vx, vy);
    for (let i = 1; i < p.length; i++) {
      // the wind blows a little to the east; walking pulls the tail back; it flutters more the faster you go
      const flutter = Math.sin(this.t * (9 + speed * 0.12) - i * 1.3) * (0.25 + speed * 0.012) * i;
      let x = p[i][0] + (0.35 - vx * 0.006) * dt * 60 * 0.4, y = p[i][1] + (0.18 - vy * 0.006) * dt * 60 * 0.4 + flutter * dt * 6;
      const dx = x - p[i - 1][0], dy = y - p[i - 1][1], d = Math.hypot(dx, dy) || 1;
      p[i] = [p[i - 1][0] + (dx / d) * len, p[i - 1][1] + (dy / d) * len];
    }
  }
}
