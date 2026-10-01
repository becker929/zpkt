/**
 * Mock `POST /api/projects/{id}/revive`.
 *
 * The project returns to the column it left, carrying every commit it already
 * had. Reviving takes a slot like anything else, so a full column answers 409
 * with the cap and the occupancy in the body and `override: true` gets through,
 * exactly as creating and committing do. That cost is the point: starting
 * something again is starting something.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockReviveProject } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, ctx: Ctx) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  const body = (await request.json().catch(() => ({}))) as { override?: unknown };

  const result = mockReviveProject(id, body.override === true);
  if (!result.ok) {
    return NextResponse.json({ detail: result.detail, ...(result.cap ?? {}) }, { status: result.status });
  }
  return NextResponse.json(result.value);
}
