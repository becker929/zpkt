// The wanderer, a cut-out: three views (front, back, and the side, mirrored for the left), stepped through a
// stop-motion walk. Each step is a pose held for a moment, not a tween: a landing (tilted to one side and squashed),
// then up on the toes (tilted less, stretched, lifted), then the other foot. About eight poses a second at a walk,
// as an animator shooting on twos would. Standing, he breathes. The gold scarf's loose end streams as a ribbon
// behind him (in front when he walks away), and what he carries rides on his back, a step behind his bounce.
// If the art pack has walk frames for a view, the landings use them, with less tilt.
//
//   const hero = new Hero(art, x, y)
//   hero.update(dt, moved, vx, vy)    after the move: the facing, the walk, the breath, the scarf
//   hero.draw(g, scene, t, ghost)     the shadow, the scarf, the body, what he carries
//   hero.cheer()                      a hop: something just landed in his hands
//   hero.carry                        the artifact on his back ('bed-2'), or null
//   hero.back()                       where the carried artifact rides, in the world
const POSES = {
  stand: { rot: 0, sx: 1, sy: 1, lift: 0 },
  breath: { rot: 0, sx: 0.986, sy: 1.016, lift: 0 },
  landL: { rot: -0.075, sx: 1.05, sy: 0.93, lift: 0, frame: 0 },
  upL: { rot: -0.03, sx: 0.97, sy: 1.04, lift: 7 },
  landR: { rot: 0.075, sx: 1.05, sy: 0.93, lift: 0, frame: 1 },
  upR: { rot: 0.03, sx: 0.97, sy: 1.04, lift: 7 },
  hop: { rot: 0, sx: 0.92, sy: 1.09, lift: 22 },
  squat: { rot: 0, sx: 1.08, sy: 0.9, lift: 0 },
};
const WALK = ['landL', 'upL', 'landR', 'upR'];
const STRIDE = 25;                  // world units walked per pose
const GOLD = ['#f1b64a', '#d99a2b'];

export class Hero {
  constructor(art, x, y) {
    this.art = art;
    Object.assign(this, { x, y, vx: 0, vy: 0, face: 'front', flip: false, walk: 0, idle: 0, carry: null, cheering: -1 });
    this.prevLift = 0; this.lift = 0; this.name = 'stand';
    this.scarf = Array.from({ length: 7 }, (_, i) => [x - i * 5, y - 80]);
  }
  get asset() { return this.art.hero[this.face]; }
  get height() { return this.asset.h; }
  cheer() { this.cheering = 0; }

  update(dt, moved, vx, vy, t) {
    this.vx = vx; this.vy = vy;
    const speed = Math.hypot(vx, vy);
    if (speed > 12 && moved > 0.01) {
      if (Math.abs(vx) > Math.abs(vy) * 0.8) { this.face = 'side'; this.flip = vx < 0; } else this.face = vy < 0 ? 'back' : 'front';
      this.walk += moved / STRIDE;
      this.idle = 0;
    } else {
      this.idle += dt;
      if (this.idle > 0.12) this.walk = Math.ceil(this.walk / 2) * 2;     // settle on a landing, not mid-air
    }
    let name;
    if (this.cheering >= 0) {
      this.cheering += dt;
      name = this.cheering < 0.09 ? 'squat' : this.cheering < 0.36 ? 'hop' : this.cheering < 0.46 ? 'squat' : null;
      if (!name) this.cheering = -1;
    }
    if (!name) name = this.idle > 0.12 ? (Math.floor((this.idle + 0.4) / 0.9) % 2 ? 'breath' : 'stand') : WALK[Math.floor(this.walk) % 4];
    if (name !== this.name) { this.prevLift = this.lift; this.name = name; }
    this.lift = POSES[name].lift;
    this.scarfStep(dt, t);
  }

  /** The neck, where the ribbon is tied, for the current pose. */
  neck() {
    const a = this.asset, p = POSES[this.name], [nx, ny] = a.neck, side = this.flip ? -1 : 1;
    const up = (a.anchor[1] - ny) * a.h * p.sy, dx = (nx - a.anchor[0]) * a.w * side;
    return [this.x + dx + Math.sin(this.rot()) * up, this.y - this.lift - Math.cos(this.rot()) * up];
  }
  rot() {
    const p = POSES[this.name], frames = this.asset.walk.length > 1 && p.frame != null;
    let r = p.rot * (frames ? 0.4 : 1);
    if (this.face === 'side' && this.idle === 0) r += 0.05;                     // leaning into the walk
    return this.flip ? -r : r;
  }
  scarfStep(dt, t) {
    // the loose end: links that trail the neck, blown a little east, pulled back by walking, fluttering faster
    // the faster he goes
    // standing, it hangs behind him out of sight; walking, it streams out the other way
    const p = this.scarf, [nx, ny] = this.neck(), speed = Math.hypot(this.vx, this.vy), len = 5.2, go = Math.min(1, speed / 120);
    const behind = this.face === 'side' ? (this.flip ? 7 : -7) : 0;
    p[0] = [nx + behind, ny + 3];
    for (let i = 1; i < p.length; i++) {
      const flutter = Math.sin(t * (7 + speed * 0.04) - i * 1.25) * (0.3 + speed * 0.012) * i;
      const x = p[i][0] + (0.15 * go - this.vx * 0.014) * dt * 60 * 0.45;
      const y = p[i][1] + (0.35 + (1 - go) * 0.6 - this.vy * 0.014) * dt * 60 * 0.45 + flutter * dt * 7;
      const dx = x - p[i - 1][0], dy = y - p[i - 1][1], d = Math.hypot(dx, dy) || 1;
      p[i] = [p[i - 1][0] + (dx / d) * len, p[i - 1][1] + (dy / d) * len];
    }
  }

