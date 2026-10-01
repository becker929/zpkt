/**
 * Mock `PUT` and `DELETE /api/files/{hash}/deleted`.
 *
 * Soft delete attaches to the hash, so the decision applies to every copy of
 * the sound at once. Nothing here touches the filesystem, and there is
 * deliberately no route that does.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockDeletedState, mockFile, setMockDeleted } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

async function set(ctx: { params: Promise<{ hash: string }> }, deleted: boolean) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  if (!mockFile(hash)) return NextResponse.json({ detail: "unknown hash" }, { status: 404 });
  setMockDeleted(hash, deleted);
  return NextResponse.json(mockDeletedState(hash));
}

export async function PUT(_request: Request, ctx: { params: Promise<{ hash: string }> }) {
  return set(ctx, true);
}

export async function DELETE(_request: Request, ctx: { params: Promise<{ hash: string }> }) {
  return set(ctx, false);
}
