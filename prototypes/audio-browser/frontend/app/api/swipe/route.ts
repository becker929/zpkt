/**
 * Mock `GET /api/swipe`: the queue of undecided sounds.
 *
 * A sound is undecided until it has been taken into a project or discarded.
 * There is no third state, so this is simply everything that is neither.
 *
 * `remaining` counts the whole undecided set, not the batch. The swipe view
 * shows it, and a batch size would make the number meaningless.
 */

import { NextRequest, NextResponse } from "next/server";

import { MOCK_ENABLED, mockSwipeQueue } from "@/lib/mock";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

export function GET(request: NextRequest) {
  if (!MOCK_ENABLED) return notMocked();
  const raw = Number(request.nextUrl.searchParams.get("limit") ?? 24);
  const limit = Math.min(Math.max(Number.isFinite(raw) ? raw : 24, 1), 200);
  return NextResponse.json(mockSwipeQueue(limit));
}
