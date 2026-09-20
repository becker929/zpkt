/**
 * Plays one region of the collage through Web Audio.
 *
 * One region, one player. The whole collage is many of these sharing a single
 * context and a single destination, conducted by `lib/collagePlayer.ts`: pass
 * a context to the constructor and a moment to `play`, and the region sounds
 * at that moment alongside the others. There is one scheduler, and it is this
 * one.
 *
 * This is the one place in the application that decodes audio in the browser,
 * and it is allowed because what it decodes is bounded: the server slices the
 * region to a small WAV (`GET /api/files/{hash}/slice?start=&end=`) and only
 * that is fetched. A region can still be fifteen minutes long — a whole sparse
 * source stamped untrimmed — so the region is fetched in pieces of
 * `CHUNK_S` seconds, each scheduled to start the instant the one before it
 * ends, and a piece that has finished playing is let go of. A fifteen-minute
 * region therefore costs a few megabytes at a time and not the whole file.
 *
 * A stretched region is the same pieces played through `playbackRate`. The
 * server cuts the source at one speed, whatever the rate; the rate is applied
 * here, to every piece alike, so each piece lasts `duration / rate` seconds
 * and the next is scheduled that far on. The pieces stay gapless because
 * their start times are added up in played time, not read off a clock.
 *
 * `play` must be called from inside a user gesture. iOS will not start an
 * `AudioContext` from anywhere else, so the context is made and resumed
 * synchronously before the first `await`.
 */

import { ApiError, sliceUrl } from "./api";

/** Seconds of source fetched per request. */
export const CHUNK_S = 15;

/**
 * Pieces kept scheduled ahead of the playhead, counted in the time they take
 * to play. Two pieces at one speed is thirty seconds; at four times it is
 * seven and a half, so the lead is never less than `LEAD_MIN_S` either. Held
 * in played time rather than source time so a fast region does not decode
 * eight pieces up front to get thirty seconds ahead.
 */
const AHEAD = 2;
const LEAD_MIN_S = 10;

/**
 * How far past its moment a piece may land and still count as on time.
 *
 * Scheduling is arithmetic against a clock that keeps moving while the
 * arithmetic is done, so a piece is routinely a millisecond or two "late".
 * A tenth of a second is longer than any of that and shorter than a gap
 * anybody hears as a gap.
 */
const LATE_S = 0.1;

export interface SliceRegion {
  hash: string;
  start_s: number;
  end_s: number;
  rate: number;
  gain: number;
}

export interface SliceHandlers {
  /** Called on every frame with how far through the region playback is, 0..1. */
  onProgress(fraction: number): void;
  /** Called once when the region has played out. */
  onEnd(): void;
  /** Called once when a piece could not be fetched or decoded. Playback stops. */
  onError(message: string): void;
  /**
   * Called once when a piece arrived after the moment it was due.
   *
   * The region carries on from where the clock is, so it runs behind what it
   * was written against. Playback does not stop. Nothing calls this on a
   * network that keeps up.
   */
  onLate?(): void;
}

/** What a caller may say about how a region is played. */
export interface SliceOptions {
  /**
   * The context time the region's first piece starts at.
   *
   * Left out, the region starts a hair after now, which is a region played on
   * its own. The collage gives a moment instead, so every region begins at
   * its own place in the piece and the pieces overlap as they should.
   */
  startAt?: number;
  /**
   * The region's first piece, already fetched and decoded.
   *
   * The collage fetches one of these for every region before it starts
   * anything, so the first sound is never waiting on the network.
   */
  first?: AudioBuffer;
  /**
   * Whether to watch the clock and report how far through the region is.
   *
   * On for a region played alone, where the block fills as it sounds. Off for
   * a region in the collage, where one playhead follows the whole piece and
   * fifteen more would be fifteen idle loops. Either way the region still
   * ends itself: the last piece says so when it has played out.
   */
  progress?: boolean;
}

type ContextCtor = typeof AudioContext;

function contextCtor(): ContextCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as typeof window & { webkitAudioContext?: ContextCtor };
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

/** A context, or null where Web Audio is not available. */
export function newAudioContext(): AudioContext | null {
  const Ctor = contextCtor();
  return Ctor ? new Ctor() : null;
}

function decode(ctx: AudioContext, bytes: ArrayBuffer): Promise<AudioBuffer> {
  return new Promise((resolve, reject) => {
    ctx.decodeAudioData(bytes, resolve, (err) => reject(err ?? new Error("could not decode the slice")));
  });
}

/** Where the piece that begins at `from` stops. Never more than `CHUNK_S`. */
function pieceEnd(region: SliceRegion, from: number): number {
  return Math.min(from + CHUNK_S, region.end_s);
}

/** One piece of a source, fetched and decoded. */
async function fetchPiece(
  ctx: AudioContext,
  hash: string,
  from: number,
  to: number,
  signal: AbortSignal,
): Promise<AudioBuffer> {
  const url = sliceUrl(hash, from, to);
  const res = await fetch(url, { signal, headers: { accept: "audio/wav" } });
  if (!res.ok) {
    let detail = "";
    try {
      detail = String(((await res.json()) as { detail?: unknown }).detail ?? "");
    } catch {
      /* no body worth reading */
    }
    throw new ApiError(detail || `${res.status} ${res.statusText} for ${url}`, res.status);
  }
  return decode(ctx, await res.arrayBuffer());
}

/**
 * A region's first piece, fetched and decoded ahead of time.
 *
 * This is what lets the collage start every region at once: the piece that
 * has to sound first is already in memory, so scheduling is arithmetic and
 * not a request. A region that cannot be fetched throws here, before anything
 * has been scheduled, and the caller can say so instead of starting a piece
 * with a silent hole in it.
 */
