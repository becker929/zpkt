/** Mock `GET` and `POST /api/lists`. */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockCreateList, mockLists } from "@/lib/mock";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

export function GET() {
  if (!MOCK_ENABLED) return notMocked();
  return NextResponse.json(mockLists());
}

export async function POST(request: Request) {
  if (!MOCK_ENABLED) return notMocked();
  const body = (await request.json().catch(() => ({}))) as { name?: unknown };
  const name = typeof body.name === "string" ? body.name.trim() : "";
  if (!name || name.length > 120) {
    return NextResponse.json({ detail: "a list needs a name" }, { status: 422 });
  }
  const created = mockCreateList(name);
  // The name is unique in the schema, so a repeat is a conflict rather than a
  // second list with the same name.
  if (!created) return NextResponse.json({ detail: "a list with that name exists" }, { status: 409 });
  return NextResponse.json(created, { status: 201 });
}
