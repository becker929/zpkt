/**
 * Mock `POST /api/projects/{id}/abandon`.
 *
 * The other exit. The project leaves the board, the slot comes back, and the
 * file is kept: what was tried is worth keeping. Nothing is frozen and nothing
 * is appended to `commits`, which is the whole difference from commit.
 *
 * No cap stands in the way of letting something go, so there is no override
 * here. Two refusals, neither overridable, because neither is a discipline: a
 * released project is already off the board, and an abandoned one has already
 * done this.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockAbandonProject } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

/** The longest reason a document will take, matching `abandonmentSchema`. */
const MAX_REASON = 2000;

export async function POST(request: Request, ctx: Ctx) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  const body = (await request.json().catch(() => ({}))) as { reason?: unknown };

  // A reason is optional. Abandoning is lighter than committing and demanding
  // an explanation for it would make the cheap exit expensive, which is the
  // trap this route exists to avoid.
  const reason = typeof body.reason === "string" ? body.reason : "";
  if (reason.length > MAX_REASON) {
    return NextResponse.json(
      { detail: `a reason is at most ${MAX_REASON} characters` },
      { status: 422 },
    );
  }

  const result = mockAbandonProject(id, reason);
  if (!result.ok) return NextResponse.json({ detail: result.detail }, { status: result.status });
  return NextResponse.json(result.value);
}
