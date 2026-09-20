/**
 * Mock `GET /api/files/{hash}/slice?start=&end=`.
 *
 * A bounded stretch of one source as Opus in an Ogg container, which is the
 * one thing the collage view decodes in the browser. Bounded twice: by the
 * region that asked, and by `MOCK_MAX_SLICE_S` here, so a client that asked
 * for a whole fifteen-minute file would be refused the way the real server
 * refuses it.
 *
 * The mock encodes with the same ffmpeg command the real route uses rather
 * than serving the PCM it generates. Sending uncompressed audio is the thing
 * that was wrong, and a mock that kept doing it would let every browser test
 * pass without ever decoding the format the phone actually receives.
 *
 * `x-slice-frames` says how many samples per channel went into the encoder, so
 * the player can check its decode instead of trusting it. Slices are cached
 * here as they are on the real server: a looping transport asks for the same
 * spans on every pass, and spawning an encoder each time would make a mock
 * server slower than the thing it stands in for.
 */

import { spawn } from "node:child_process";

import { NextResponse } from "next/server";

import { MOCK_ENABLED, MOCK_SLICE_RATE, mockFile, mockSlicePcm } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

/** Encoded slices by hash, start and end. The cut, never the rate. */
const encoded = new Map<string, Buffer>();

/** Enough spans for any fixture collage to loop without re-encoding. */
const KEEP = 256;

function opus(pcm: Buffer): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const ff = spawn("ffmpeg", [
      "-v", "error",
      "-nostdin",
      "-f", "s16le",
      "-ar", String(MOCK_SLICE_RATE),
      "-ac", "2",
      "-i", "pipe:0",
      "-c:a", "libopus",
      "-b:a", "96k",
      "-ar", String(MOCK_SLICE_RATE),
      "-ac", "2",
      "-f", "ogg",
      "pipe:1",
    ]);
    const out: Buffer[] = [];
    const err: Buffer[] = [];
    ff.stdout.on("data", (chunk: Buffer) => out.push(chunk));
    ff.stderr.on("data", (chunk: Buffer) => err.push(chunk));
    ff.on("error", reject);
    ff.on("close", (code) => {
      if (code === 0 && out.length > 0) resolve(Buffer.concat(out));
      else reject(new Error(Buffer.concat(err).toString().trim() || `ffmpeg exited ${code}`));
    });
    ff.stdin.on("error", () => {});
    ff.stdin.end(pcm);
  });
}

export async function GET(request: Request, ctx: { params: Promise<{ hash: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  const file = mockFile(hash);
  if (!file) return NextResponse.json({ detail: "unknown hash" }, { status: 404 });

  const url = new URL(request.url);
  const start = Number(url.searchParams.get("start") ?? "");
  const end = Number(url.searchParams.get("end") ?? "");
  const result = mockSlicePcm(file, start, end);
  if (!result.ok) return NextResponse.json({ detail: result.detail }, { status: result.status });

  const key = `${hash}:${start}:${end}`;
  let body = encoded.get(key);
  if (!body) {
    try {
      body = await opus(result.pcm);
    } catch (err) {
      return NextResponse.json({ detail: String(err) }, { status: 500 });
    }
    if (encoded.size >= KEEP) encoded.delete(encoded.keys().next().value!);
    encoded.set(key, body);
  }

  return new Response(new Uint8Array(body), {
    status: 200,
    headers: {
      "content-type": "audio/ogg",
      "content-length": String(body.length),
      "cache-control": "no-store",
      "x-slice-frames": String(result.frames),
      "x-slice-rate": String(MOCK_SLICE_RATE),
    },
  });
}
