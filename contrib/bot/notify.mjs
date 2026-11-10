// Tells the owner when something needs a human: a declined post (its like taken back) or a request that failed.
// Through ntfy (cfg.ntfyTopic, in the bot's own config.json, never the repo: anyone with the topic can post to it).
// Never throws and never waits long; with no topic set it only logs.

export async function report({ cfg, log, dryRun }, { title, text, url }) {
  log('report', { title, text: text.slice(0, 200), url });
  if (!cfg.ntfyTopic) return false;
  try {
    const r = await fetch(`${cfg.ntfyUrl ?? 'https://ntfy.sh'}/${encodeURIComponent(cfg.ntfyTopic)}`, {
      method: 'POST', body: text.slice(0, 1000), signal: AbortSignal.timeout(5000),
      headers: { Title: `${dryRun ? '[dry run] ' : ''}${title}`.replace(/[^\x20-\x7e]/g, '?').slice(0, 120), ...(url ? { Click: url } : {}), Tags: 'robot' },
    });
    return r.ok;
  } catch (e) {
    log('report failed', { error: e.message });
    return false;
  }
}

/** The bsky.app link for a post's at:// URI. */
export const postLink = (uri) => {
  const m = /^at:\/\/([^/]+)\/app\.bsky\.feed\.post\/([^/]+)$/.exec(uri);
  return m ? `https://bsky.app/profile/${m[1]}/post/${m[2]}` : null;
};
