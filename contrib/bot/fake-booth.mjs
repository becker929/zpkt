// A stand-in for the booth (contrib/booth) in tests: one local HTTP server with the booth's API, so the bot's tests need
// no Live. The guide carries the real score schema (fixtures/score.schema.json, exported from contrib/booth's pydantic
// model) and a few instruments of the 2026-11 palette; /v1/check does a small honest check (palette ids, pitch
// ranges, macro names, references, length, with the real booth's error codes) so a composer stand-in can really fail
// it and fix it.
//
// Every answer has the real booth's shape: lib/contracts/booth-*.schema.json (copied into fixtures/), which test.mjs
// checks this fake against. Where the shapes come from: contrib/booth/src/booth/contract.py.
//
// Jobs run on a clock: queued, building, rendering, measuring, each `stageMs` long, then done with a tiny real MP4
// and JPEG (made with ffmpeg at start-up). Markers in a score's title script the rest:
//   [fail]   failed while building, retryable false (the score's fault: invalid_score at compile)
//   [flaky]  the first job for this score fails retryable (encode_failed); sent again under a new key, it passes
//   [hold]   held for `holdMs` after queueing (the booth stopped on a surprise), then carries on
//   [flags]  done, with measure.flags (a render-side revision should follow)
//   [novideo] done with no video.mp4 (the still is the fallback)
// st.closed = {reason, retry_in_s} answers POST /v1/jobs with 503 closed; st.queueFull with 429 queue_full.

import { execFileSync } from 'node:child_process';
import { mkdtempSync, readFileSync, rmSync } from 'node:fs';
import { createServer } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

export const TOKEN = 'zb1_test-token-0123456789abcdef';
export const SCORE_SCHEMA = JSON.parse(readFileSync(new URL('./fixtures/score.schema.json', import.meta.url), 'utf8'));

// a few instruments of contrib/booth/palettes/2026-11.toml, as GET /v1/guide shows them
export const INSTRUMENTS = [
  { id: 'drums.clockwork', role: 'drums', range: [36, 51], about: 'clanking clockwork and ticking; steady four-on-the-floor. Pads 36-51', macros: [] },
  { id: 'bass.sub_mellow', role: 'bass', range: [24, 55], about: 'a round sub bass; the drive macro makes it carry on a phone speaker', macros: ['drive'] },
  { id: 'keys.upright', role: 'keys', range: [28, 100], about: 'an old upright piano, a little out of tune; chords and melodies', macros: [] },
  { id: 'keys.music_box', role: 'keys', range: [48, 96], about: 'a wind-up music box, bright and small; good for a tune or an arpeggio', macros: [] },
];
export const RETURNS = { room: ['small', 'hall', 'cave'], echo: ['dotted_eighth', 'quarter', 'slap'] };

/** A score that passes the check: 16 bars, three parts, two sections. */
export function exampleScore(title = 'clockwork rain') {
  const four = [0, 1, 2, 3].map((t) => ({ p: 36, t, d: 0.25, v: 110 }));
  return {
    score: 1, palette: '2026-11', title, bpm: 112, key: 'F minor',
    feel: { swing: 0.1, humanize_ms: 6, velocity_jitter: 8, seed: 41 },
    parts: [
      { id: 'kick', instrument: 'drums.clockwork', gain_db: 0, pan: 0, room: 0, echo: 0, macros: [] },
      { id: 'bass', instrument: 'bass.sub_mellow', gain_db: -3, pan: 0, room: 0, echo: 0, macros: [{ name: 'drive', value: 0.5 }] },
      { id: 'keys', instrument: 'keys.upright', gain_db: -8, pan: 0.2, room: 0.4, echo: 0.2, macros: [] },
    ],
    patterns: [
      { id: 'kick_a', part: 'kick', bars: 1, notes: four },
      { id: 'bass_a', part: 'bass', bars: 2, notes: [{ p: 29, t: 0.5, d: 0.4, v: 96 }, { p: 32, t: 4.5, d: 0.4, v: 96 }] },
      { id: 'keys_a', part: 'keys', bars: 2, notes: [{ p: 65, t: 0, d: 2, v: 70 }, { p: 68, t: 0, d: 2, v: 66 }, { p: 72, t: 4, d: 2, v: 70 }] },
    ],
    song: [
      { bars: 4, play: [{ part: 'keys', pattern: 'keys_a' }] },
      { bars: 12, play: [{ part: 'kick', pattern: 'kick_a' }, { part: 'bass', pattern: 'bass_a' }, { part: 'keys', pattern: 'keys_a' }] },
    ],
    mix: { room: 'hall', echo: 'dotted_eighth' },
  };
}

