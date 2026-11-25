// Shared state for the surface system: which session is open, which card is armed, and who to tell when
// something changes. Modules import S and call emit(); the page subscribes with onChange().

export const S = {
  api: null,             // (path, opts) => Promise<json>, from the page
  toast: (m) => console.log(m),
  sessionId: null,
  states: {},            // saved values/peaks per surface id, for the open session
  cards: new Map(),      // surface id -> card
  active: null,          // id of the armed card
};

const listeners = new Set();
export const onChange = (fn) => { listeners.add(fn); return () => listeners.delete(fn); };
export const emit = () => { for (const fn of listeners) try { fn(); } catch (e) { console.error(e); } };

/** Per-device settings (MIDI map, which card was armed). Never required: private windows may refuse storage. */
export const local = {
  get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

/** A path an agent wrote, as a URL the page can fetch (relative paths resolve in the session's folder). */
export function mediaUrl(src) {
  if (/^(https?:|data:|blob:)/i.test(src) || src.startsWith('/app/ask/api/')) return src;
  return S.sessionId ? `/app/ask/api/sessions/${S.sessionId}/file?path=${encodeURIComponent(src)}` : src;
}
