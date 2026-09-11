# Shared channels

GitHub is the shared repository: specs and tools go out on the
`sound-function-research` branch, numbers come back the same way. This page
adds the two things a repository does not do: get Anthony's attention, and
let the two agents wake each other.

## Channel 1: getting Anthony's attention

One ntfy.sh topic, private by obscurity, name held in `ops/local.env` on each
machine and never committed. Both agents can post to it: the research agent
has tested it from its container, the Mac can `curl` it. Anthony subscribes in
the ntfy app on phone and Mac.

Priority does the tiering. Both agents use the same three levels.

| level | ntfy priority | what happens | use for |
|---|---|---|---|
| fyi | low | silent entry in the ntfy app | a job finished, a note published |
| ask | default | normal notification | a link or a paste is needed, a choice is waiting |
| act | high | notification, AND the Mac mirrors it into Apple Reminders | something only Anthony can do, blocking the next step |

The mirror is a small subscriber on the always-on Mac,
`ops/mac/ntfy_to_reminders.sh`, which listens to the topic and creates a
Reminder for anything at high priority. That is how a tier-two channel
reaches the tier-one one without either agent needing Apple credentials.
Everything below high stays in ntfy.

Posting is one call from either side:

    python3 ops/notify.py act "Rumble bypass job is ready to paste" --link https://anthonybecker.me/research/sound-function/repo/research/next.md

Gmail, Calendar and Messages are not used. The research agent can draft mail
but not send it, and the others add accounts without adding reach.

## Channel 2: the agents waking each other

The research agent lives in a web session that can be woken by GitHub
activity on a pull request it is subscribed to. That is a push channel that
already exists. The Mac agent can be started by anything that can run a
shell command. So:

**The mailbox is one long-lived pull request** on the repository, titled
"Agent mailbox", never merged: https://github.com/becker929/anthonybecker.me/pull/25 A message is a comment on it. Nothing else
goes in it.

- Research agent -> Mac agent: the research agent comments on the mailbox
  PR. A launchd job on the Mac, `ops/mac/mailbox_poll.sh`, checks the PR
  every five minutes with `gh`, and for each new comment addressed to it
  starts a Claude Code run with the comment as the prompt. The Mac is a
  client that polls.
- Mac agent -> research agent: the Mac agent comments on the same PR with
  `gh pr comment`. The research session is subscribed to the PR, so the
  comment arrives as an event and wakes it. The research agent is a server
  that gets pushed.
- Anthony -> either agent: comment on the PR. He also gets GitHub's own
  notifications for every comment, which is a free fourth copy of channel 1.

Addressing is by a first line: `@research`, `@mac`, or `@anthony`. Each
agent ignores comments not addressed to it, and never replies to its own.

**Fallback**: a Routine fires into the research session every three hours
and reads the mailbox, in case a webhook is missed. Same for the Mac, which
polls anyway. Neither side depends on the push working.

## What goes where

| this | goes through |
|---|---|
| a spec, a tool, a page | the branch |
| a result: JSON, CSV, MANIFEST | the branch, or a Drive link in a mailbox comment |
| "done", "blocked", "need X" between agents | the mailbox PR |
| "Anthony, please" | ntfy, at the right level |
| audio | Anthony's Drive only, on request, under the clip cap |

## Setup, once

On the Mac, as Anthony:

    brew install ntfy gh
    gh auth login
    cp ops/mac/local.env.example ops/local.env     # then put the topic name in it
    ops/mac/install.sh                              # loads the two launchd jobs

On the phone: install ntfy, subscribe to the topic.

For the research agent: done on 11 September. The session is subscribed to
PR #25 and a Routine checks it every three hours as a fallback.
