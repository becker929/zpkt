// The art pack (art/manifest.json, docs/rummage.md "Art (as made)") as assets the scene can draw. Every asset has
// a world size (half its file's pixels, times a scale for the megaliths), an anchor (its base, as fractions of the
// sprite), a foot (its collision radius, as a fraction of its width) and a way to draw itself: the decoded image once
// it is in, the placeholder from paper.js until then, or for good when the manifest or the file is missing. So the
// page works whichever lands first.
//
//   const art = await loadArt('art/')     the assets, from the manifest's sizes or the defaults
//   art.loaded                            resolves when every image has arrived or failed
//   art.onImage(fn)                       fn(asset) as each image arrives (the scene redraws what used it)
//   asset.draw(g)                         draws it at its world size with its top left at (0, 0)
//   art.sleeve(combo) / art.title         the record sleeve for a finished short, the arrival title (URLs or null)
import { DEFAULT_PROP_IDS, PAINT, setMaterial } from './paper.js';
import { PARTS } from './region.js';

// file pixels (as in the manifest) and feet, for when the manifest is missing
const PROP_SIZES = {
  teapot: [250, 260, 0.34], birdcage: [210, 330, 0.32], suitcase: [300, 220, 0.42], clock: [190, 420, 0.3],
  typewriter: [280, 230, 0.42], lamp: [170, 400, 0.2], oilcan: [190, 250, 0.34], kettle: [220, 220, 0.36],
  boot: [180, 200, 0.36], wheel: [260, 300, 0.24], crate: [260, 240, 0.44], globe: [200, 300, 0.3],
};
export const HORN = [0.42, 0.2];          // where the Gramophone's horn opens, as fractions of its sprite
export const SLOTS = [[0.25, 0.8], [0.5, 0.85], [0.75, 0.8]];
// The machines stand three to four times the wanderer's height (the art's mockup); the Gramophone a little less.
const SCALE = { machine: 1.25, gramophone: 1.12 };

function asset(key, [w, h], { anchor = [0.5, 0.95], foot = 0, file = null, scale = 1, paint }) {
  return {
    key, w: (w / 2) * scale, h: (h / 2) * scale, anchor, foot, file, img: null, v: 0, paint,
    draw(g) { if (this.img) g.drawImage(this.img, 0, 0, this.w, this.h); else this.paint(g, this.w, this.h); },
  };
}
const size = (e, fallback) => (e && e.w > 0 && e.h > 0 ? [e.w, e.h] : fallback);
/** An image decoded once, off the main thread, into a bitmap the canvas draws as it is: WebKit may drop an <img>'s
 * decoded pixels under memory pressure and decode it again in the middle of a frame the next time it's drawn. */
async function bitmap(img) {
  if (!img) return null;
  try { return await createImageBitmap(img); } catch { return img; }
}

