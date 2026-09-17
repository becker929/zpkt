/**
 * Mock `GET` and `POST /api/projects`.
 *
 * `GET` reports the files it could not read alongside the ones it could. A
 * project file that does not match the schema is not silently dropped: it is
 * counted in no column, and the board says so.
 *
 * `POST` refuses past the cap with 409 and a body that names the cap and the
 * occupancy, so the client can state both rather than guess. `override: true`
 * gets through. The refusal is friction, not a block.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockCreateProject, mockProjects } from "@/lib/mock";
import { MAX_NAME_LENGTH } from "@/lib/project";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

export function GET() {
  if (!MOCK_ENABLED) return notMocked();
  const { items, unreadable, total } = mockProjects();
  return NextResponse.json({ total, items, unreadable });
}

export async function POST(request: Request) {
  if (!MOCK_ENABLED) return notMocked();
  const body = (await request.json().catch(() => ({}))) as { name?: unknown; override?: unknown };
  const name = typeof body.name === "string" ? body.name.trim() : "";
  if (!name || name.length > MAX_NAME_LENGTH) {
    return NextResponse.json({ detail: "a project needs a name" }, { status: 422 });
  }

  const result = mockCreateProject(name, body.override === true);
  if (!result.ok) {
    return NextResponse.json({ detail: result.detail, ...(result.cap ?? {}) }, { status: result.status });
  }
  return NextResponse.json(result.value, { status: 201 });
}
