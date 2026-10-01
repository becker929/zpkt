/**
 * Mock `GET /api/files/{hash}`.
 *
 * No aliases. A path is a name for a hash and nothing more, and no view in
 * this interface shows one, so the route does not carry a list of them.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockFile, mockSummary } from "@/lib/mock";
import { notMocked } from "../../guard";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, ctx: { params: Promise<{ hash: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  const file = mockFile(hash);
  if (!file) return NextResponse.json({ detail: "unknown hash" }, { status: 404 });

  // `deleted` says only that the user discarded it; every copy is still on disk.
  return NextResponse.json({ ...mockSummary(file), tags: file.tags });
}