/** The assets: the manifest's where it has them, placeholders of the same size where it doesn't. */
export async function loadArt(base = 'art/') {
  let m = null;
  try {
    const r = await fetch(`${base}manifest.json`, { cache: 'no-cache' });
    if (r.ok) m = await r.json();
  } catch { /* no art yet: placeholders */ }
  m ??= {};
  const listeners = new Set();
  const art = { manifest: m, onImage: (fn) => listeners.add(fn), loaded: null };

  const list = Array.isArray(m.props) && m.props.length ? m.props.filter((p) => p?.id) : DEFAULT_PROP_IDS.map((id) => ({ id }));
  const props = list.map((p) => {
    const [w, h, foot] = PROP_SIZES[p.id] ?? [240, 260, 0.3];
    const a = asset(`prop:${p.id}`, size(p, [w, h]), { anchor: p.anchor ?? [0.5, 0.94], foot: p.foot ?? foot, file: p.file, paint: (g, W, H) => PAINT.prop(g, W, H, p.id) });
    a.id = p.id;
    return a;
  });

  const machines = {};
  for (const part of PARTS) {
    const e = m.machines?.[part];
    machines[part] = asset(`machine:${part}`, size(e, [360, 620]), { anchor: e?.anchor ?? [0.5, 0.96], foot: e?.foot ?? 0.4, file: e?.file, scale: SCALE.machine, paint: (g, w, h) => PAINT.machine(g, w, h, part) });
    machines[part].panel = e?.panel ? base + e.panel : null;
  }
  // the Gramophone, with its three plinth dishes: `slots` are where an artifact's base rests, bed, drums, bass
  const ge = m.gramophone;
  const gramophone = asset('gramophone', size(ge, [600, 640]), { anchor: ge?.anchor ?? [0.5, 0.95], foot: ge?.foot ?? 0.42, file: ge?.file, scale: SCALE.gramophone, paint: (g, w, h) => PAINT.gramophone(g, w, h, ge?.horn ?? HORN) });
  gramophone.slots = Array.isArray(ge?.slots) && ge.slots.length === 3 ? ge.slots : SLOTS;
  gramophone.horn = ge?.horn ?? HORN;
  const te = m.portal;
  const portal = asset('portal', size(te, [300, 360]), { anchor: te?.anchor ?? [0.5, 0.95], foot: te?.foot ?? 0.3, file: te?.file, paint: PAINT.portal });
  const artifacts = {};
  for (const part of PARTS) for (const id of [1, 2, 3]) {
    const key = `${part}-${id}`, e = m.artifacts?.[key];
    artifacts[key] = asset(`artifact:${key}`, size(e, [160, 160]), { anchor: e?.anchor ?? [0.5, 0.94], file: e?.file, paint: (g, w, h) => PAINT.artifact(g, w, h, part, id) });
    artifacts[key].url = e?.file ? base + e.file : null;
  }
  // the wanderer: three views (the side faces right; it is mirrored for the left), and, if the pack has them, two
  // walk frames per view
  const hero = {};
  for (const face of ['front', 'back', 'side']) {
    const e = m.hero?.[face];
    const opts = { anchor: e?.anchor ?? [0.5, 0.97], file: e?.file, paint: (g, w, h) => PAINT.hero(g, w, h, face) };
    hero[face] = asset(`hero:${face}`, size(e, [140, 230]), opts);
    hero[face].neck = e?.neck ?? [0.5, 0.37];                                         // where the scarf's tail is tied
    hero[face].walk = Array.isArray(e?.walk) ? e.walk.filter((f) => f?.file).map((f, i) =>
      asset(`hero:${face}:walk${i}`, size(f, size(e, [140, 230])), { anchor: f.anchor ?? opts.anchor, file: f.file, paint: opts.paint })) : [];
  }
  const sign = asset('sign', [270, 230], { anchor: [0.5, 0.97], foot: 0.05, paint: (g, w, h) => PAINT.sign(g, w, h, sign.arms) });
  sign.arms = [];
  const sleeves = m.sleeves && typeof m.sleeves === 'object' ? m.sleeves : {};
  // the easel by the Gramophone, which holds the latest sleeve once the short is finished
  const easel = asset('easel', [270, 350], { anchor: [0.5, 0.97], foot: 0.16, paint: (g, w, h) => PAINT.easel(g, w, h, easel.sleeve) });
  Object.assign(easel, { sleeve: null, combo: null });
  Object.assign(art, {
    props, machines, gramophone, portal, artifacts, hero, sign, easel, path: null, ground: [],
    pathAspect: m.path?.w > 0 && m.path?.h > 0 ? m.path.h / m.path.w : null,
    sleeve: (combo) => (sleeves[combo]?.file ? { url: base + sleeves[combo].file, file: sleeves[combo].file } : null),
    title: m.title?.file ? { url: base + m.title.file, w: m.title.w, h: m.title.h } : null,
    // which materials the ground has: the base sheet, and what big and small patches are cut from
    floor: { base: 'kraft', big: ['cork', 'newsprint', 'fabric', 'tin', 'card', 'wood', 'map'], small: ['map', 'newsprint', 'cork'] },
  });

  // --- the files: each one replaces its placeholder as it decodes ---
  const load = (file) => new Promise((resolve) => {
    const img = new Image();
    img.decoding = 'async';
    img.onload = () => (img.decode ? img.decode().catch(() => null) : Promise.resolve()).then(() => resolve(img));
    img.onerror = () => resolve(null);
    img.src = base + file;
  });
  const jobs = [];
  const take = (a) => {
    if (!a.file) return;
    jobs.push(load(a.file).then(bitmap).then((img) => {
      if (!img) return;
      a.img = img; a.v++;
      for (const fn of listeners) fn(a);
    }));
  };
  [...props, ...Object.values(machines), gramophone, portal, ...Object.values(artifacts)].forEach(take);
  for (const h of Object.values(hero)) { take(h); h.walk.forEach(take); }
  // the ground: ground-b (cork and felt) is the calm base; ground-a (kraft) is cut into big patches, ground-c (sheet
  // music and maps) is busy, so only into small ones. Without the pack, the materials are paper.js's.
  const grounds = Array.isArray(m.ground) ? m.ground.filter((e) => e?.file) : [];
  if (grounds.length) {
    const byId = Object.fromEntries(grounds.map((e) => [e.id, e]));
    const baseG = byId['ground-b'] ?? grounds[0];
    const rest = grounds.filter((e) => e !== baseG);
    const big = rest.filter((e) => e.id !== 'ground-c'), small = rest.filter((e) => e.id === 'ground-c');
    art.floor = { base: `art:${baseG.id}`, big: (big.length ? big : rest).map((e) => `art:${e.id}`), small: (small.length ? small : rest).map((e) => `art:${e.id}`) };
    for (const e of grounds) {
      jobs.push(load(e.file).then(bitmap).then((img) => {
        if (!img) return;
        setMaterial(`art:${e.id}`, img);
        art.ground.push(e.id);
        for (const fn of listeners) fn({ key: `ground:${e.id}`, ground: true });
      }));
    }
  }
  if (m.path?.file) {
    jobs.push(load(m.path.file).then(bitmap).then((img) => {
      if (!img) return;
      art.path = { img };
      for (const fn of listeners) fn({ key: 'path', ground: true });
    }));
  }
  art.loaded = Promise.all(jobs);
  /** Puts a finished short's sleeve on the easel (null takes it off); resolves when it's there. */
  art.setEasel = async (combo) => {
    if (easel.combo === combo) return;
    easel.combo = combo;
    const s = combo ? art.sleeve(combo) : null;
    const img = s ? await load(s.file) : null;
    if (easel.combo !== combo) return;
    easel.sleeve = img ? await bitmap(img) : null;
    easel.v++;
    for (const fn of listeners) fn(easel);
  };
  return art;
}
