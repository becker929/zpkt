/**
 * Mock `GET /api/swipe`: the one sound to answer next.
 *
 * A sound is undecided until it has been taken into a project or discarded.
 * There is no third state, so this is simply the first thing that is neither.
 *
 * The answer carries the sound's silent gaps, its spans and the project on the
 * bench alongside the sound, as the real route does, so the view spends one
 * request on a sound instead of three.
 *
 * `remaining` counts the whole undecided set, not what is in this answer. The
 * swipe view shows it.
 *
 * `limit` is accepted and ignored, exactly as the real route does with it: one
 * sound is answered before the next is handed over, so there is no batch for a
 * limit to bound.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockSwipeQueue } from "@/lib/mock";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

export function GET() {
  if (!MOCK_ENABLED) return notMocked();
  return NextResponse.json(mockSwipeQueue());
}