export const GUIDE = {
  palette: '2026-11',
  schema: SCORE_SCHEMA,
  instruments: INSTRUMENTS,
  returns: RETURNS,
  rules: '- 4/4 only. Time is in beats from the pattern start.\n- Ids match ^[a-z][a-z0-9_]{0,23}$.\n- 8-64 bars, at most 60 s of audio.',
  examples: [exampleScore()],
  limits: { bars: [4, 64], audio_s: 60, parts: 8, notes: 2000, bpm: [60, 180] },
};

/** The fake check: enough of contrib/booth's check.py to fail a bad draft for the right reasons. */
export function checkScore(s) {
  const errors = [], warnings = [];
  const err = (path, code, message) => errors.push({ path, code, message });
  if (!s || typeof s !== 'object') return { ok: false, errors: [{ path: '$', code: 'type', message: 'a score is an object' }], warnings, estimate: null };
  if (s.score !== 1) err('score', 'schema', 'Input should be 1');
  if (s.palette !== '2026-11') err('palette', 'unknown_palette', `no palette ${s.palette}`);
  if (!(s.bpm >= 60 && s.bpm <= 180)) err('bpm', 'schema', 'Input should be between 60 and 180');
  const parts = new Map();
  (s.parts ?? []).forEach((p, i) => {
    const inst = INSTRUMENTS.find((x) => x.id === p.instrument);
    if (!inst) err(`parts[${i}].instrument`, 'unknown_instrument', `no instrument ${p.instrument} in palette 2026-11`);
    for (const [j, m] of (p.macros ?? []).entries()) if (inst && !inst.macros.includes(m.name)) err(`parts[${i}].macros[${j}].name`, 'unknown_macro', `${p.instrument} has no macro ${m.name}`);
    parts.set(p.id, inst);
  });
  const patterns = new Map();
  (s.patterns ?? []).forEach((p, i) => {
    patterns.set(p.id, p);
    const inst = parts.get(p.part);
    if (!parts.has(p.part)) err(`patterns[${i}].part`, 'unknown_part', `no part ${p.part}`);
    (p.notes ?? []).forEach((n, j) => {
      if (inst && (n.p < inst.range[0] || n.p > inst.range[1])) err(`patterns[${i}].notes[${j}].p`, 'pitch_out_of_range', `${inst.id} plays ${inst.range[0]}-${inst.range[1]}`);
      if (n.t >= p.bars * 4) err(`patterns[${i}].notes[${j}].t`, 'note_outside_pattern', `starts at beat ${n.t}; the pattern is ${p.bars * 4} beats`);
    });
  });
  let bars = 0, notes = 0;
  const played = new Set();
  (s.song ?? []).forEach((sec, i) => {
    bars += sec.bars ?? 0;
    (sec.play ?? []).forEach((pl, j) => {
      played.add(pl.part);
      const pat = patterns.get(pl.pattern);
      if (pat) notes += (pat.notes ?? []).length * Math.ceil((sec.bars ?? 0) / (pat.bars || 1));
      if (!pat) err(`song[${i}].play[${j}].pattern`, 'unknown_pattern', `no pattern ${pl.pattern}`);
      else if (pat.part !== pl.part) err(`song[${i}].play[${j}]`, 'pattern_part_mismatch', `pattern '${pl.pattern}' belongs to part '${pat.part}'`);
    });
  });
  if (bars < 4) err('song', 'too_short', `${bars} bars; at least 4`);
  if (bars > 64) err('song', 'too_long', `${bars} bars; at most 64`);
  if (!RETURNS.room.includes(s.mix?.room)) err('mix.room', 'unknown_setting', `no room setting ${s.mix?.room}`);
  if (!RETURNS.echo.includes(s.mix?.echo)) err('mix.echo', 'unknown_setting', `no echo setting ${s.mix?.echo}`);
  (s.parts ?? []).forEach((p, i) => { if (!played.has(p.id)) warnings.push({ path: `parts[${i}]`, code: 'unused_part', message: `'${p.id}' never plays` }); });
  const audio_s = bars * 4 * 60 / (s.bpm || 120);
  if (errors.length) return { ok: false, errors, warnings, estimate: null };
  return { ok: true, errors, warnings, estimate: { audio_s: Math.round(audio_s * 10) / 10, render_s: Math.round(13 + audio_s * 1.1), notes } };
}

