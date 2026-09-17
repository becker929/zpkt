/**
 * Mock `GET /api/files`.
 *
 * Only reachable in mock mode. In real mode a `beforeFiles` rewrite in
 * `next.config.mjs` sends `/api/*` to the FastAPI server before the filesystem
 * routes are consulted.
 */

import { NextRequest, NextResponse } from "next/server";

import { MOCK_ENABLED, mockQuery, mockSummary } from "@/lib/mock";
import { EMPTY_QUERY, type DeletedFilter, type Query, type SortKey, type SortOrder } from "@/lib/types";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  if (!MOCK_ENABLED) return notMocked();

  const params = request.nextUrl.searchParams;
  const query: Query = {
    ...EMPTY_QUERY,
    q: params.get("q") ?? "",
    ext: params.get("ext") ?? "",
    favorite: params.get("favorite") === "true",
    min_dur: params.get("min_dur") ?? "",
    max_dur: params.get("max_dur") ?? "",
    sort: (params.get("sort") ?? "name") as SortKey,
    order: (params.get("order") ?? "asc") as SortOrder,
    // Anything the server does not recognise falls back to hiding discarded
    // sounds, which is the safe direction: it never shows a sound the user
    // asked to stop seeing.
    deleted: (["false", "true", "any"].includes(params.get("deleted") ?? "")
      ? params.get("deleted")
      : "false") as DeletedFilter,
  };

  const limit = Math.min(Math.max(Number(params.get("limit") ?? 200), 1), 1000);
  const offset = Math.max(Number(params.get("offset") ?? 0), 0);

  const matched = mockQuery(query);
  const items = matched.slice(offset, offset + limit).map(mockSummary);

  return NextResponse.json({ items, total: matched.length, limit, offset });
}
