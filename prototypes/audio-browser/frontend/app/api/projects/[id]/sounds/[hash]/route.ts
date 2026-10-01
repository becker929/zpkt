/**
 * Mock `PUT` and `DELETE /api/projects/{id}/sounds/{hash}`.
 *
 * Membership keys on the hash, never on a path, so a decision made about one
 * copy of a sound holds for every copy of it.
 *
 * Both answer 409 once a `stored` commit exists. The refusal is at the API and
 * not only in the interface: a tab that was showing the project before it was
 * committed will try this, and it has to be told no by the server rather than
 * be trusted to have noticed.
 *
 * Neither removes audio. `DELETE` here takes a sound out of a project; every
 * path that held the bytes still holds them.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockSetProjectSound } from "@/lib/mock";
import { notMocked } from "../../../../guard";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string; hash: string }> };

async function set(ctx: Ctx, member: boolean) {
  if (!MOCK_ENABLED) return notMocked();
  const { id, hash } = await ctx.params;
  const result = mockSetProjectSound(id, hash, member);
  if (!result.ok) return NextResponse.json({ detail: result.detail }, { status: result.status });
  return NextResponse.json(result.value);
}

export async function PUT(_request: Request, ctx: Ctx) {
  return set(ctx, true);
}

export async function DELETE(_request: Request, ctx: Ctx) {
  return set(ctx, false);
}
