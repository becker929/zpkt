// Post text for replies: facets (links, mentions) by UTF-8 byte offsets, the 300-grapheme limit, reply refs,
// and scrubbing what the model writes so the bot can't be talked into posting links or tagging people. The only
// links and mentions in a reply are the bot's own: a piece's page and a remix's credit.

const enc = new TextEncoder();
const seg = new Intl.Segmenter('en', { granularity: 'grapheme' });

export const POST_LIMIT = 300;
export const graphemes = (s) => [...seg.segment(s)].length;

/** At most n graphemes, ending in an ellipsis when cut. */
export function clip(s, n) {
  const g = [...seg.segment(s)].map((x) => x.segment);
  return g.length <= n ? s : g.slice(0, Math.max(0, n - 1)).join('').trimEnd() + '…';
}

/** Model-written text for a post or a title: no links, no @mentions, no line breaks beyond one, trimmed. */
export function scrub(s) {
  return String(s ?? '')
    .replace(/https?:\/\/\S+/gi, '')
    .replace(/\b[\w-]+(\.[\w-]+)+\/\S*/g, '') // bare domain/path links
    .replace(/(^|[^\w])@(?=[\w])/g, '$1') // a handle loses its @ (no mention, no notification) but keeps its words
    .replace(/[\u0000-\u0009\u000b-\u001f\u007f‪-‮⁦-⁩]/g, '') // control and bidi override characters
    .replace(/\n{2,}/g, '\n')
    .replace(/[ \t]{2,}/g, ' ')
    .trim();
}

/** Text and facets from parts: plain strings, {link, text?} and {mention: handle, did}. */
export function rich(parts) {
  let text = '';
  const facets = [];
  for (const p of parts) {
    if (typeof p === 'string') { text += p; continue; }
    const start = enc.encode(text).length;
    text += p.mention ? `@${p.mention}` : (p.text ?? p.link);
    const end = enc.encode(text).length;
    facets.push({
      index: { byteStart: start, byteEnd: end },
      features: [p.mention ? { $type: 'app.bsky.richtext.facet#mention', did: p.did } : { $type: 'app.bsky.richtext.facet#link', uri: p.link }],
    });
  }
  return { text, facets };
}

/** The reply's thread refs: its parent is the request, its root the request's own root (or the request). */
export function replyRefs(req) {
  return { root: { uri: req.root_uri ?? req.uri, cid: req.root_cid ?? req.cid }, parent: { uri: req.uri, cid: req.cid } };
}

/** The reply to a finished piece: the composer's line, then the title and version (linked when the piece has a
 * page), then for a remix who made the original (a mention, so they hear about it), within 300 graphemes. */
export function pieceReply({ line, title, version = 1, url = null, credit = null }) {
  const shown = url ? url.replace(/^https?:\/\//, '') : null;
  const name = (t) => `“${t}” v${version}`;
  const tail = (t) => ['\n\n', name(t), ...(url ? [' → ', { link: url, text: shown }] : []), ...(credit ? [', a remix of ', `“${credit.title}” by `, { mention: credit.handle, did: credit.did }] : [])];
  const tailLen = (t) => graphemes(`\n\n${name(t)}${url ? ` → ${shown}` : ''}${credit ? `, a remix of “${credit.title}” by @${credit.handle}` : ''}`);
  if (credit && tailLen(title) > POST_LIMIT - 40) credit = { ...credit, title: clip(credit.title, 30) };
  const t = tailLen(title) > POST_LIMIT - 20 ? clip(title, 40) : title;
  const body = clip(scrub(line) || 'Your piece is ready.', POST_LIMIT - tailLen(t));
  return rich([body, ...tail(t)]);
}

/** A reply that is only words (a decline, a question, a limit), within 300 graphemes. */
export function plainReply(text) {
  return rich([clip(scrub(text), POST_LIMIT)]);
}
