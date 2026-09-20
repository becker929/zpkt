/**
 * The mix bus, and the curve it saturates with.
 *
 * Fifteen voices summed plainly go past full scale whenever they overlap, and
 * past full scale the output device simply cuts the tops off: a discontinuity
 * in the waveform, whose harmonics do not roll off, heard as tearing. There is
 * no master fader to pull down, because there is no number anywhere on this
 * surface. So the bus saturates instead. Push more in and it gets harder;
 * there is nothing to configure and nothing to read.
 *
 * Three claims, all of them arithmetic rather than opinion, and all of them
 * checked by `collage.mock.spec.ts` against the curve this module really
 * builds:
 *
 * 1. **Below the knee it is the identity.** `softClip(x) === x` exactly for
 *    `|x| <= KNEE`. A single region at gain 1 whose peaks stay under −1.9 dBFS
 *    — which is every real recording — passes through untouched, sample for
 *    sample. Nothing is coloured on the way to being loud.
 * 2. **It never leaves the rails.** `|softClip(x)| < 1` for every finite `x`,
 *    so the destination never has to cut anything off. The saturation is the
 *    only non-linearity in the path.
 * 3. **It has no corner.** The two pieces meet with the same value *and the
 *    same slope*: at the knee `tanh` has slope 1 and the widths cancel
 *    exactly. A hard clip's corner is what makes its harmonics fall away as
 *    slowly as they do; there is no corner here.
 *
 * What a full-scale peak costs: `softClip(1) = 0.8 + 0.2·tanh(1) = 0.95234`,
 * which is −0.42 dB, on the loudest sample of a sound that reaches digital
 * full scale and nowhere else. That is well under the ear's threshold for a
 * level difference, and it is the price of having an output ceiling at all: no
 * curve can hold the output inside ±1 and also leave a full-scale input alone.
 *
 * ## Why the trim, and why eight
 *
 * A `WaveShaperNode`'s curve is defined over an input of −1 to 1 and *clamps*
 * anything outside it to the end of the table. Fed a sum of four, it would
 * hold the curve's last value flat — a hard clip wearing the curve's name. So
 * the bus scales down by `HEADROOM` first, and the table is built over inputs
 * of −`HEADROOM` to `HEADROOM`. Eight is enough for fifteen voices at the
 * loudest the balance gesture allows, and by then the curve is within a
 * millionth of the rail, so the clamp past it changes nothing.
 *
 * `HEADROOM` is a power of two, so dividing by it is exact in binary floating
 * point; `CURVE_POINTS - 1` is a power of two, so every point of the table
 * lands on an exactly representable input. Together those are what make claim
 * 1 hold through the node and not only in this file.
 *
 * `oversample` is left off on purpose. Oversampling would run even an
 * untouched quiet signal through an up- and down-sampling filter pair, and
 * claim 1 would become "almost". The cost is aliasing on the harmonics the
 * saturation makes, which on noise and texture is part of the same hardness.
 */

/**
 * Where the curve stops being the identity.
 *
 * −1.94 dBFS. Above it the curve bends; at it and below it does nothing at
 * all. Higher would be more transparent and would squeeze the bend into less
 * room; lower would be gentler and would colour more of what is already quiet
 * enough not to need it.
 */
export const KNEE = 0.8;

/** The largest input the table covers. A power of two, so the trim is exact. */
export const HEADROOM = 8;

/**
 * Points in the table.
 *
 * One more than 2^14, so the table's step is a power of two and every input it
 * names is exactly representable. Sixty-four kilobytes, built once per context.
 */
export const CURVE_POINTS = 16385;

/**
 * One sample through the curve.
 *
 * The identity up to the knee; above it, the remaining room to the rail,
 * approached by `tanh`. Odd, so no direct current is added and no even
 * harmonic is made out of nothing.
 */
export function softClip(x: number): number {
  const magnitude = Math.abs(x);
  if (magnitude <= KNEE) return x;
  const room = 1 - KNEE;
  const y = KNEE + room * Math.tanh((magnitude - KNEE) / room);
  return x < 0 ? -y : y;
}

/**
 * The table a `WaveShaperNode` reads, covering inputs of ±`HEADROOM`.
 *
 * The node interpolates between neighbouring points, so the stretch of the
 * table below the knee — where the points lie on a straight line through the
 * origin — interpolates back to exactly the input it came from.
 */
export function softClipCurve(): Float32Array<ArrayBuffer> {
  const curve = new Float32Array(new ArrayBuffer(CURVE_POINTS * Float32Array.BYTES_PER_ELEMENT));
  const last = CURVE_POINTS - 1;
  for (let i = 0; i <= last; i += 1) {
    const at = ((i / last) * 2 - 1) * HEADROOM;
    curve[i] = softClip(at);
  }
  return curve;
}

/** The mix bus: everything that sounds connects to `input`. */
export interface MixBus {
  /** Where voices connect. */
  input: AudioNode;
  /** Let the bus go. The context is the caller's to close. */
  dispose(): void;
}

/**
 * A saturating bus into the context's destination.
 *
 * Every voice connects to `input` and Web Audio sums them there, exactly as
 * it summed them at the destination before this existed. The sum is trimmed
 * into the table's range, shaped, and sent on. One region at unity reaches the
 * destination as itself; fifteen overlapping reach it hard rather than torn.
 */
export function mixBus(ctx: AudioContext): MixBus {
  const trim = ctx.createGain();
  trim.gain.value = 1 / HEADROOM;
  const shaper = ctx.createWaveShaper();
  shaper.curve = softClipCurve();
  shaper.oversample = "none";
  trim.connect(shaper);
  shaper.connect(ctx.destination);
  return {
    input: trim,
    dispose() {
      try {
        trim.disconnect();
        shaper.disconnect();
      } catch {
        /* a context that has already gone */
      }
    },
  };
}
