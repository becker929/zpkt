/**
 * Mock `GET /api/files/{hash}/spans`.
 *
 * Stage 3 adds this route to the real backend. Mock mode answers it now so the
 * waveform's span overlay can be seen working. Half the collection returns
 * spans and half returns none, which exercises both paths.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockFile, mockSpans } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, ctx: { params: Promise<{ hash: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  const file = mockFile(hash);
  if (!file) return NextResponse.json({ detail: "unknown hash" }, { status: 404 });
  return NextResponse.json({ hash, spans: mockSpans(file) });
}
