// The ready cue: two soft notes, rising, the moment the mic starts hearing (the dock's "Go ahead"), so Anthony can
// start talking without looking at the phone. It is made on the spot with two oscillators on the engine's context:
// no file to fetch or decode. The menu's "Ready sound" turns it off.
//
// The mic and the speaker are never on together (docs/studio.md, "A turn"), and this cue is the one deliberate
// exception. The rule is there so a car's Bluetooth is never switched between its profiles mid-sound, and so the
// answer never goes back into the mic. The cue does neither: it plays in the audio session the open mic already
// has (play-and-record), so nothing switches; it lasts 150 ms and is quiet, before anyone has started talking; and
// the mic's echo cancellation takes it out of what the Mac hears. It goes straight to the context's destination,
// never through the engine's queue, so it is not an item: it is not counted, and it never makes the page busy,
// which would tell the Mac 'busy' and close the very mic it announces.

const NOTES = [[659.25, 0, 0.06], [987.77, 0.06, 0.09]];   // E5, then the B a fifth above: [Hz, start s, length s]
const PEAK = 0.08;            // about -22 dBFS: heard over a car's road noise, not a jolt in headphones
const ATTACK_S = 0.006;
const LEAD_S = 0.01;          // scheduled just ahead, so the first note starts whole

/** Play the cue on `ctx` (which must be running). Returns the seconds until it reaches the speaker. */
export function playReadyCue(ctx) {
  const at = ctx.currentTime + LEAD_S;
  for (const [hz, start, length] of NOTES) {
    const t = at + start;
    const osc = ctx.createOscillator();
    const env = ctx.createGain();
    osc.frequency.value = hz;
    env.gain.setValueAtTime(0, t);
    env.gain.linearRampToValueAtTime(PEAK, t + ATTACK_S);
    env.gain.exponentialRampToValueAtTime(PEAK / 100, t + length - 0.005);
    env.gain.linearRampToValueAtTime(0, t + length);
    osc.connect(env).connect(ctx.destination);
    osc.onended = () => env.disconnect();
    osc.start(t);
    osc.stop(t + length);
  }
  return LEAD_S + (ctx.outputLatency || ctx.baseLatency || 0);
}
