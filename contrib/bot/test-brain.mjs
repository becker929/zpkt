// Scripted stand-ins for Claude, for tests (and `MUSIC_BOT_BRAIN=./test-brain.mjs node main.mjs ...`, which runs
// the whole bot with no API key). The acker answers by keywords in the post: "decline", "thanks" (ignore), "what are
// you" (chat), a reply under a piece is a revision, else a piece when the limits allow it (or always, for "insist",
// to test that the pipeline won't promise music the limits refuse). The composer writes fake-booth's example score:
// "fix" in the post makes the first drafts fail the booth's check (a pitch out of range, then an unknown
// instrument) before a good one; booth markers in the post ([hold], [fail], [flags], [flaky], [novideo]) go into the
// title, where fake-booth.mjs reads them; a measure round takes [flags] out. A revision starts from the parent's
// score and keeps its title; "slower" lowers the tempo. MUSIC_BOT_TEST_COMPOSE_MS makes every first draft that slow.

import { exampleScore } from './fake-booth.mjs';

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
export const ACCEPTED = "On it! I'm making your piece now. A video of it will follow here.";
export const REVISING = "On it! I'm making the next version now.";
const MARKERS = ['[hold]', '[fail]', '[flags]', '[flaky]', '[novideo]'];

export function scriptedAcker({ ms = 0 } = {}) {
  const log = [];
  return {
    log,
    async ack(input) {
      log.push(input);
      if (ms) await sleep(ms);
      const t = input.text.toLowerCase();
      const a = (decision, reply, brief = null) => ({ decision, brief, reply, cost: 0.0005 });
      if (t.includes('decline')) return a('decline', "I can't make that one, but I'd happily make you something else.");
      if (t.includes('thanks')) return a('ignore', null);
      if (t.includes('what are you')) return a('chat', 'I make short pieces of music! Mention me again with an idea.');
      if (input.piece?.kind === 'revise' && (input.canRevise.ok || t.includes('insist'))) return a('revise', REVISING, `the next version: ${input.text}`);
      if (input.canPiece.ok || t.includes('insist')) return a('piece', ACCEPTED, `a piece for: ${input.text}`);
      return a('chat', (input.piece?.kind === 'revise' ? input.canRevise.text : input.canPiece.text) ?? "I can't make that right now.");
    },
  };
}

export function scriptedBrain({ composeMs = Number(process.env.MUSIC_BOT_TEST_COMPOSE_MS || 0) } = {}) {
  const log = { compose: [], fixes: [] };
  const answer = (score) => ({ score, line: `I made you “${score.title}”, a little clockwork groove.`, alt: 'A piano roll scrolls past: ticking clockwork drums, a round sub bass and soft upright piano chords.', cost: 0.05 });
  return {
    log,
    composeSystem: '',
    schema: null,
    compose({ brief, handle, text, parent }) {
      log.compose.push({ brief, handle, text, parent });
      const marks = MARKERS.filter((m) => text.includes(m)).join(' ');
      let good;
      if (parent?.kind === 'revise') {
        good = structuredClone(parent.score);
        if (/slower/i.test(text)) good.bpm = Math.max(60, good.bpm - 20);
        good.title = `${String(good.title).replace(/ ?\[[a-z]+\]/g, '')}${marks ? ` ${marks}` : ''}`;
      } else if (parent?.kind === 'remix') {
        good = structuredClone(parent.score);
        good.title = `${String(parent.title).replace(/ ?\[[a-z]+\]/g, '')} (remix)${marks ? ` ${marks}` : ''}`;
        good.bpm = Math.min(180, good.bpm + 16);
      } else good = exampleScore(`clockwork rain${marks ? ` ${marks}` : ''}`);
      const pitch = structuredClone(good); pitch.patterns[1].notes[0].p = 90; // bass.sub_mellow plays 24-55
      const inst = structuredClone(good); inst.parts[2].instrument = 'keys.harpsichord';
      const drafts = /\bfix\b/i.test(text) ? [pitch, inst, good] : [good];
      let i = 0;
      return {
        draft: async () => { if (composeMs) await sleep(composeMs); return answer(drafts[i++] ?? good); },
        fix: async (kind, ...args) => {
          log.fixes.push({ kind, args });
          if (kind === 'measure') { const s = structuredClone(good); s.title = s.title.replace(' [flags]', ''); s.parts[1].gain_db += 3; good = s; return answer(s); }
          return answer(drafts[i++] ?? good);
        },
      };
    },
  };
}

export default scriptedBrain;
