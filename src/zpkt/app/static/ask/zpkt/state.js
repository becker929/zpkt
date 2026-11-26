// What the composer's parts share with the page: how to call the API, how to say something, which session is open.

export const S = {
  api: null,             // (path, opts) => Promise<json>, from the page
  toast: (m) => console.log(m),
  sessionId: null,
};

/** A path an agent wrote, as a URL the page can fetch (relative paths resolve in the session's folder). */
export function mediaUrl(src) {
  if (/^(https?:|data:|blob:)/i.test(src) || src.startsWith('/app/ask/api/')) return src;
  return S.sessionId ? `/app/ask/api/sessions/${S.sessionId}/file?path=${encodeURIComponent(src)}` : src;
}