export function firstPieceOf(ctx: AudioContext, region: SliceRegion, signal: AbortSignal): Promise<AudioBuffer> {
  return fetchPiece(ctx, region.hash, region.start_s, pieceEnd(region, region.start_s), signal);
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class SlicePlayer {
  private ctx: AudioContext | null = null;
  /** True when the context belongs to somebody else and must not be closed. */
  private readonly shared: boolean;
  private token = 0;
  private sources: AudioBufferSourceNode[] = [];
  private abort: AbortController | null = null;
  private frame = 0;

  /**
   * A player of its own, or one voice of a collage.
   *
   * Given a context, this player uses it and never closes it: the collage
   * mixes every region through one context and one destination, and iOS
   * allows only a handful of contexts at a time.
   */
  constructor(shared: AudioContext | null = null) {
    this.ctx = shared;
    this.shared = shared !== null;
  }

  /** Whether the browser can do this at all. Old WebViews cannot. */
  static supported(): boolean {
    return contextCtor() !== null;
  }

  /**
   * Start a region from its beginning. Anything already playing stops.
   *
   * Returns false when Web Audio is not available, in which case nothing was
   * started and the caller says so.
   */
  play(region: SliceRegion, handlers: SliceHandlers, options?: SliceOptions): boolean {
    this.stop();
    if (!this.ctx) this.ctx = newAudioContext();
    const ctx = this.ctx;
    if (!ctx) return false;
    // Inside the gesture, before any await: this is what lets iOS play.
    void ctx.resume().catch(() => {});

    const token = (this.token += 1);
    const abort = new AbortController();
    this.abort = abort;

    const rate = region.rate > 0 ? region.rate : 1;
    const lengthS = Math.max(0, region.end_s - region.start_s) / rate;
    let startedAt: number | null = null;
    let nextAt = 0;
    let finished = false;
    let late = false;

    const finish = () => {
      if (finished || token !== this.token) return;
      finished = true;
      this.stop();
      handlers.onEnd();
    };

    // A piece that has played out is let go of, buffer and all, so a long
    // or a slowed region never holds every piece it has played.
    const release = (source: AudioBufferSourceNode) => {
      if (token !== this.token) return;
      source.onended = null;
      source.disconnect();
      this.sources = this.sources.filter((s) => s !== source);
    };

    // How far ahead, in played seconds, the pieces are fetched.
    const lead = Math.max((CHUNK_S / rate) * AHEAD, LEAD_MIN_S);

    const tick = () => {
      if (token !== this.token) return;
      if (startedAt !== null && lengthS > 0) {
        const fraction = Math.min(Math.max((ctx.currentTime - startedAt) / lengthS, 0), 1);
        handlers.onProgress(fraction);
        if (fraction >= 1) {
          finish();
          return;
        }
      }
      this.frame = requestAnimationFrame(tick);
    };

    // The first piece, when the caller has already fetched and decoded it.
    let primed = options?.first ?? null;

    const run = async () => {
      let cursor = region.start_s;
      while (cursor < region.end_s) {
        const to = pieceEnd(region, cursor);
        let buffer: AudioBuffer;
        if (primed) {
          buffer = primed;
          primed = null;
        } else {
          buffer = await fetchPiece(ctx, region.hash, cursor, to, abort.signal);
        }
        if (token !== this.token) return;

        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.playbackRate.value = rate;
        const gain = ctx.createGain();
        gain.gain.value = region.gain;
        source.connect(gain);
        gain.connect(ctx.destination);

        if (startedAt === null) {
          // A short lead so the first piece is not scheduled in the past,
          // unless the caller named the moment this region begins at.
          nextAt = options?.startAt ?? ctx.currentTime + 0.05;
          startedAt = nextAt;
          if (options?.progress !== false) this.frame = requestAnimationFrame(tick);
        }
        // A piece whose moment has already gone is never scheduled into it.
        // Web Audio answers a start time in the past by sounding the piece at
        // once, so a fetch that took longer than the lead would put this piece
        // on top of the one still sounding — and then every piece after it,
        // each arriving quickly and each also overdue, until the region was
        // several copies of itself at once. It starts from the clock instead,
        // and the rest of the region follows it: the region runs behind, and
        // it stays one sound.
        const at = Math.max(nextAt, ctx.currentTime);
        if (at > nextAt + LATE_S && !late) {
          late = true;
          handlers.onLate?.();
        }
        source.start(at);
        // The piece lasts its own length divided by the rate, and the next
        // one begins exactly then.
        nextAt = at + buffer.duration / rate;
        this.sources.push(source);
        cursor = to;

        if (cursor >= region.end_s) {
          source.onended = () => {
            release(source);
            finish();
          };
          return;
        }
        source.onended = () => release(source);
        // Hold back rather than fetching the whole region up front. Two pieces
        // ahead is enough to cover a slow tailnet and keeps memory bounded.
        while (token === this.token && nextAt - ctx.currentTime > lead) {
          await sleep(200);
        }
      }
    };

    run().catch((err: unknown) => {
      if (token !== this.token || abort.signal.aborted) return;
      this.stop();
      handlers.onError(err instanceof Error ? err.message : String(err));
    });
    return true;
  }

  /** Stop whatever is playing. Safe to call when nothing is. */
  stop(): void {
    this.token += 1;
    this.abort?.abort();
    this.abort = null;
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
    for (const source of this.sources) {
      try {
        source.onended = null;
        source.stop();
      } catch {
        /* never started, or already stopped */
      }
      source.disconnect();
    }
    this.sources = [];
  }

  /**
   * Release the context. Called when the view unmounts.
   *
   * A player on somebody else's context only stops: the context is theirs to
   * close, and closing it would silence every other region in the mix.
   */
  close(): void {
    this.stop();
    if (this.shared) return;
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
  }
}
