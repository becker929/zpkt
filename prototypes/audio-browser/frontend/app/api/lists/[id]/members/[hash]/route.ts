/** Mock `PUT` and `DELETE /api/lists/{id}/members/{hash}`. Membership keys on the hash. */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockSetMember } from "@/lib/mock";
import { notMocked } from "../../../../guard";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string; hash: string }> };

async function set(ctx: Ctx, member: boolean) {
  if (!MOCK_ENABLED) return notMocked();
  const { id, hash } = await ctx.params;
  const state = mockSetMember(Number(id), hash, member);
  if (!state) return NextResponse.json({ detail: "unknown list or hash" }, { status: 404 });
  return NextResponse.json(state);
}

export async function PUT(_request: Request, ctx: Ctx) {
  return set(ctx, true);
}

export async function DELETE(_request: Request, ctx: Ctx) {
  return set(ctx, false);
}
