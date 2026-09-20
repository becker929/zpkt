/**
 * Hold to arm: the friction in front of a gesture that destroys.
 *
 * Two gestures on the collage take material away — a snip that covers a whole
 * region, and removing a track — and both are one thumb movement away from
 * something harmless. Measured on a one-second region, a forty-pixel thumb
 * drag took the whole of it four times in ten, and the band that said so sat
 * under the thumb where it could not be read. So neither gesture goes on a
 * lift alone. The thumb has to stop and stay, about as long as a long press,
 * and only then does letting go take anything.
 *
 * Friction, not a question: nothing opens, nothing has to be answered, and
 * undo still stands behind it. This is the one implementation of it; both
 * gestures use this, so the wait, the slop and the way a moving thumb starts
 * the clock again are the same wherever the surface asks for a hold.
 */

/**
 * How long a thumb must rest before a lift takes anything.
 *
 * About as long as a long press: short enough not to feel like waiting, long
 * enough that no sweep through a region ever reaches it.
 */
export const HOLD_MS = 600;

/**
 * How far a thumb may drift and still be holding still.
 *
 * A tap's worth. Past it the clock starts again from where the thumb now is,
 * so a thumb that is still travelling never arms anything.
 */
export const HOLD_SLOP = 8;

/**
 * One hold in progress.
 *
 * `keep` is called with where the thumb is, as often as the gesture likes: it
 * starts the clock the first time, lets it run while the thumb stays put, and
 * starts it again from the new place once the thumb has moved a tap's worth.
 * `cancel` gives up on it. `armed` is what a lift should read.
 *
 * The clock is `window.setTimeout`, so this belongs to the view and not to the
 * pure geometry beside it.
 */
export class Hold {
  private timer = 0;
  private at: number | null = null;

  /** True once the thumb has stayed put for the whole wait. */
  armed = false;

  constructor(
    private readonly onArm: () => void,
    private readonly ms: number = HOLD_MS,
    private readonly slop: number = HOLD_SLOP,
  ) {}

  /** True while the clock is running and has not finished. */
  get waiting(): boolean {
    return this.timer !== 0;
  }

  /**
   * The thumb is at `at` and the gesture would like to arm.
   *
   * Called every time the thumb moves, and once when the gesture begins. A
   * thumb that has not moved a tap's worth leaves the clock alone, so the
   * wait is a wait and not a series of restarts.
   */
  keep(at: number): void {
    if (this.at !== null && Math.abs(at - this.at) < this.slop) return;
    this.cancel();
    this.at = at;
    this.timer = window.setTimeout(() => {
      this.timer = 0;
      this.armed = true;
      this.onArm();
    }, this.ms);
  }

  /** Give up on the hold: nothing is armed and no clock is running. */
  cancel(): void {
    if (this.timer) window.clearTimeout(this.timer);
    this.timer = 0;
    this.at = null;
    this.armed = false;
  }
}
