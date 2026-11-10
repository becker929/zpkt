# The music bot

A Bluesky account that makes short pieces of music for friends. Mention it with an idea and it replies with a
vertical video of a new piece: the audio over a piano roll of its score. Reply under one of its pieces and it makes
the next version. Quote a piece and mention it, and it makes a remix that starts from that score and credits it.
It runs on this Mac (`main.mjs`, a Node program that keeps running) because the music is made in Ableton Live
here, through the booth (`contrib/booth`). The design is `contrib/docs/design/bluesky-bot.md`; this follows the Room World room bot
(`~/world2/bot`) wherever it can.

Three stages run side by side in the one process, so a minute in Live never holds up anyone else's like or answer:

```
intake (every 2 s)          ack (seconds, a few at once)                         build (one at a time, minutes)
post ──► like ──► limits ──► Acker (Claude Haiku): piece / revise / chat / ──► queue ──► compose (Claude, high effort)
         │                   decline / ignore; "On it!" or a chat reply            │      ▲         │
         └ own posts, old,                                                         │      └─ fix ◄── POST /v1/check
           not allowed, too many:                                                  ▼                (up to 3 rounds)
           no like, no reply         reply ◄── upload video.mp4 ◄── GET /v1/jobs/{id} every 5 s ◄── POST /v1/jobs
                                                                     └ measure.flags? one revision, the better kept
```

- **Intake and like:** the bot account's notifications (`listNotifications`) every 2 s (`pollSeconds`): mentions;
  replies whose parent is one of the bot's own posts; and quotes of the bot's own posts that also mention it. Each
  new one is liked at once, before any Claude call: in the tests about 1 s after it was posted, while a piece was
  being made. Not liked or answered: the bot's own posts, posts older than 24 h when first seen, replies to anyone
  else, quotes that don't mention the bot, people past `mentionsPerUserPerDay`, and (while `open` is false) anyone
  not on `allow`. Intake also works out which piece a post is about: the one it quotes (a remix), the one it
  replies under, or the newest piece in its thread (a revision).
- **Ack:** right after the like (and the posts it replies to or quotes, read for context), the limits are worked out
  (`canMake`: new pieces and remixes per person, revisions per person, renders and dollars per day) and the Acker
  (`ack.mjs`, a quick Haiku call) answers piece, revise (only under a piece), chat, decline (covers of a specific
  song, lyrics that hurt someone, posting things for people) or ignore. The bot overrules music the limits don't
  allow, and a "revise" with nothing to revise becomes a new piece. It can look up the person's past requests and
  whether the booth is open, nothing else. Acks in flight count against the day's renders.
- **Compose:** Claude writes the score in the booth's own shape (palette instruments, short patterns, a song order,
  a mix), a line for the reply and alt text. The system prompt is fixed text plus the booth's live guide
  (`GET /v1/guide`: the palette's instruments, ranges and macros, the return settings, the rules, the limits and two
  example scores), cached for an hour. The structured-output schema is the guide's score schema with the keywords
  structured outputs don't take (bounds, lengths, patterns, defaults) moved into the descriptions (`composeSchema` in
  `prompts.mjs`); the booth's check enforces all of them anyway. A revision gets the parent score and the
  instruction; a remix gets the quoted score.
- **Check:** `POST /v1/check` is free and never touches Live. What it finds goes back to the composer, up to 3 rounds.
- **Render:** `POST /v1/jobs` with the idempotency key `<post uri>#v<version>` (so a bot that crashed mid-request asks
  for the same job again, never a second render), then `GET /v1/jobs/{id}` every 5 s. If `measure.flags` is not empty
  (a part you can't hear on a phone, no contrast between sections), the flags go back to the composer once and the
  revision renders under `<key>+1`; the render with fewer flags is kept. Check rounds are free; render rounds cost
  Live time, so there is only one.
- **When the booth says not now:** `503 closed` and `429 queue_full` put the request back in the queue until
  `retry_in_s`, and the friend is told once that the piece is waiting (when the wait is a minute or more). A `held`
  job (the booth stopped itself on a surprise) is told once as a hiccup on the bot's side and polled until it
  finishes. `failed` with `retryable: false` gets a sorry; a retryable failure goes back in line and is sent again
  under `<key>~<n>`. The booth not answering for 10 minutes while a job runs is tried again later (10, 30, 90 min).
- **Reply:** threaded under the request, with the booth's `video.mp4` uploaded through Bluesky's video service (the
  booth's `still.jpg` if the account can't post video, or the booth made none), alt text, the title and version, a
  link facet when `pieceUrl` is set, and for a remix a mention of whoever made the original. The model's words lose
  links and @mentions first (`richtext.mjs` `scrub`).
- **bot.db keeps every version:** the `pieces` table has a row per booth job with its key, score JSON, parent key,
  job id, state, measurements and, for the version that was posted, the reply's post uri (which is how a reply or a
  quote finds it later).

