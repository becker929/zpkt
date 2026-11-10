#!/usr/bin/env node
// Writes the bot's secrets.json, so nobody hand-edits JSON or pastes a secret anywhere it could be kept: it asks for
// each value with the typing hidden, checks it looks like what was asked for, and saves the file readable by this
// user only. Enter keeps a value that's already saved; other keys in the file are left as they are.
//
//   node bot/secrets.mjs                                                         as you (--check, from the repo)
//   sudo -u roombot -H /opt/homebrew/bin/node /usr/local/musicbot/bot/secrets.mjs   as roombot (the running bot)
//
// Without a terminal (stdin piped) it reads one line per value, for tests.

import { chmodSync, existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { HOME } from './config.mjs';

const FIELDS = [
  {
    key: 'BSKY_IDENTIFIER', hidden: false, ask: "The bot's Bluesky handle (e.g. tunes.anthonybecker.me)",
    clean: (v) => v.replace(/^@/, '').toLowerCase(), ok: (v) => /^[a-z0-9-]+(\.[a-z0-9-]+)+$/.test(v), why: 'a handle looks like tunes.anthonybecker.me',
  },
  {
    key: 'BSKY_APP_PASSWORD', hidden: true, ask: 'Its app password (Settings, Privacy and security, App passwords)',
    ok: (v) => /^[a-z0-9]{4}(-[a-z0-9]{4}){3}$/i.test(v), why: "an app password looks like abcd-efgh-ijkl-mnop. Make one; never give the bot the account's own password",
  },
  {
    key: 'ANTHROPIC_API_KEY', hidden: true, ask: 'The Anthropic API key',
    ok: (v) => /^sk-ant-[\w-]{20,}$/.test(v), why: 'an Anthropic API key starts sk-ant-',
  },
  {
    key: 'BOOTH_TOKEN', hidden: true, ask: "The booth's token (Anthony's Keychain item zpkt-booth-token; setup-mac.sh --secrets copies it)",
    ok: (v) => /^zb1_[A-Za-z0-9_-]{16,}$/.test(v), why: 'a booth token starts zb1_',
  },
];

const file = join(HOME, 'secrets.json');
const saved = existsSync(file) ? JSON.parse(readFileSync(file, 'utf8')) : {};
const tty = process.stdin.isTTY;
const piped = tty ? null : readFileSync(0, 'utf8').split(/\r?\n/);

let carry = ''; // what arrived after a line's Enter (several lines pasted at once): the next prompt's input

/** One line from the person, echoed only if not hidden. Arrow keys and other escape sequences are dropped. */
function line(question, hidden) {
  process.stdout.write(question);
  if (!tty) {
    if (!piped.length) { process.stdout.write('\nno more input\n'); process.exit(1); }
    process.stdout.write('\n');
    return Promise.resolve(piped.shift());
  }
  return new Promise((resolve) => {
    let buf = '', esc = 0;
    const stdin = process.stdin;
    const done = (value) => { stdin.off('data', onData); stdin.setRawMode(false); stdin.pause(); process.stdout.write('\n'); resolve(value); };
    const onData = (chunk) => {
      const chars = [...chunk];
      for (let i = 0; i < chars.length; i++) {
        const ch = chars[i];
        if (esc === 1) { esc = ch === '[' || ch === 'O' ? 2 : 0; continue; }
        if (esc === 2) { if (/[@-~]/.test(ch)) esc = 0; continue; }
        if (ch === '\u001b') { esc = 1; continue; }
        if (ch === '\u0003') { process.stdout.write('\n'); stdin.setRawMode(false); process.exit(130); }
        if (ch === '\r' || ch === '\n') {
          carry = chars.slice(i + 1 + (ch === '\r' && chars[i + 1] === '\n' ? 1 : 0)).join('');
          return done(buf);
        }
        if (ch === '\u007f' || ch === '\b') { if (buf) { buf = buf.slice(0, -1); if (!hidden) process.stdout.write('\b \b'); } continue; }
        if (ch < ' ') continue;
        buf += ch;
        if (!hidden) process.stdout.write(ch);
      }
    };
    stdin.setRawMode(true);
    stdin.setEncoding('utf8');
    stdin.resume();
    stdin.on('data', onData);
    if (carry) { const c = carry; carry = ''; onData(c); }
  });
}

console.log(`Saving to ${file}${Object.keys(saved).length ? ' (Enter keeps what is saved)' : ''}.${FIELDS.some((f) => f.hidden) ? ' Secrets are not shown as you type or paste.' : ''}`);
const out = { ...saved };
for (const f of FIELDS) {
  for (;;) {
    const have = saved[f.key] ? (f.hidden ? ' [saved]' : ` [${saved[f.key]}]`) : '';
    const raw = (await line(`${f.ask}${have}: `, f.hidden)).trim();
    if (!raw && saved[f.key]) break;
    const v = f.clean ? f.clean(raw) : raw;
    if (v && f.ok(v)) {
      out[f.key] = v;
      if (f.hidden) console.log(`  ok (${v.length} characters)`);
      break;
    }
    console.log(`  That doesn't look right: ${f.why}. Try again (Ctrl-C to stop).`);
  }
}

mkdirSync(HOME, { recursive: true, mode: 0o700 });
const tmp = `${file}.new`;
writeFileSync(tmp, JSON.stringify(out, null, 2) + '\n', { mode: 0o600 });
chmodSync(tmp, 0o600);
renameSync(tmp, file);
console.log(`Saved ${file}, readable by this user only.`);
const env = FIELDS.map((f) => f.key).filter((k) => process.env[k]);
if (env.length) console.log(`Note: ${env.join(', ')} ${env.length > 1 ? 'are' : 'is'} also set in your environment, and the bot uses the environment's value first.`);
