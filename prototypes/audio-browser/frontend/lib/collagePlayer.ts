/**
 * Plays the whole collage: every region, on every track, at once.
 *
 * Until this there was only ever one region sounding. This is the piece.
 *
 * It is a conductor, not a second scheduler. The scheduling stays in
 * `SlicePlayer`, which already fetches a region in bounded pieces, joins them
 * without a seam and plays them at any rate. Here there is one player per
 * region, all sharing one `AudioContext` and therefore one destination. Web
 * Audio sums everything reaching that destination, so the mix is a plain sum
 * and nothing here has to add anything up.
 *
 * One context, not fifteen: iOS allows only a handful at a time, and separate
 * contexts have separate clocks, which is the one thing a collage cannot have.
 * Every region's start is `t0 + at_s` on that single clock, so two regions
 * written to sound together do.
 *
 * The one thing between the voices and the destination is the mix bus, which
 * **saturates**. Fifteen voices at unity go past full scale the moment they
 * overlap, and past full scale the device cuts the tops off and it tears.
 * There is no master fader, because there is no number on this surface, so
 * the sum is shaped instead: push more in and it gets harder. Below the knee
 * the curve asks for the signal back unchanged, and the node returns it to
 * within about 126 dB down — a browser's rounding, not a colour, and not
 * nothing either. The curve and that number are in `lib/softClip.ts`.
 *
 * A region's level may move while the piece plays, and does not stop it. That
 * is the one edit that is heard at once: balance is set by ear against what is
 * already sounding, and a gesture that silenced the thing it was balancing
 * would be useless. Every other edit still takes its region out of the pass.
 *
 * **Nothing starts until every region's first piece is in memory.** A piece
 * that began on time and went silent while the network caught up would be
 * worse than one that started a moment later, so the transport says it is
 * loading and the first sound is scheduled only once there is something to
 * schedule. Only the *first* piece of each region is fetched: the rest arrive
 * as they are needed, the way a single region already works. Fetching every
 * second of a long collage up front would be hundreds of megabytes on a phone.
 *
 * `play` must be called from inside a user gesture. iOS will not start an
 * `AudioContext` from anywhere else, so the context is made and resumed
 * synchronously, before the first `await`.
 */

import { regionLengthS } from "./collage";
import { SlicePlayer, firstPieceOf, newAudioContext, type SliceRegion } from "./slicePlayer";
import { mixBus, type MixBus } from "./softClip";

/** A region as the piece needs it: what to cut, and when it sounds. */
export interface CollageRegion extends SliceRegion {
  id: string;
  /** When the region sounds, in seconds from the top of the piece. */
  at_s: number;
}

export interface CollageHandlers {
  /** Called once when the piece has been scheduled and is about to sound. */
  onStart(): void;
  /** Called on every frame with how far into the piece playback is, in seconds. */
  onElapsed(elapsedS: number): void;
  /** Called once when the piece has played out. */
  onEnd(): void;
  /** Called when nothing at all could be played. Nothing was scheduled. */
  onError(message: string): void;
  /** Called when one region dropped out. Everything else plays on. */
  onRegionError(id: string, message: string): void;
  /**
   * Called when one region fell behind the piece: a slice arrived after the
   * moment it was due, so that voice is now running late against the rest.
   */
  onRegionLate(id: string): void;
  /**
   * Called when one region's sound decoded to a different length than the
   * server encoded.
   *
   * Every region is placed by arithmetic on one clock, so a voice that is a
   * few samples longer or shorter than it says sits a fraction away from
   * where the piece puts it, and its own repeats meet with a seam. The piece
   * plays on and this is said, because a drift nobody is told about is a
   * piece that sounds subtly wrong with nothing to blame.
   */
  onRegionDrift(id: string): void;
}

/**
 * How far ahead of now the piece's first moment is scheduled.
 *
 * Long enough that the scheduling arithmetic for fifteen regions finishes
 * before the first of them is due, short enough to read as immediate.
 */
const START_LEAD_S = 0.12;

function messageOf(err: unknown): string {
  return err instanceof Error ? err.message : String(err);
}

export class CollagePlayer {
  private ctx: AudioContext | null = null;
  /** One player per region sounding, by region id. */
  private players = new Map<string, SlicePlayer>();
  private abort: AbortController | null = null;
  private frame = 0;
  private token = 0;
  /**
   * Regions silenced for the rest of this pass, by id.
   *
   * An edit silences a region. It may arrive before that region has a player
   * to silence: the pass is decided at the tap, but the first pieces take a
   * breath to arrive, and the modes stay live throughout that breath. A
   * region named here is left out when the scheduling finally happens, so a
   * cut made under the ear is never sounded with the material it removed.
   * Cleared by `stop`, which every `play` begins with.
   */
  private silenced = new Set<string>();
  /**
   * Levels set since this pass was decided, by region id.
   *
   * A balance made between the tap and the first sound has no player to reach
   * yet: the pass is scheduled once the first pieces are in, and the gestures
   * stay live through that breath. A level named here is used when the
   * scheduling finally happens, so a region balanced under the thumb is heard
   * at the level the thumb left it at and not the one the file held at the
   * tap. Cleared by `stop`, which every `play` begins with.
   */
  private levels = new Map<string, number>();
  /** The saturating bus every voice reaches the destination through. */
  private bus: MixBus | null = null;

  /** Whether the browser can do this at all. */
  static supported(): boolean {
    return SlicePlayer.supported();
  }