/** Tiny real media for the jobs: a 1 s 108x192 H.264 + AAC MP4 and a JPEG still. */
export function makeMedia(dir) {
  const mp4 = join(dir, 'video.mp4'), jpg = join(dir, 'still.jpg');
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=navy:s=108x192:d=1', '-f', 'lavfi', '-i', 'sine=f=220:d=1', '-shortest', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-c:a', 'aac', '-b:a', '32k', mp4]);
  execFileSync('ffmpeg', ['-y', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=navy:s=108x192', '-frames:v', '1', jpg]);
  return { video: readFileSync(mp4), still: readFileSync(jpg) };
}

// The booth's `stage` in each state: the step it is on ("" when none). A real build shows each step ("load p2").
const STAGE = { queued: '', building: 'open', rendering: 'export', measuring: 'encode', done: '', failed: '', held: 'export' };
const HELD_ERROR = { stage: 'export', code: 'held', message: 'render: silent; Live\'s audio engine may be off', retryable: true };
export const FLAG_NOTES = {
  silent: 'the render is silent',
  clipping: 'the true peak is over -0.5 dBTP',
  too_quiet: 'it is quieter than -20 LUFS even after the master',
  no_contrast: 'every section is within 1.5 LU of the others; nothing builds or drops',
  lost_on_phone: 'most of it is below 180 Hz, so a phone speaker plays little of it',
};

/** measure.json for a score, in contrib/booth's measure.py shape: a section per song section, louder as it goes. */
export function measureOf(score, flags = []) {
  const beat = 60 / (score.bpm || 120);
  let at = 0;
  const sections = (score.song ?? []).map((sec, k) => {
    const start = at; at += (sec.bars ?? 0) * 4 * beat;
    return { label: `section ${k + 1}`, start_s: Math.round(start * 100) / 100, end_s: Math.round(at * 100) / 100, lufs: -18 + 4.5 * k };
  });
  return { seconds: Math.round((at + 2) * 100) / 100, sample_rate: 44100, lufs: -14.1, true_peak_db: -1.9, phone_db: flags.includes('lost_on_phone') ? -12.4 : -4.2, sections, flags, notes: flags.map((f) => FLAG_NOTES[f]) };
}

export async function fakeBooth({ stageMs = 30, holdMs = 300 } = {}) {
  const dir = mkdtempSync(join(tmpdir(), 'fake-booth-'));
  const media = makeMedia(dir);
  const st = {
    stageMs, holdMs, jobs: new Map(), keys: new Map(), calls: [], checks: [], submits: [],
    closed: null, queueFull: false, open: true, flakySeen: new Set(), n: 0,
  };
  const id = () => (++st.n).toString(36).padStart(12, '0').replace(/^0/, 'j');

  /** A job's timeline from its title markers: [[state, ms], ...] then its last state. */
  function timeline(score) {
    const t = String(score.title ?? '');
    const s = st.stageMs;
    const flaky = t.includes('[flaky]') && !st.flakySeen.has(JSON.stringify(score));
    if (flaky) st.flakySeen.add(JSON.stringify(score));
    const lead = [['queued', s], ...(t.includes('[hold]') ? [['held', st.holdMs]] : []), ['building', s], ['rendering', s]];
    if (t.includes('[fail]')) return [...lead.slice(0, -1), ['failed', 0, { stage: 'compile', code: 'invalid_score', message: "'drums.clockwork' is not in palette 2026-11", retryable: false }]];
    if (flaky) return [...lead, ['measuring', s], ['failed', 0, { stage: 'encode', code: 'encode_failed', message: 'ffmpeg exited with status 1', retryable: true }]];
    return [...lead, ['measuring', s], ['done', 0]];
  }

  function stateOf(j) {
    if (j.cancelled) return ['failed', 0, { stage: 'queue', code: 'cancelled', message: 'cancelled', retryable: false }];
    let left = Date.now() - j.t0, i = 0;
    while (i < j.line.length - 1 && left >= j.line[i][1]) { left -= j.line[i][1]; i++; }
    return j.line[i];
  }

  /** GET /v1/jobs/{id}, as contrib/booth's jobs.public answers it. */
  function view(j) {
    const [state, , error] = stateOf(j);
    const t = String(j.score.title ?? '');
    const done = state === 'done';
    const queued = [...st.jobs.values()].filter((x) => stateOf(x)[0] === 'queued');
    return {
      job: j.id, key: j.key, state, stage: STAGE[state], parent: j.parent,
      position: state === 'queued' ? queued.indexOf(j) + 1 : null,
      timings: done ? { open: 0.1, build: 0.1, export: 0.1, close: 0.1, encode: 0.1, total: 0.5 } : {},
      measure: done ? measureOf(j.score, t.includes('[flags]') ? ['lost_on_phone'] : []) : null,
      files: done ? ['render.m4a', ...(t.includes('[novideo]') ? [] : ['video.mp4']), 'still.jpg', 'score.json', 'measure.json'] : [],
      error: state === 'failed' ? error : state === 'held' ? HELD_ERROR : null,
    };
  }

  const read = (req) => new Promise((r) => { const parts = []; req.on('data', (d) => parts.push(d)); req.on('end', () => r(Buffer.concat(parts))); });
  const server = createServer(async (req, res) => {
    const url = new URL(req.url, 'http://x');
    const body = await read(req);
    const send = (code, data) => { res.writeHead(code, { 'content-type': 'application/json' }); res.end(JSON.stringify(data)); };
    st.calls.push(`${req.method} ${url.pathname}`);
    if (req.headers.authorization !== `Bearer ${TOKEN}`) return send(401, { error: 'unauthorized', message: 'bad token' });
    let json = {};
    try { json = body.length ? JSON.parse(body.toString()) : {}; } catch { return send(400, { error: 'bad_json', message: 'not JSON' }); }
    const m = /^\/v1\/jobs\/([a-z0-9]+)(?:\/files\/(.+))?$/.exec(url.pathname);
    if (req.method === 'GET' && url.pathname === '/v1/guide') return send(200, GUIDE);
    if (req.method === 'GET' && url.pathname === '/v1/status') {
      const states = [...st.jobs.values()].map((j) => [j.id, stateOf(j)[0]]);
      const running = states.find(([, s]) => ['building', 'rendering', 'measuring'].includes(s));
      return send(200, { open: st.open && !st.closed, reason: st.closed?.reason ?? '', running: running ? running[0] : null, queue: states.filter(([, s]) => s === 'queued').length, live: { front: 'booth_template' }, today: { jobs: st.jobs.size, live_s: 0 } });
    }
    if (req.method === 'POST' && url.pathname === '/v1/check') { st.checks.push(json.score); return send(200, checkScore(json.score)); }
    if (req.method === 'POST' && url.pathname === '/v1/jobs') {
      st.submits.push(json);
      // in the real booth's order (contrib/booth/src/booth/server.py post_job)
      if (typeof json.key !== 'string' || !json.key || json.key.length > 300) return send(400, { error: 'bad_key', message: 'key is a string of 1-300 characters' });
      if (st.keys.has(json.key)) return send(200, view(st.jobs.get(st.keys.get(json.key))));
      const c = checkScore(json.score);
      if (!c.ok) return send(400, { error: 'invalid_score', message: 'the score does not pass check', errors: c.errors });
      if (st.queueFull) return send(429, { error: 'queue_full', message: '10 pieces are waiting', retry_in_s: 300 });
      if (st.closed) return send(503, { error: 'closed', message: st.closed.reason, reason: st.closed.reason, retry_in_s: st.closed.retry_in_s });
      const j = { id: id(), key: json.key, score: json.score, parent: typeof json.parent === 'string' && json.parent ? json.parent.slice(0, 300) : null, want: json.want, t0: Date.now() };
      j.line = timeline(json.score);
      st.jobs.set(j.id, j);
      st.keys.set(json.key, j.id);
      return send(202, { ...view(j), eta_s: 45 });
    }
    if (m && !st.jobs.has(m[1])) return send(404, { error: m[2] ? 'no_file' : 'no_job', message: m[2] ? 'no such file' : 'no such job' });
    if (m && req.method === 'GET' && !m[2]) return send(200, view(st.jobs.get(m[1])));
    if (m && req.method === 'DELETE' && !m[2]) {
      const j = st.jobs.get(m[1]);
      const cancelled = stateOf(j)[0] === 'queued';
      if (cancelled) j.cancelled = true;
      return send(200, { cancelled });
    }
    if (m && req.method === 'GET' && m[2]) {
      const v = view(st.jobs.get(m[1]));
      if (!v.files.includes(m[2]) && m[2] !== 'score.json') return send(404, { error: 'no_file', message: 'not ready' });
      const bytes = m[2] === 'video.mp4' ? media.video : m[2] === 'still.jpg' ? media.still : Buffer.from(JSON.stringify(m[2] === 'score.json' ? st.jobs.get(m[1]).score : v.measure));
      res.writeHead(200, { 'content-type': m[2].endsWith('.mp4') ? 'video/mp4' : m[2].endsWith('.jpg') ? 'image/jpeg' : 'application/json' });
      return res.end(bytes);
    }
    return send(404, { error: 'not_found', message: url.pathname });
  });
  await new Promise((r) => server.listen(0, '127.0.0.1', r));
  const base = `http://127.0.0.1:${server.address().port}`;
  return { url: base, state: st, media, view, close: () => new Promise((r) => server.close(() => { rmSync(dir, { recursive: true, force: true }); r(); })) };
}
