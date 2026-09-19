/**
 * Mock `PUT /api/projects/{id}/collage`: the arrangement, replaced whole.
 *
 * The body is `{ regions: [...] }`. It is validated with the same model the
 * file is read with, so a region the schema rejects, or one that cuts from a
 * sound outside the project's frozen set, answers 422 with the model's words.
 * Nothing is merged and nothing is deleted from disk: a region is a pair of
 * positions in a source, and the source is untouched.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockPutCollage } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

export async function PUT(request: Request, ctx: Ctx) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  const body = (await request.json().catch(() => null)) as { regions?: unknown } | null;
  if (!body || typeof body !== "object") {
    return NextResponse.json({ detail: "a collage is { regions: [...] }" }, { status: 422 });
  }

  const result = mockPutCollage(id, body.regions);
  if (!result.ok) return NextResponse.json({ detail: result.detail }, { status: result.status });
  return NextResponse.json({
    id: result.value.id,
    updated_at: result.value.updated_at,
    collage: result.value.collage,
  });
}