  /**
   * Play the piece from the top. Anything already sounding stops first.
   *
   * Returns false when Web Audio is not available, in which case nothing was
   * started and the caller says so. Returning true means the piece is being
   * loaded; `onStart` says when it is sounding.
   */
  play(regions: readonly CollageRegion[], handlers: CollageHandlers): boolean {
    this.stop();
    if (!this.ctx) this.ctx = newAudioContext();
    const ctx = this.ctx;
    if (!ctx) return false;
    if (!this.bus) this.bus = mixBus(ctx);
    // Inside the gesture, before any await: this is what lets iOS play.
    void ctx.resume().catch(() => {});

    const token = (this.token += 1);
    const abort = new AbortController();
    this.abort = abort;
    void this.begin(token, ctx, abort, regions, handlers);
    return true;
  }

  private async begin(
    token: number,
    ctx: AudioContext,
    abort: AbortController,
    regions: readonly CollageRegion[],
    handlers: CollageHandlers,
  ): Promise<void> {
    // Every region's first piece, fetched at once. A region that cannot be
    // fetched is reported and left out; the rest of the piece still plays.
    const fetched = await Promise.all(
      regions.map(async (region) => {
        try {
          return { region, piece: await firstPieceOf(ctx, region, abort.signal), error: null as string | null };
        } catch (err) {
          return { region, piece: null, error: messageOf(err) };
        }
      }),
    );
    if (token !== this.token || abort.signal.aborted) return;

    // A region edited while its first piece was still coming does not sound
    // this pass. The edit already happened; the material it asked for is gone.
    const ready = fetched.filter((entry) => entry.piece !== null && !this.silenced.has(entry.region.id));
    if (ready.length === 0) {
      this.stop();
      handlers.onError(fetched[0]?.error ?? "there is nothing here to play");
      return;
    }
    for (const entry of fetched) {
      if (entry.error !== null && !this.silenced.has(entry.region.id)) {
        handlers.onRegionError(entry.region.id, entry.error);
      }
    }

    // The piece's first moment, on the one clock every region is read against.
    const t0 = ctx.currentTime + START_LEAD_S;
    const out = this.bus?.input ?? ctx.destination;
    let extentS = 0;
    for (const { region, piece } of ready) {
      const player = new SlicePlayer(ctx);
      this.players.set(region.id, player);
      // The first piece was fetched before any player existed, so its length
      // is checked here rather than inside the one that is about to play it.
      if (piece !== null && !piece.exact) handlers.onRegionDrift(region.id);
      // A level set while the first pieces were still coming is the level
      // this pass sounds at.
      const level = this.levels.get(region.id);
      player.play(
        level === undefined ? region : { ...region, gain: level },
        {
          onProgress: () => {},
          onEnd: () => {
            this.players.delete(region.id);
          },
          onError: (message) => {
            this.players.delete(region.id);
            handlers.onRegionError(region.id, message);
          },
          onLate: () => handlers.onRegionLate(region.id),
          onDrift: () => handlers.onRegionDrift(region.id),
        },
        { startAt: t0 + Math.max(0, region.at_s), first: piece ?? undefined, progress: false, out },
      );
      extentS = Math.max(extentS, Math.max(0, region.at_s) + regionLengthS(region));
    }
    handlers.onStart();

    // The playhead's clock: the piece's own time, read off the context. A
    // region slowed to a quarter is four times as tall, so the line takes
    // four times as long to cross it. Nothing here is counted in frames.
    const tick = () => {
      if (token !== this.token) return;
      const elapsed = ctx.currentTime - t0;
      handlers.onElapsed(Math.max(0, elapsed));
      if (elapsed >= extentS) {
        this.stop();
        handlers.onEnd();
        return;
      }
      this.frame = requestAnimationFrame(tick);
    };
    this.frame = requestAnimationFrame(tick);
  }

  /**
   * Silence one region for the rest of this pass, leaving the others alone.
   *
   * This is what an edit to a sounding region does. The piece keeps its
   * shape; the region that was changed under the ear stops rather than
   * carrying on as material that no longer exists.
   *
   * Returns whether there was a pass for it to go quiet in, so the caller can
   * say so. A region going quiet looks exactly like a region ending, and the
   * difference is the whole of why the next play sounds different.
   */
  silence(id: string): boolean {
    // Between the tap and the end there is a pass; outside one there is
    // nothing to silence and nothing to say.
    if (this.abort === null) return false;
    this.silenced.add(id);
    const player = this.players.get(id);
    if (player) {
      player.close();
      this.players.delete(id);
    }
    return true;
  }

  /**
   * Move one region's level, while the piece plays, without stopping it.
   *
   * The one edit that is heard at once. Everything else a gesture can do
   * changes what material a region holds or when it sounds, and a voice
   * already scheduled cannot be rewritten mid-sound without a seam — so those
   * take the region out of the pass. A level is different in kind: it is a
   * number on a gain that already exists, ramped rather than switched, and
   * balancing by ear against a mix that is not sounding would not be
   * balancing at all.
   *
   * Returns whether there was a pass for it to be heard in.
   */
  setGain(id: string, gain: number): boolean {
    if (this.abort === null) return false;
    this.levels.set(id, gain);
    this.players.get(id)?.setGain(gain);
    return true;
  }

  /** Stop everything at once. Safe to call when nothing is playing. */
  stop(): void {
    this.token += 1;
    this.silenced.clear();
    this.levels.clear();
    this.abort?.abort();
    this.abort = null;
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
    for (const player of this.players.values()) player.close();
    this.players.clear();
  }

  /** Release the context. Called when the view unmounts. */
  close(): void {
    this.stop();
    this.bus?.dispose();
    this.bus = null;
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
  }
}
