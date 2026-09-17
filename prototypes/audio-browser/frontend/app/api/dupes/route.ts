/** Mock `GET /api/dupes`: hashes with more than one alias. */

import { NextRequest, NextResponse } from "next/server";

import { MOCK_ENABLED, mockDupes } from "@/lib/mock";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  if (!MOCK_ENABLED) return notMocked();
  const params = request.nextUrl.searchParams;
  const limit = Math.min(Math.max(Number(params.get("limit") ?? 200), 1), 2000);
  // Copies inside a project bundle are withheld unless asked for. See
  // `mockDupes` and the real route in `server/queries.py`.
  const includeBundles = params.get("include_bundles") === "true";
  return NextResponse.json({ ...mockDupes(limit, includeBundles), include_bundles: includeBundles });
}
