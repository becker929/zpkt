// Settings and secrets for the music bot. Both live outside the repo, in MUSIC_BOT_HOME
// (default ~/_agent_scratch/music-bot): config.json (anything below can be overridden there) and
// secrets.json ({BSKY_IDENTIFIER, BSKY_APP_PASSWORD, ANTHROPIC_API_KEY, BOOTH_TOKEN}; the same names in
// the environment win). The state database, the log, the downloaded videos and the outbox go there too.

import { existsSync, mkdirSync, readFileSync } from 'node:fs';
import { homedir } from 'node:os';
import { join } from 'node:path';
import { ACK_DEFAULTS } from './ack.mjs';

export const HOME = process.env.MUSIC_BOT_HOME || join(homedir(), '_agent_scratch', 'music-bot');

export const DEFAULTS = {
  boothBase: 'http://127.0.0.1:8794', // the booth (contrib/booth), as Anthony, on loopback only
  bskyService: 'https://bsky.social', // where the bot logs in; posts go to its own PDS (from the session)
  videoService: 'https://video.bsky.app',
  open: false, // false: only accounts in `allow` get music (everyone else is ignored); true: anyone who asks
  allow: ['anthonybecker.bsky.social'],
  piecesPerUserPerDay: 2, // new pieces and remixes per person per day (UTC)
  revisionsPerUserPerDay: 6, // next versions per person per day (UTC)
  rendersPerDay: 60, // booth jobs for everyone (about an hour of Live)
  mentionsPerUserPerDay: 30, // past this a person's posts are neither liked nor answered for the day
  dollarsPerDay: 15, // Claude spend (composer and acks); at the cap no more music today, at 1.25x no more acks
  pollSeconds: 2, // listNotifications this often, so a mention is liked within a few seconds
  jobPollSeconds: 5, // GET /v1/jobs/{id} this often while the booth works
  boothDownMinutes: 10, // the booth not answering this long while a job is polled: try the request again later
  heldHours: 24, // a held job not finished after this long gets the sorry
  tellWaitSeconds: 60, // a closed booth or a full queue asking for at least this wait is told to the friend, once
  ackConcurrency: 4, // acks in flight at once (one at a time per person)
  ackRetryMinutes: [0.5, 2, 10], // after Claude is overloaded or down during an ack: the waits before each try again
  maxAgeHours: 24, // posts older than this when first seen (say after the Mac was off) are left alone
  dryRun: true, // true: read Bluesky but never write to it; each reply goes to outbox/ instead
  model: 'claude-opus-5-5',
  composeEffort: 'high',
  cacheTtl: '1h', // the composer's prompt is the same for every request; requests are sporadic, so keep it an hour
  retryMinutes: [10, 30, 90], // after Claude or the booth is down: the waits before each try again, then it fails
  ntfyTopic: null, // set in config.json: declined posts and failed requests are reported to the owner there
  fixRounds: 3, // drafts the composer gets to fix what POST /v1/check finds
  measureRounds: 1, // render-side revisions per version, when measure.json flags a problem (each costs Live time)
  video: { size: [1080, 1920] },
  pieceUrl: null, // e.g. "https://anthonybecker.me/tunes/{job}": a link under each piece (none by default)
  ...ACK_DEFAULTS, // ackModel, chatPerUserPerDay, chatPerHour: the ack's model and its own rate limits (ack.mjs)
};

export function loadConfig(overrides = {}) {
  const file = join(HOME, 'config.json');
  const saved = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
  return { ...DEFAULTS, ...saved, ...overrides, video: { ...DEFAULTS.video, ...saved.video, ...overrides.video } };
}

export function loadSecrets() {
  const file = join(HOME, 'secrets.json');
  const saved = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
  const pick = (k) => process.env[k] || saved[k] || '';
  return { BSKY_IDENTIFIER: pick('BSKY_IDENTIFIER'), BSKY_APP_PASSWORD: pick('BSKY_APP_PASSWORD'), ANTHROPIC_API_KEY: pick('ANTHROPIC_API_KEY'), BOOTH_TOKEN: pick('BOOTH_TOKEN') };
}

export function ensureHome(dir = HOME) {
  for (const d of [dir, join(dir, 'renders'), join(dir, 'outbox')]) mkdirSync(d, { recursive: true });
  return dir;
}

/** The day limits count in: the UTC date. */
export const today = (now = Date.now()) => new Date(now).toISOString().slice(0, 10);