## Setting it up (the owner)

1. **Create the account** on Bluesky, e.g. `tunes.anthonybecker.me`, and confirm its email (only confirmed accounts
   post video). Give it a bio that says it's a bot and who runs it.
2. **App password:** signed in as the bot, Settings, Privacy and security, App passwords, Add. Leave direct messages off.
3. **Claude:** a workspace of its own in the Anthropic Console (e.g. `music-bot`) with a monthly spend limit, and an API
   key made in that workspace.
4. **The booth:** set it up as `contrib/booth` says; it keeps its token in your Keychain as `zpkt-booth-token`.
5. **Secrets:** `node contrib/bot/secrets.mjs` asks for the handle, app password, Anthropic key and booth token (`zb1_...`),
   with the typing hidden, checks each looks right and writes `~/_agent_scratch/music-bot/secrets.json` (0600).
   Don't paste them into chats or the terminal's command line.
6. **Check:** `node contrib/bot/main.mjs --check` logs in to Bluesky and the booth and reports the handle, whether the email is
   confirmed, today's video allowance, whether the booth is open, and the mode.

Settings go in `~/_agent_scratch/music-bot/config.json` (any of `DEFAULTS` in `config.mjs`; `MUSIC_BOT_HOME` moves
the folder):

| Setting | Default | |
|---|---|---|
| `dryRun` | `true` | reads Bluesky but never writes to it; each reply goes to `outbox/` as JSON (the booth still renders) |
| `open`, `allow` | `false`, `["anthonybecker.bsky.social"]` | `false`: only accounts in `allow` (handles or DIDs) get answers. Recommended: stay friends-only |
| `piecesPerUserPerDay`, `revisionsPerUserPerDay` | 2, 6 | per person per UTC day; a remix counts as a piece |
| `rendersPerDay`, `dollarsPerDay` | 60, 15 | booth jobs and Claude spend for everyone; at 1.25x the dollars it stops acking (likes go on) |
| `mentionsPerUserPerDay` | 30 | past this a person's posts are neither liked nor answered |
| `pollSeconds`, `jobPollSeconds` | 2, 5 | notifications; a running booth job |
| `model`, `composeEffort`, `ackModel` | `claude-opus-5-5`, `high`, `claude-haiku-5-5` | |
| `boothBase` | `http://127.0.0.1:8794` | |
| `fixRounds`, `measureRounds` | 3, 1 | check rounds (free), render-side revisions (Live time) |
| `tellWaitSeconds`, `heldHours`, `boothDownMinutes` | 60, 24, 10 | when a wait is worth a post; when a held job gets the sorry; when a silent booth means try later |
| `pieceUrl` | `null` | e.g. `"https://anthonybecker.me/tunes/{job}"`: a link under each piece |
| `ntfyTopic` | `null` | declined posts and failed requests are reported there. Keep it out of the repo |

## Running it

```sh
node contrib/bot/secrets.mjs                              # enter or change the secrets (typing hidden; Enter keeps a saved one)
node contrib/bot/main.mjs --check                         # credentials, the booth and the mode
node contrib/bot/main.mjs                                 # run (dry run until config.json says "dryRun": false)
node contrib/bot/main.mjs --status                        # recent requests, renders and spend today
node contrib/bot/main.mjs --prompt                        # the composer's prompt as Claude sees it (reads the booth's guide)
node contrib/bot/main.mjs --retry <post id>               # a failed request back in line (its saved score is reused)
touch ~/_agent_scratch/music-bot/PAUSE            # pause (finishes the acks and build in hand, reads nothing new); rm to resume
```

The plan, as in the design: the booth first, driven by hand; then the bot in dry run with `open: false`, reading
`outbox/`; then `dryRun: false` for the allow list.

## Running it for real: inside roombot

