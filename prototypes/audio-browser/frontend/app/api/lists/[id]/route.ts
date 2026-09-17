/** Mock `GET`, `PATCH` and `DELETE /api/lists/{id}`. */

import { NextRequest, NextResponse } from "next/server";

import { MOCK_ENABLED, mockDeleteList, mockListDetail, mockRenameList } from "@/lib/mock";
import { notMocked } from "../../guard";

export const dynamic = "force-dynamic";

const missing = () => NextResponse.json({ detail: "unknown list" }, { status: 404 });

export async function GET(request: NextRequest, ctx: { params: Promise<{ id: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  const params = request.nextUrl.searchParams;
  const limit = Math.min(Math.max(Number(params.get("limit") ?? 200), 1), 1000);
  const offset = Math.max(Number(params.get("offset") ?? 0), 0);
  const detail = mockListDetail(Number(id), limit, offset);
  return detail ? NextResponse.json(detail) : missing();
}

export async function PATCH(request: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  const body = (await request.json().catch(() => ({}))) as { name?: unknown };
  const name = typeof body.name === "string" ? body.name.trim() : "";
  if (!name) return NextResponse.json({ detail: "a list needs a name" }, { status: 422 });
  const renamed = mockRenameList(Number(id), name);
  return renamed ? NextResponse.json(renamed) : missing();
}

export async function DELETE(_request: Request, ctx: { params: Promise<{ id: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  // Removing a list removes membership rows. The sounds in it are untouched,
  // and so is every file on disk.
  const removed = mockDeleteList(Number(id));
  return removed ? NextResponse.json(removed) : missing();
}
