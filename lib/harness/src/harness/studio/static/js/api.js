// The studio's HTTP API. Paths are relative to where the page is served (/studio/), found from this
// module's own URL (/studio/static/js/api.js).

export const BASE = new URL('../../', import.meta.url).pathname.replace(/\/$/, '');

async function call(path, options = {}) {
  const res = await fetch(`${BASE}${path}`, { credentials: 'same-origin', ...options });
  const body = await res.json().catch(() => ({}));
  if (!res.ok) throw Object.assign(new Error(body.error || `${res.status} ${res.statusText}`), { status: res.status });
  return body;
}

/** A page of history, oldest first: {items, has_more}. Without `before`, the newest page. */
export function messages({ before = null, limit }) {
  const q = new URLSearchParams({ limit: String(limit) });
  if (before != null) q.set('before', String(before));
  return call(`/api/messages?${q}`);
}

/** One message by seq (for `play` of a render that is not in the chat window). */
export async function message(seq) {
  const { items } = await messages({ before: seq + 1, limit: 1 });
  return items.find((m) => m.seq === seq) ?? null;
}

/** The last turns' timing marks, newest first: [{turn, at, marks: [{name, ms, source, at, ...}]}]. */
export function timings(turns = 8) {
  return call(`/api/timings?turns=${turns}`);
}

export function newConversation() {
  return call('/api/conversation', { method: 'POST' });
}
