/** Mock `GET /api/files/{hash}`. Includes every alias of the hash. */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockFile, mockListsOf, mockSummary } from "@/lib/mock";
import { notMocked } from "../../guard";

export const dynamic = "force-dynamic";

export async function GET(_request: Request, ctx: { params: Promise<{ hash: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  const file = mockFile(hash);
  if (!file) return NextResponse.json({ detail: "unknown hash" }, { status: 404 });

  return NextResponse.json({
    ...mockSummary(file),
    tags: file.tags,
    aliases: file.aliases,
    // Which lists hold this sound. `deleted` comes from the summary and says
    // only that the user discarded it; every alias below is still on disk.
    lists: mockListsOf(hash),
  });
}
