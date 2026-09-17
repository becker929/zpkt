/**
 * Mock `GET /api/files/{hash}/silence`.
 *
 * The real route reads the `silence` and `silence_interval` tables. This
 * answers the same shape from the fixture so the player's skipping and the
 * waveform's tint can be driven before the backend serves it.
 *
 * `min_gap` defaults to 2.0 seconds, which is the floor the whole interface
 * works at. The fixture stores gaps down to 0.4 seconds and filters here, which
 * is what the real route does with the table.
 */

import { NextRequest, NextResponse } from "next/server";

import { MOCK_ENABLED, mockFile, mockSilence } from "@/lib/mock";
import { MIN_GAP_S } from "@/lib/silence";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

export async function GET(request: NextRequest, ctx: { params: Promise<{ hash: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  const file = mockFile(hash);
  if (!file) return NextResponse.json({ detail: "unknown hash" }, { status: 404 });

  const raw = Number(request.nextUrl.searchParams.get("min_gap") ?? MIN_GAP_S);
  const minGap = Number.isFinite(raw) && raw >= 0 ? raw : MIN_GAP_S;
  return NextResponse.json(mockSilence(file, minGap));
}
