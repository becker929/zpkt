/**
 * Plays one region of the collage through Web Audio.
 *
 * This is the one place in the application that decodes audio in the browser,
 * and it is allowed because what it decodes is bounded: the server slices the
 * region to a small WAV (`GET /api/files/{hash}/slice?start=&end=`) and only
 * that is fetched. A region can still be fifteen minutes long — a whole sparse
 * source stamped untrimmed — so the region is fetched in pieces of
 * `CHUNK_S` seconds, each scheduled to start the instant the one before it
 * ends, and never more than two pieces are held decoded at once. A
 * fifteen-minute region therefore costs a few megabytes at a time and not the
 * whole file.
 *
 * `play` must be called from inside a user gesture. iOS will not start an
 * `AudioContext` from anywhere else, so the context is made and resumed
 * synchronously before the first `await`.
 */

import { ApiError, sliceUrl } from "./api";

/** Seconds of source fetched per request. */
export const CHUNK_S = 15;

/** Decoded pieces kept scheduled ahead of the playhead. */
const AHEAD = 2;

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
}

type ContextCtor = typeof AudioContext;

function contextCtor(): ContextCtor | null {
  if (typeof window === "undefined") return null;
  const w = window as typeof window & { webkitAudioContext?: ContextCtor };
  return w.AudioContext ?? w.webkitAudioContext ?? null;
}

function decode(ctx: AudioContext, bytes: ArrayBuffer): Promise<AudioBuffer> {
  return new Promise((resolve, reject) => {
    ctx.decodeAudioData(bytes, resolve, (err) => reject(err ?? new Error("could not decode the slice")));
  });
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

export class SlicePlayer {
  private ctx: AudioContext | null = null;
  private token = 0;
  private sources: AudioBufferSourceNode[] = [];
  private abort: AbortController | null = null;
  private frame = 0;

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
  play(region: SliceRegion, handlers: SliceHandlers): boolean {
    this.stop();
    const Ctor = contextCtor();
    if (!Ctor) return false;
    if (!this.ctx) this.ctx = new Ctor();
    const ctx = this.ctx;
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

    const finish = () => {
      if (finished || token !== this.token) return;
      finished = true;
      this.stop();
      handlers.onEnd();
    };

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

    const run = async () => {
      let cursor = region.start_s;
      while (cursor < region.end_s) {
        const to = Math.min(cursor + CHUNK_S, region.end_s);
        const url = sliceUrl(region.hash, cursor, to);
        const res = await fetch(url, { signal: abort.signal, headers: { accept: "audio/wav" } });
        if (!res.ok) {
          let detail = "";
          try {
            detail = String(((await res.json()) as { detail?: unknown }).detail ?? "");
          } catch {
            /* no body worth reading */
          }
          throw new ApiError(detail || `${res.status} ${res.statusText} for ${url}`, res.status);
        }
        const bytes = await res.arrayBuffer();
        if (token !== this.token) return;
        const buffer = await decode(ctx, bytes);
        if (token !== this.token) return;

        const source = ctx.createBufferSource();
        source.buffer = buffer;
        source.playbackRate.value = rate;
        const gain = ctx.createGain();
        gain.gain.value = region.gain;
        source.connect(gain);
        gain.connect(ctx.destination);

        if (startedAt === null) {
          // A short lead so the first piece is not scheduled in the past.
          nextAt = ctx.currentTime + 0.05;
          startedAt = nextAt;
          this.frame = requestAnimationFrame(tick);
        }
        source.start(nextAt);
        nextAt += buffer.duration / rate;
        this.sources.push(source);
        cursor = to;

        if (cursor >= region.end_s) {
          source.onended = finish;
          return;
        }
        // Hold back rather than fetching the whole region up front. Two pieces
        // ahead is enough to cover a slow tailnet and keeps memory bounded.
        while (token === this.token && nextAt - ctx.currentTime > CHUNK_S * AHEAD) {
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

  /** Release the context. Called when the view unmounts. */
  close(): void {
    this.stop();
    void this.ctx?.close().catch(() => {});
    this.ctx = null;
  }
}
