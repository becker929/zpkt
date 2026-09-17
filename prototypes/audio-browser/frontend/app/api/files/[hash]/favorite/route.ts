/** Mock `PUT` and `DELETE /api/files/{hash}/favorite`. Favourites attach to the hash. */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockFile, setMockFavorite } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

async function toggle(ctx: { params: Promise<{ hash: string }> }, favorite: boolean) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  if (!mockFile(hash)) return NextResponse.json({ detail: "unknown hash" }, { status: 404 });
  setMockFavorite(hash, favorite);
  return NextResponse.json({ hash, favorite });
}

export async function PUT(_request: Request, ctx: { params: Promise<{ hash: string }> }) {
  return toggle(ctx, true);
}

export async function DELETE(_request: Request, ctx: { params: Promise<{ hash: string }> }) {
  return toggle(ctx, false);
}
