// The Rummage drawn: a collage on a canvas at the device's own resolution (up to 3x), smooth, not pixel art.
//
// Nothing is resampled per frame. The ground (the region's sheet, patches of cork and tin and newsprint, the mats
// under the landmarks, the scraps on it, the torn-paper paths) is painted once into tiles of 512 device px, kept in a
// small cache and blitted. Every standing thing is drawn once at its drawn size (a "flat"), and then once per pose:
// its slight fixed turn, a mirror, with its contact shadow and a soft drop shadow baked in. The stop-motion boil
// steps each thing between two poses and a small offset, eight times a second, all on the same frames. Poses not
// drawn for a while are let go; new ones are made within a few milliseconds a frame.
//
//   const scene = createScene(canvas, { R, art })
//   scene.resize()                  after a size change (the scale, and every cache made at the old one)
//   scene.look(x, y)                centres the view on a world point, to the device pixel
//   scene.draw(t, frame)            one frame: { hero, plinths, bounce, settle, bloom, beat, after(g) }
//   scene.dish(part)                where that part's artifact rests on the Gramophone (world)
//   scene.pose(asset, opts, force)  a pose of an asset: { c, ax, ay } (opts: flip, rot, sx, sy, shadow, contact, pin)
//   scene.blit(pose, x, y)          a pose at a world point, to the device pixel
//   scene.toScreen(x, y) / toWorld(cx, cy)   world <-> CSS px
import { decal, doily, material, pattern } from './paper.js';

const TD = 512;                     // a ground tile, device px
const PAD = 7;                      // room round a flat for the cut edge, world units
const SHADOW = { dx: 5, dy: 4, blur: 7, color: 'rgba(38,22,8,0.36)' };
const BOIL = [[0, 0, 0], [0.0105, 0.5, -0.45], [0, -0.55, 0.35]];   // [turn, dx, dy] per boil step

function canvas(w, h) { const c = document.createElement('canvas'); c.width = Math.max(1, w); c.height = Math.max(1, h); return c; }

