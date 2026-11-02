// Who gets a like, an answer and music. Three gates: before the like (the bot itself, the allow list, people
// posting at it over and over: these are set aside without a word), before the ack (a hard spending stop), and
// canMake, worked out before the ack so its reply can say truthfully whether music was accepted: new pieces and
// remixes per person per day, revisions per person per day, booth renders per day and the day's budget.

export const TEXT = {
  pieces: "You've had your pieces for today. Ask me again tomorrow, or reply under one of them and I'll make the next version.",
  revisions: "That's all the new versions I can make for you today. Reply again tomorrow and I'll carry on.",
  day: "The booth has made all the music it can for today. Ask me again tomorrow!",
  notAllowed: "I'm only making music for a few friends while I'm new. Soon, I hope!",
};

export const allowed = (cfg, req) => cfg.open || cfg.allow.some((a) => a.toLowerCase() === String(req.handle).toLowerCase() || a === req.author);

/** null, or {status, note} to set the post aside unliked and unanswered. Call it after the post is stored (it counts itself). */
export function beforeLike(req, { cfg, store, self }) {
  if (req.author === self) return { status: 'skipped', note: 'the bot itself' };
  if (!allowed(cfg, req)) return { status: 'skipped', note: 'not on the allow list' };
  if (store.mentionsFrom(req.author, req.day) > cfg.mentionsPerUserPerDay) return { status: 'skipped', note: 'too many mentions today' };
  return null;
}

/** null, or {status, note}: liked, but no Claude call at all. */
export function beforeAck(req, { cfg, store }) {
  if (store.spentToday(req.day) >= cfg.dollarsPerDay * 1.25) return { status: 'skipped', note: 'over the hard spending stop' };
  return null;
}

/** Could this person have music of this kind (piece, revise or remix) made now? {ok: true} or {ok: false, reason,
 * text}. `reserved` counts music that acks still in flight were offered, so a burst can't all be promised the day's
 * last render. */
export function canMake(req, { cfg, store }, kind = 'piece', reserved = 0) {
  if (!allowed(cfg, req)) return { ok: false, reason: 'not_allowed', text: TEXT.notAllowed };
  if (kind === 'revise') {
    if (store.revisionsFor(req.author, req.day) >= cfg.revisionsPerUserPerDay) return { ok: false, reason: 'revisions_per_user', text: TEXT.revisions };
  } else if (store.piecesFor(req.author, req.day) >= cfg.piecesPerUserPerDay) return { ok: false, reason: 'pieces_per_user', text: TEXT.pieces };
  if (store.rendersToday(req.day) + reserved >= cfg.rendersPerDay) return { ok: false, reason: 'renders_per_day', text: TEXT.day };
  if (store.spentToday(req.day) >= cfg.dollarsPerDay) return { ok: false, reason: 'dollars', text: TEXT.day };
  return { ok: true };
}
