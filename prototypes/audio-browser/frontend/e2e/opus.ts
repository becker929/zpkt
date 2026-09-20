/**
 * Slice bodies for the tests that serve the slice route themselves.
 *
 * Some playback tests need a cut longer than the one second the fixture's
 * sounds hold, so they answer `GET /api/files/{hash}/slice` from inside the
 * test. What they answer with has to be what the server answers with —
 * Opus in an Ogg container at 96 kbps, 48 kHz stereo — because the thing
 * those tests prove is that pieces join without a seam, and a seam is a
 * property of what the browser decoded.
 *
 * Encoded by the same ffmpeg command the server uses, so the bytes under
 * test are made the way the real ones are. Kept by span, because a looping
 * transport asks for the same spans on every pass and the server caches them
 * too; a test that re-encoded each time would be measuring ffmpeg.
 */

import { spawnSync } from "node:child_process";

import type { Page } from "@playwright/test";

export const SLICE_RATE = 48000;

/** A slice as it goes over the wire, with the sample count it was made from. */
export interface SliceBody {
  body: Buffer;
  frames: number;
}

const made = new Map<string, SliceBody>();

/** The tone the fixture's slice route sends, as raw PCM. */
function tone(fromS: number, frames: number): Buffer {
  const pcm = Buffer.alloc(frames * 4);
  for (let i = 0; i < frames; i += 1) {
    const value = Math.round(Math.sin(2 * Math.PI * 220 * (fromS + i / SLICE_RATE)) * 12000);
    pcm.writeInt16LE(value, i * 4);
    pcm.writeInt16LE(value, i * 4 + 2);
  }
  return pcm;
}

/** Encode raw 48 kHz stereo PCM the way the server does. */
export function encodeOpus(pcm: Buffer): Buffer {
  const done = spawnSync(
    "ffmpeg",
    [
      "-v", "error",
      "-nostdin",
      "-f", "s16le",
      "-ar", String(SLICE_RATE),
      "-ac", "2",
      "-i", "pipe:0",
      "-c:a", "libopus",
      "-b:a", "96k",
      "-ar", String(SLICE_RATE),
      "-ac", "2",
      "-f", "ogg",
      "pipe:1",
    ],
    { input: pcm, maxBuffer: 1 << 28 },
  );
  if (done.status !== 0 || done.stdout.length === 0) {
    throw new Error(`ffmpeg could not encode the slice: ${done.stderr?.toString().trim()}`);
  }
  return done.stdout;
}

/** What a browser made of a slice: its own decode, and what it was told. */
export interface Decoded {
  /** Samples per channel the browser handed back. */
  length: number;
  /** Samples per channel the server said it encoded. */
  stated: number;
  rate: number;
  channels: number;
  bytes: number;
  type: string;
}

/**
 * Fetch one slice and decode it in the browser under test.
 *
 * This is the real path and not a model of it: the browser's own `fetch`, the
 * browser's own `decodeAudioData`, over bytes made by the same encoder the
 * server runs. The context is asked for 48 kHz, which is the rate every slice
 * is cut at, so `length` is comparable to `stated` without resampling in the
 * way.
 */
export async function decodeSlice(page: Page, url: string): Promise<Decoded> {
  return page.evaluate(async (target) => {
    const res = await fetch(target);
    const stated = Number(res.headers.get("x-slice-frames") ?? "0");
    const type = res.headers.get("content-type") ?? "";
    const bytes = await res.arrayBuffer();
    const Ctor =
      window.AudioContext ?? (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    const ctx = new Ctor({ sampleRate: 48000 });
    const buffer = await new Promise<AudioBuffer>((resolve, reject) => {
      ctx.decodeAudioData(bytes.slice(0), resolve, (err) => reject(err ?? new Error("could not decode")));
    });
    const out = {
      length: buffer.length,
      stated,
      rate: buffer.sampleRate,
      channels: buffer.numberOfChannels,
      bytes: bytes.byteLength,
      type,
    };
    void ctx.close();
    return out;
  }, url);
}

/** The slice for `fromS..toS`, encoded once and kept. */
export function sliceBody(fromS: number, toS: number): SliceBody {
  const key = `${fromS}:${toS}`;
  const kept = made.get(key);
  if (kept) return kept;
  const frames = Math.round((toS - fromS) * SLICE_RATE);
  const fresh = { body: encodeOpus(tone(fromS, frames)), frames };
  made.set(key, fresh);
  return fresh;
}