  /** Where what he carries rides: over the shoulder from the front, on the pack from behind, at his back side on. */
  back(lag = true) {
    const a = this.asset, h = a.h, w = a.w, lift = lag ? this.prevLift : this.lift;
    if (this.face === 'front') return [this.x + w * 0.24, this.y - lift - h * 0.68];
    if (this.face === 'back') return [this.x, this.y - lift - h * 0.42];
    return [this.x + (this.flip ? 1 : -1) * w * 0.34, this.y - lift - h * 0.5];
  }

  draw(g, scene, t, ghost = false) {
    const p = POSES[this.name], a = this.asset;
    const frames = a.walk.length > 1 && p.frame != null && !ghost;
    const src = frames ? a.walk[p.frame] : a;
    const body = scene.pose(src, { flip: this.face === 'side' && this.flip, rot: this.rot(), sx: p.sx, sy: p.sy, contact: false, pin: true }, true);
    if (ghost) { scene.blit(body, this.x, this.y - this.lift); return; }
    // the shadow stays on the ground; it shrinks a little when he's up
    const sh = this.shadow(scene, this.lift > 10 ? 0.7 : this.lift > 0 ? 0.88 : 1);
    scene.blit(sh, this.x, this.y);
    const behind = this.face !== 'back';
    if (behind) { this.drawScarf(g, scene); this.drawCarry(scene, t); }
    scene.blit(body, this.x, this.y - this.lift);
    if (!behind) { this.drawScarf(g, scene); this.drawCarry(scene, t); }
  }
  shadow(scene, k) {
    const key = `shadow:${k}`, K = scene.K;
    this.shadows ??= new Map();
    let s = this.shadows.get(key);
    if (!s || s.K !== K) {
      const rx = 30 * k, ry = 9 * k, c = document.createElement('canvas');
      c.width = Math.ceil(rx * 2 * K); c.height = Math.ceil(ry * 2 * K);
      const x = c.getContext('2d');
      x.setTransform(rx * K, 0, 0, ry * K, rx * K, ry * K);
      const gr = x.createRadialGradient(0, 0, 0, 0, 0, 1);
      gr.addColorStop(0, 'rgba(30,18,6,0.5)'); gr.addColorStop(0.7, 'rgba(30,18,6,0.22)'); gr.addColorStop(1, 'rgba(30,18,6,0)');
      x.fillStyle = gr; x.beginPath(); x.arc(0, 0, 1, 0, Math.PI * 2); x.fill();
      s = { c, ax: Math.round(rx * K), ay: Math.round(ry * K * 0.6), K };
      this.shadows.set(key, s);
    }
    return s;
  }
  drawCarry(scene, t) {
    if (!this.carry) return;
    const it = this.art.artifacts[this.carry];
    if (!it) return;
    const k = 46 / it.h;
    const p = scene.pose(it, { sx: k, sy: k, rot: (this.flip ? -1 : 1) * (this.face === 'side' ? 0.2 : 0.12), pin: true, contact: false }, true);
    const [x, y] = this.back();
    scene.blit(p, x, y);
  }
  drawScarf(g, scene) {
    // a ribbon: wide at the knot, narrowing to the end, with the white cut edge the rest of the world has; it
    // shows as he walks (standing, the scarf's own end in the art is enough)
    const go = Math.min(1, Math.hypot(this.vx, this.vy) / 90);
    this.show = (this.show ?? 0) + (go - (this.show ?? 0)) * 0.15;
    if (this.show < 0.05) return;
    const p = this.scarf, n = p.length, K = scene.K, v = scene.view;
    g.globalAlpha = Math.min(1, this.show * 1.4);
    g.setTransform(K, 0, 0, K, -v.x, -v.y);
    const left = [], right = [];
    for (let i = 0; i < n; i++) {
      const [x, y] = p[i], [x2, y2] = p[Math.min(n - 1, i + 1)], [x0, y0] = p[Math.max(0, i - 1)];
      const dx = x2 - x0, dy = y2 - y0, d = Math.hypot(dx, dy) || 1, w = 5 * (1 - (i / n) * 0.55);
      left.push([x - (dy / d) * w, y + (dx / d) * w]); right.push([x + (dy / d) * w, y - (dx / d) * w]);
    }
    g.beginPath();
    [...left, ...right.reverse()].forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y)));
    g.closePath();
    g.lineJoin = 'round'; g.strokeStyle = '#fbf6ea'; g.lineWidth = 2.4; g.stroke();
    const gr = g.createLinearGradient(p[0][0], p[0][1], p[n - 1][0], p[n - 1][1]);
    gr.addColorStop(0, GOLD[1]); gr.addColorStop(1, GOLD[0]);
    g.fillStyle = gr; g.fill();
    // the fringe at the end
    const [ex, ey] = p[n - 1], [px, py] = p[n - 2], ux = (ex - px) / 5.2, uy = (ey - py) / 5.2;
    g.strokeStyle = GOLD[1]; g.lineWidth = 1.1; g.lineCap = 'round';
    g.beginPath();
    for (const o of [-2.2, 0, 2.2]) { g.moveTo(ex - uy * o, ey + ux * o); g.lineTo(ex - uy * o + ux * 4, ey + ux * o + uy * 4); }
    g.stroke();
    g.globalAlpha = 1;
    g.setTransform(1, 0, 0, 1, 0, 0);
  }
}
