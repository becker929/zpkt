// The collage's own state: which tape is in, where its cue is, the slicer's pattern, the bed's clips, the
// resamples. It lives in this module, so it outlasts a tab switch; the layout (not the audio) is kept in this
// phone's storage. Resampled audio lives only in memory: a reload drops it and any bed clip made from it.

const KEY = 'hw002-lab:collage:v1';

export const state = {
  mode: 'grain',
  sel: 'src-3',
  cue: {},              // source id -> seconds: where audition, the slicer and the bed's next drop start
  win: {},              // source id -> {start, len} seconds: the grain view's window
  pattern: Array.from({ length: 16 }, (_, i) => i),   // step -> slice (or -1)
  vel: Array(16).fill(0.9),
  seq: false,
  rec: false,
  bed: [],              // {id, src, lane, start, len (16ths), off (s), st, rev, gain}
  bedPrev: null,
  zoom: 1,
  scroll: 0,
  loaded: null,         // what a tap on the bed drops: {src, off, len, st, rev}
  lastPad: 0,
  rs: [],               // resamples: {id, name, buffer, bars, made}
  rsN: 0,
  clipN: 0,
};

let timer = 0;
let loaded = false;

export function loadState() {
  if (loaded) return state;
  loaded = true;
  try {
    const s = JSON.parse(localStorage.getItem(KEY) || 'null');
    if (!s) return state;
    for (const k of ['mode', 'sel', 'cue', 'win', 'pattern', 'vel', 'zoom', 'scroll', 'lastPad', 'clipN']) if (s[k] != null) state[k] = s[k];
    if (Array.isArray(s.bed)) state.bed = s.bed.filter((c) => !String(c.src).startsWith('rs-'));
    if (s.loaded && !String(s.loaded.src).startsWith('rs-')) state.loaded = s.loaded;
    if (String(state.sel).startsWith('rs-')) state.sel = 'src-3';
  } catch { /* a broken save starts clean */ }
  return state;
}

export function saveState() {
  clearTimeout(timer);
  timer = setTimeout(() => {
    try {
      const { mode, sel, cue, win, pattern, vel, bed, zoom, scroll, loaded: ld, lastPad, clipN } = state;
      localStorage.setItem(KEY, JSON.stringify({
        mode, sel: String(sel).startsWith('rs-') ? 'src-3' : sel, cue, win, pattern, vel, zoom, scroll, lastPad, clipN,
        bed: bed.filter((c) => !String(c.src).startsWith('rs-')),
        loaded: ld && !String(ld.src).startsWith('rs-') ? ld : null,
      }));
    } catch { /* private mode: the layout lives for this visit */ }
  }, 300);
}
