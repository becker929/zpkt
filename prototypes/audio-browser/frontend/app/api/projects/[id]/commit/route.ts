/**
 * Mock `POST /api/projects/{id}/commit`.
 *
 * Freezes this column's artifact, appends an entry to `commits`, and advances
 * the project to the next column. Out of `enrich` the project is released and
 * leaves the board.
 *
 * Two refusals, and they are different in kind:
 *
 * - 409 because the next column is at its cap. That is the discipline, so it is
 *   overridable with `override: true` and the board then shows the receiving
 *   column as over its limit until the count comes back down.
 * - 422 because a `stored` project holds no sounds. Freezing an empty sound set
 *   is not a discipline being tested, it is an operation with no meaning, and
 *   overriding it would produce a project that can never gain a sound and never
 *   had one. It is refused outright.
 * - 409 because the caller named a stage the project has already left. A second
 *   tab, or a retry after a timeout, would otherwise freeze the next stage
 *   instead of the one it asked for. Also refused outright.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockCommitProject } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

export async function POST(request: Request, ctx: Ctx) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  const body = (await request.json().catch(() => ({}))) as {
    override?: unknown;
    expect_column?: unknown;
  };

  // `expect_column` is the stage the caller believes it is freezing. It is
  // optional, and a request without it commits whatever stage the project is in.
  const expectColumn = typeof body.expect_column === "string" ? body.expect_column : undefined;
  const result = mockCommitProject(id, body.override === true, expectColumn);
  if (!result.ok) {
    return NextResponse.json({ detail: result.detail, ...(result.cap ?? {}) }, { status: result.status });
  }
  return NextResponse.json(result.value);
}