The music bot doesn't get a macOS user of its own. It runs as `roombot`, the standard user that world2's
`bot/setup-mac.sh` made for the room bot: one bot user on this Mac, two programs in it, each with its own
LaunchAgent (`me.anthonybecker.roombot` and `me.anthonybecker.musicbot`) and its own state folder.

```sh
sudo bot/setup-mac.sh             # install into roombot (refuses until world2's setup has made it), copy state and secrets, start
sudo bot/setup-mac.sh --update    # after reading the diff: install the repo's current bot/, restart
sudo bot/setup-mac.sh --secrets   # copy ~/_agent_scratch/music-bot/{secrets,config}.json over again, and the booth token
sudo bot/setup-mac.sh --uninstall # remove the music bot only (LaunchAgent and code); roombot and the room bot stay
```

- **What it changes.** The code goes to `/usr/local/musicbot`, owned by root, so `roombot` can run it but not change
  it. Its state and secrets go to `/Users/roombot/_agent_scratch/music-bot`, written by `roombot` itself. The booth
  token is read from your Keychain (`zpkt-booth-token`) and handed to `roombot` on a pipe, never a command line. If a
  copy was running as you (`me.anthonybecker.musicbot` in your LaunchAgents), it's stopped and renamed `.disabled`.
- **Root never writes inside `roombot`'s home**, as in the room bot's setup: a compromised `roombot` can't plant a trap
  for the next time you run the script. It needs no Chrome and no ffmpeg (the booth makes the video and the still).
- **What sharing roombot means.** `roombot` also runs Chrome on strangers' shaders for the room bot, so a compromise
  there reaches the music bot's secrets too: its app password, its Claude key and the booth token. The booth's rule
  bounds what the token buys: it can queue scores, and a score is data the booth checks, never code. Nothing of yours
  is in `roombot` (your home folder stays 700), and the booth's files come back over HTTP, so no folder is shared.
- **Day to day,** as `roombot` (it must be logged in, as for the room bot):
  - `sudo -u roombot -H /opt/homebrew/bin/node /usr/local/musicbot/bot/main.mjs --check </dev/null 2>&1 | cat -v` (or `--status`);
  - pause: `sudo -u roombot touch /Users/roombot/_agent_scratch/music-bot/PAUSE`;
  - logs: `sudo -u roombot tail -f /Users/roombot/_agent_scratch/music-bot/bot.log | cat -v`.

  These open the files as `roombot`, never as root, and `cat -v` defuses terminal escapes from a stranger's post.

Everything it keeps is in `_agent_scratch/music-bot/` in the home folder of whoever runs it: `bot.db` (every post,
decision, version, score, job, reply, cost and error; the Bluesky session), `bot.log` (JSON lines), `renders/` (the
booth's videos and stills as posted), `outbox/`.

## Tests

```sh
cd bot && npm install && node test.mjs            # 26 checks, about a minute; needs ffmpeg
```

Bluesky is a local fake (`fake-bsky.mjs`), the booth another (`fake-booth.mjs`: the booth's API, the real score schema
in `fixtures/score.schema.json`, a small honest check, and jobs on a clock that end in a tiny real MP4; markers in a
score's title make a job fail, fail retryably, hold, raise measure flags or come without video), and Claude a scripted
stand-in (`test-brain.mjs`), so the tests cost nothing, post nothing and never touch Live. They cover the text (facets
by UTF-8 bytes, the 300-grapheme limit, scrubbing, remix credits), the score schema made fit for structured outputs
(and that the fixture matches `lib/contracts/score.schema.json`), the limits, costs, the secrets, the Bluesky and booth
clients, the Claude requests, and whole requests: a piece replied with its video; check failures fixed in rounds; a
revision in a thread with the parent score and v2; a remix by quote; the measure-flag round; 503 closed and 429 full
waiting and resuming; held told once, then finished; a non-retryable failure's sorry and a retryable one sent again;
a crash after the job was sent picked up on the same job; a dry run writing only the outbox; the still fallback; the
acks; and `main.mjs` itself, once (`--once`) and running, where a post made during a 6 s compose is liked in about a
second and a reply under the video makes v2. `MUSIC_BOT_BRAIN=./test-brain.mjs` runs `main.mjs` with the stand-in, for
trying the plumbing without a key (against a booth, real or fake: `--booth URL`).