export function createScene(cv, { R, art }) {
  const ctx = cv.getContext('2d', { alpha: false });
  const view = { x: 0, y: 0 };
  let dpr = 1, zoom = 1, K = 1, CW = 1, CH = 1;
  const flats = new Map(), poses = new Map(), tiles = new Map(), pool = [];
  let budget = 0, frameNo = 0;
  const stats = { tiles: 0, poses: 0, ms: 0 };

  function resize() {
    dpr = Math.min(3, devicePixelRatio || 1);
    // the wanderer about 80-100 CSS px tall on a phone; a desk shows more of the place, not a bigger one
    zoom = Math.max(0.72, Math.min(1.1, Math.min(innerWidth / 393, innerHeight / 700) * 0.82));
    K = zoom * dpr;
    CW = cv.width = Math.round(innerWidth * dpr); CH = cv.height = Math.round(innerHeight * dpr);
    flats.clear(); poses.clear();
    for (const c of tiles.values()) pool.push(c);
    tiles.clear();
    pats.clear();
  }

  // --- flats and poses ---
  function flat(a) {
    const key = `${a.key}:${a.v}`;
    let f = flats.get(key);
    if (!f) {
      const c = canvas(Math.ceil((a.w + PAD * 2) * K), Math.ceil((a.h + PAD * 2) * K));
      const g = c.getContext('2d');
      g.imageSmoothingQuality = 'high';
      g.setTransform(K, 0, 0, K, PAD * K, PAD * K);
      a.draw(g);
      f = c;
      flats.set(key, f);
    }
    return f;
  }
  /** A pose of an asset, made now if `force` or there's time left this frame; null if not. */
  function pose(a, { flip = false, rot = 0, sx = 1, sy = 1, shadow = true, contact = true, pin = false } = {}, force = false) {
    const key = `${a.key}:${a.v}|${flip ? 1 : 0}|${rot.toFixed(4)}|${sx.toFixed(3)}|${sy.toFixed(3)}|${shadow ? 1 : 0}${contact ? 1 : 0}`;
    let p = poses.get(key);
    if (p) { p.used = frameNo; return p; }
    if (!force && budget <= 0) return null;
    const t0 = performance.now();
    const w = a.w, h = a.h, ax = a.anchor[0] * w, ay = a.anchor[1] * h, fx = flip ? -sx : sx;
    const cos = Math.cos(rot), sin = Math.sin(rot);
    let x0 = Infinity, y0 = Infinity, x1 = -Infinity, y1 = -Infinity;
    for (const [px, py] of [[-PAD, -PAD], [w + PAD, -PAD], [w + PAD, h + PAD], [-PAD, h + PAD]]) {
      const lx = (px - ax) * fx, ly = (py - ay) * sy, X = lx * cos - ly * sin, Y = lx * sin + ly * cos;
      x0 = Math.min(x0, X); y0 = Math.min(y0, Y); x1 = Math.max(x1, X); y1 = Math.max(y1, Y);
    }
    const foot = Math.max(a.foot * w * 1.3, w * 0.3) * sx, footY = foot * 0.3;
    if (shadow) {
      x0 = Math.min(x0 - SHADOW.blur, -foot); x1 = Math.max(x1 + SHADOW.dx + SHADOW.blur * 1.5, foot);
      y0 -= SHADOW.blur; y1 = Math.max(y1 + SHADOW.dy + SHADOW.blur * 1.5, footY);
    }
    const oxD = Math.ceil(-x0 * K), oyD = Math.ceil(-y0 * K);
    const c = canvas(Math.ceil((x1 - x0) * K) + 2, Math.ceil((y1 - y0) * K) + 2);
    const g = c.getContext('2d');
    g.imageSmoothingQuality = 'high';
    if (shadow && contact) {
      // the contact shadow, where it stands
      g.setTransform(K * foot, 0, 0, K * footY, oxD, oyD - footY * 0.4 * K);
      const gr = g.createRadialGradient(0, 0, 0, 0, 0, 1);
      gr.addColorStop(0, 'rgba(38,22,8,0.42)'); gr.addColorStop(0.6, 'rgba(38,22,8,0.2)'); gr.addColorStop(1, 'rgba(38,22,8,0)');
      g.fillStyle = gr; g.beginPath(); g.arc(0, 0, 1, 0, Math.PI * 2); g.fill();
    }
    if (shadow) {
      g.shadowColor = SHADOW.color; g.shadowBlur = SHADOW.blur * K; g.shadowOffsetX = SHADOW.dx * K; g.shadowOffsetY = SHADOW.dy * K;
    }
    g.setTransform(K, 0, 0, K, oxD, oyD);
    g.rotate(rot); g.scale(fx, sy); g.translate(-ax, -ay);
    g.drawImage(flat(a), -PAD, -PAD, w + PAD * 2, h + PAD * 2);
    p = { c, ax: oxD, ay: oyD, used: frameNo, pin };
    poses.set(key, p);
    stats.poses++;
    budget -= performance.now() - t0;
    return p;
  }
  function forget() {
    // poses not drawn in the last ~6 seconds go (the hero's and the artifacts' are pinned)
    for (const [k, p] of poses) if (!p.pin && frameNo - p.used > 360) poses.delete(k);
  }
  const blit = (p, x, y, dx = 0, dy = 0) => ctx.drawImage(p.c, Math.round(x * K - view.x + dx * K) - p.ax, Math.round(y * K - view.y + dy * K) - p.ay);
  /** A pose drawn scaled about its anchor (for a short squash or a bloom: resampled, so only while it lasts). */
  function blitScaled(p, x, y, sx, sy) {
    const X = x * K - view.x, Y = y * K - view.y;
    ctx.setTransform(sx, 0, 0, sy, X, Y);
    ctx.drawImage(p.c, -p.ax, -p.ay);
    ctx.setTransform(1, 0, 0, 1, 0, 0);
  }

  // --- the ground, in tiles ---
  const work = canvas(TD, TD), wg = work.getContext('2d');
  const pats = new Map();
  const fillOf = (name, angle = 0) => {
    let p = pats.get(name);
    if (!p) { p = pattern(wg, name, 0.5); pats.set(name, p); }
    try { p.setTransform(new DOMMatrix().rotateSelf((angle * 180) / Math.PI).scaleSelf(0.5)); } catch { /* unscaled */ }
    return p;
  };
  const poly = (g, pts) => { g.beginPath(); pts.forEach(([x, y], i) => (i ? g.lineTo(x, y) : g.moveTo(x, y))); g.closePath(); };
  const hits = (b, x0, y0, x1, y1) => b[2] >= x0 && b[0] <= x1 && b[3] >= y0 && b[1] <= y1;
  function sheet(g, s, fill, shadow = 4, edge = '#f8f2e4') {
    g.save();
    g.shadowColor = 'rgba(40,24,10,0.3)'; g.shadowBlur = shadow * K; g.shadowOffsetX = shadow * 0.3 * K; g.shadowOffsetY = shadow * 0.5 * K;
    poly(g, s.outer); g.fillStyle = edge; g.fill();
    g.restore();
    poly(g, s.inner); g.fillStyle = fill; g.fill();
  }
  function paintTile(i, j) {
    const g = wg, x0 = (i * TD) / K, y0 = (j * TD) / K, x1 = ((i + 1) * TD) / K, y1 = ((j + 1) * TD) / K;
    g.setTransform(K, 0, 0, K, -i * TD, -j * TD);
    g.fillStyle = fillOf('table', 0.02); g.fillRect(x0, y0, x1 - x0, y1 - y0);
    // the region's sheet: a soft shadow on the table, a white torn edge, the ground
    g.save();
    g.shadowColor = 'rgba(0,0,0,0.55)'; g.shadowBlur = 22 * K; g.shadowOffsetY = 8 * K;
    poly(g, R.edge.outer); g.fillStyle = '#f6efe0'; g.fill();
    g.restore();
    poly(g, R.edge.inner); g.fillStyle = fillOf(art.floor?.base ?? 'kraft'); g.fill();
    for (const p of R.patches) if (hits(p.box, x0, y0, x1, y1)) sheet(g, p, fillOf(p.mat, p.a), 4);
    for (const m of R.mats) {
      if (!hits(m.box, x0, y0, x1, y1)) continue;
      if (m.mat === 'doily') doily(g, m.cx, m.cy, m.rx, m.ry); else sheet(g, m, fillOf(m.mat, m.a), 6);
    }
    for (const d of R.decals) if (d.x > x0 - 30 && d.x < x1 + 30 && d.y > y0 - 30 && d.y < y1 + 30) decal(g, d);
    for (const p of R.pieces) {
      if (!hits(p.box, x0, y0, x1, y1)) continue;
      if (art.path) {
        g.save(); g.translate(p.x, p.y); g.rotate(p.a); if (p.flip) g.scale(1, -1);
        g.shadowColor = 'rgba(40,24,10,0.3)'; g.shadowBlur = 3 * K; g.shadowOffsetY = 1.5 * K;
        g.drawImage(art.path.img, -p.len / 2, -p.wid / 2, p.len, p.wid);
        g.restore();
      } else sheet(g, p, fillOf(p.mat, p.a), 3);
    }
    let c = tiles.get(`${i},${j}`) ?? pool.pop();
    if (!c || c.width !== TD) c = canvas(TD, TD);
    const tg = c.getContext('2d', { alpha: false });
    tg.drawImage(work, 0, 0);
    stats.tiles++;
    return c;
  }
  function tile(i, j, force) {
    const key = `${i},${j}`;
    let c = tiles.get(key);
    if (c) { tiles.delete(key); tiles.set(key, c); return c; }
    if (!force && budget <= 0) return null;
    const t0 = performance.now();
    c = paintTile(i, j);
    tiles.set(key, c);
    while (tiles.size > 44) { const [k0, old] = tiles.entries().next().value; tiles.delete(k0); pool.push(old); }
    budget -= performance.now() - t0;
    return c;
  }
  /** Repaints the ground (the art pack's textures arrived). */
  function regrind() { for (const c of tiles.values()) pool.push(c); tiles.clear(); pats.clear(); }

  function look(x, y) {
    const M = 150;                  // how far past the region's edge the view may go: the table it lies on
    const maxX = (R.W + M) * K - CW, maxY = (R.H + M) * K - CH;
    let vx = x * K - CW / 2, vy = y * K - CH / 2;
    vx = maxX < -M * K ? (R.W * K - CW) / 2 : Math.max(-M * K, Math.min(maxX, vx));
    vy = maxY < -M * K ? (R.H * K - CH) / 2 : Math.max(-M * K, Math.min(maxY, vy));
    view.x = Math.round(vx); view.y = Math.round(vy);
  }

  // --- the glow behind a lit slot, made once ---
  let glowC = null;
  function glow() {
    if (glowC && glowC.k === K) return glowC;
    const r = Math.ceil(40 * K), c = canvas(r * 2, r * 2), g = c.getContext('2d');
    const gr = g.createRadialGradient(r, r, 0, r, r, r);
    gr.addColorStop(0, 'rgba(255,226,140,0.95)'); gr.addColorStop(0.25, 'rgba(241,182,74,0.6)'); gr.addColorStop(1, 'rgba(241,182,74,0)');
    g.fillStyle = gr; g.fillRect(0, 0, r * 2, r * 2);
    glowC = { c, ax: r, ay: r, k: K };
    return glowC;
  }

  // --- one frame ---
  const things = R.things;
  for (const t of things) t.phase ??= Math.floor(((t.x * 7 + t.y * 13) % 97) / 33);
  function thingPose(t, boil) {
    const [dr] = BOIL[boil];
    const base = pose(t.asset, { flip: t.flip, rot: t.rot }, true);
    if (!dr) return base;
    return pose(t.asset, { flip: t.flip, rot: t.rot + dr }) ?? base;
  }
  function draw(t, f) {
    const t0 = performance.now();
    frameNo++;
    budget = 5;
    if (frameNo % 120 === 0) forget();
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    // the ground: every visible tile (made now if it must be), then one more round the edge, ahead of need
    const i0 = Math.floor(view.x / TD), i1 = Math.floor((view.x + CW - 1) / TD), j0 = Math.floor(view.y / TD), j1 = Math.floor((view.y + CH - 1) / TD);
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) ctx.drawImage(tile(i, j, true), i * TD - view.x, j * TD - view.y);
    for (let j = j0 - 1; j <= j1 + 1 && budget > 0; j++) for (let i = i0 - 1; i <= i1 + 1 && budget > 0; i++) tile(i, j, false);

    // what stands, back to front, with the wanderer among them
    const wx0 = view.x / K - 40, wy0 = view.y / K - 40, wx1 = (view.x + CW) / K + 40, wy1 = (view.y + CH) / K + 60;
    const boilStep = Math.floor(t * 8);
    const hero = f.hero;
    let heroDone = !hero, covered = false;
    for (const th of things) {
      const a = th.asset;
      if (!heroDone && th.y > hero.y) { hero.draw(ctx, api, t); heroDone = true; }
      if (th.x + a.w < wx0 || th.x - a.w > wx1 || th.y - a.h * a.anchor[1] > wy1 || th.y + a.h * (1 - a.anchor[1]) + 20 < wy0) continue;
      const step = (boilStep + th.phase) % 3, [, bx, by] = BOIL[step];
      const p = thingPose(th, step);
      const bounce = f.bounce?.get(th.id);
      const bloom = th.kind === 'gram' && f.bloom != null ? t - f.bloom : null;
      const beat = th.kind === 'gram' && f.beat ? f.beat(t) : 0;
      if (bounce != null && t - bounce < 0.42) {
        const u = (t - bounce) / 0.42, s = Math.sin(u * Math.PI * 2.5) * (1 - u) * 0.07;
        blitScaled(p, th.x + bx, th.y + by, 1 - s * 0.6, 1 + s);
      } else if (bloom != null && bloom < 1.6) {
        const u = bloom / 1.6, s = Math.sin(u * Math.PI * 3) * (1 - u) * 0.1 + (1 - u) * 0.04;
        blitScaled(p, th.x, th.y, 1 + s, 1 + s * 1.2);
      } else if (beat > 0) {
        blitScaled(p, th.x + bx, th.y + by, 1 + beat * 0.012, 1 + beat * 0.022);
      } else blit(p, th.x, th.y, bx, by);
      if (th.kind === 'gram') dishes(th, f, t);
      if (heroDone && hero && th.kind !== 'portal' && th.y > hero.y && Math.abs(th.x - hero.x) < a.w * 0.45 && th.y - a.h * a.anchor[1] * 0.9 < hero.y - 20 && th.y - hero.y < a.h) covered = true;
    }
    if (!heroDone) hero.draw(ctx, api, t);
    if (covered) { ctx.globalAlpha = 0.38; hero.draw(ctx, api, t, true); ctx.globalAlpha = 1; }
    if (f.after) {
      ctx.setTransform(K, 0, 0, K, -view.x, -view.y);
      f.after(ctx, api, t);
      ctx.setTransform(1, 0, 0, 1, 0, 0);
    }
    stats.ms = performance.now() - t0;
  }
  // the Gramophone's three plinth dishes: what is on each, lit from below; just placed, it drops in and squashes
  const PARTS3 = ['bed', 'drums', 'bass'];
  function dishes(th, f, t) {
    const a = th.asset, g0 = glow();
    a.slots.forEach(([sx, sy], i) => {
      const part = PARTS3[i], key = f.plinths?.[part];
      if (!key) return;
      const x = th.x - a.anchor[0] * a.w + sx * a.w, y = th.y - a.anchor[1] * a.h + sy * a.h;
      ctx.globalCompositeOperation = 'lighter';
      ctx.globalAlpha = 0.5 + 0.2 * Math.sin(t * 2.4 + i * 2) + (f.beat ? f.beat(t) * 0.3 : 0);
      blit(g0, x, y);
      ctx.globalAlpha = 1; ctx.globalCompositeOperation = 'source-over';
      const it = art.artifacts[key], k = Math.min(1, (a.h * 0.17) / it.h);
      const p = pose(it, { sx: k, sy: k, rot: (i - 1) * 0.06, pin: true }, true);
      const s0 = f.settle?.get(part);
      if (s0 != null && t - s0 < 0.5) {
        const u = (t - s0) / 0.5, drop = u < 0.35 ? (1 - u / 0.35) ** 2 * 70 : 0, sq = u >= 0.35 ? Math.sin(((u - 0.35) / 0.65) * Math.PI * 2) * (1 - u) * 0.25 : 0;
        blitScaled(p, x, y - drop, 1 + sq, 1 - sq);
      } else blit(p, x, y);
    });
  }
  /** Where an artifact rests on the Gramophone, for a part. */
  function dish(part) {
    const th = R.gram, a = th.asset, [sx, sy] = a.slots[PARTS3.indexOf(part)];
    return [th.x - a.anchor[0] * a.w + sx * a.w, th.y - a.anchor[1] * a.h + sy * a.h];
  }

  const toScreen = (x, y) => [(x * K - view.x) / dpr, (y * K - view.y) / dpr];
  const toWorld = (cx, cy) => [(cx * dpr + view.x) / K, (cy * dpr + view.y) / K];
  /** Makes the poses and tiles round a point now (the first frame should not stutter). */
  function warm(x, y) {
    look(x, y);
    const i0 = Math.floor(view.x / TD), i1 = Math.floor((view.x + CW - 1) / TD), j0 = Math.floor(view.y / TD), j1 = Math.floor((view.y + CH - 1) / TD);
    for (let j = j0; j <= j1; j++) for (let i = i0; i <= i1; i++) tile(i, j, true);
    const wx0 = view.x / K - 200, wy0 = view.y / K - 200, wx1 = (view.x + CW) / K + 200, wy1 = (view.y + CH) / K + 300;
    for (const th of things) if (th.x > wx0 && th.x < wx1 && th.y > wy0 && th.y < wy1) for (const [dr] of BOIL) pose(th.asset, { flip: th.flip, rot: th.rot + dr }, true);
  }
  /** Forgets what was drawn from an asset (its image arrived), or the whole ground. */
  function refresh(a) {
    if (a.ground) { regrind(); return; }
    for (const k of [...flats.keys()]) if (k.startsWith(`${a.key}:`)) flats.delete(k);
    for (const k of [...poses.keys()]) if (k.startsWith(`${a.key}:`)) poses.delete(k);
  }

  const api = {
    resize, look, draw, pose, blit, blitScaled, toScreen, toWorld, warm, refresh, dish, view, stats,
    get K() { return K; }, get zoom() { return zoom; }, get dpr() { return dpr; }, get size() { return [CW, CH]; },
    material,
  };
  resize();
  return api;
}
