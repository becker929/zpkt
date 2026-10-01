/** Mock `GET /api/files/{hash}/peaks`. 1,000 int8 min/max pairs. */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockFile, mockPeaks } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, ctx: { params: Promise<{ hash: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  const file = mockFile(hash);
  if (!file) return NextResponse.json({ detail: "unknown hash" }, { status: 404 });

  const pairs = mockPeaks(file);
  return NextResponse.json({
    hash: file.hash,
    buckets: pairs.length,
    duration_s: file.duration_s,
    peaks: pairs,
  });
}
