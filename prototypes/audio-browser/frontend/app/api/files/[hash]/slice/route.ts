/**
 * Mock `GET /api/files/{hash}/slice?start=&end=`.
 *
 * A bounded stretch of one source as a 48 kHz stereo 16-bit WAV, which is the
 * one thing the collage view decodes in the browser. Bounded twice: by the
 * region that asked, and by `MOCK_MAX_SLICE_S` here, so a client that asked
 * for a whole fifteen-minute file would be refused the way the real server
 * refuses it.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockFile, mockSliceWav } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

export async function GET(request: Request, ctx: { params: Promise<{ hash: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  const file = mockFile(hash);
  if (!file) return NextResponse.json({ detail: "unknown hash" }, { status: 404 });

  const url = new URL(request.url);
  const start = Number(url.searchParams.get("start") ?? "");
  const end = Number(url.searchParams.get("end") ?? "");
  const result = mockSliceWav(file, start, end);
  if (!result.ok) return NextResponse.json({ detail: result.detail }, { status: result.status });

  return new Response(new Uint8Array(result.wav), {
    status: 200,
    headers: {
      "content-type": "audio/wav",
      "content-length": String(result.wav.length),
      "cache-control": "no-store",
    },
  });
}
