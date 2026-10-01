/**
 * Mock `GET` and `PATCH /api/projects/{id}`, plus a `DELETE` the specification
 * does not have.
 *
 * `GET` answers with the document as it is on disk, even when it does not
 * validate: `valid: false` plus the reasons. A caller that cannot read a file
 * has to be able to see why, and the board shows it rather than pretending the
 * file is not there.
 *
 * `PATCH` writes the name and the notes. It does not move a project between
 * columns; that is what commit is for. It does not abandon or revive one
 * either: those free and take a slot, so they have their own routes where the
 * cap can be applied.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockDeleteProject, mockPatchProject, mockProjectDetail } from "@/lib/mock";
import { MAX_NAME_LENGTH } from "@/lib/project";
import { notMocked } from "../../guard";

export const dynamic = "force-dynamic";

type Ctx = { params: Promise<{ id: string }> };

export async function GET(_request: Request, ctx: Ctx) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  const detail = mockProjectDetail(id);
  if (!detail) return NextResponse.json({ detail: "no such project" }, { status: 404 });
  // A file that does not validate is a 200 with the reasons in it, not a 404.
  // The file exists; it is the shape that is wrong, and hiding it behind "not
  // found" would send someone looking for a file that is right in front of them.
  return NextResponse.json(detail);
}

export async function PATCH(request: Request, ctx: Ctx) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  const body = (await request.json().catch(() => ({}))) as {
    name?: unknown;
    notes?: unknown;
    column?: unknown;
    abandoned?: unknown;
  };

  const patch: { name?: string; notes?: string; column?: unknown } = {};
  if (body.name !== undefined) {
    const name = typeof body.name === "string" ? body.name.trim() : "";
    if (!name || name.length > MAX_NAME_LENGTH) {
      return NextResponse.json({ detail: "a project needs a name" }, { status: 422 });
    }
    patch.name = name;
  }
  if (body.notes !== undefined) {
    if (typeof body.notes !== "string") {
      return NextResponse.json({ detail: "notes must be text" }, { status: 422 });
    }
    patch.notes = body.notes;
  }
  if (body.column !== undefined) patch.column = body.column;
  // Abandoning frees a slot and reviving takes one, so neither may be written
  // as an ordinary field: the cap would never be consulted. They have their own
  // routes, and this says which rather than ignoring the key.
  if (body.abandoned !== undefined) {
    return NextResponse.json(
      {
        detail:
          "abandoning frees a slot and reviving takes one. use POST /abandon or POST /revive, where the cap is applied.",
      },
      { status: 409 },
    );
  }

  const result = mockPatchProject(id, patch);
  if (!result.ok) return NextResponse.json({ detail: result.detail }, { status: result.status });
  return NextResponse.json(result.value);
}

/**
 * Mock only, and test only.
 *
 * No route in the specification removes a project, and nothing in the interface
 * calls this. It exists because the mock server keeps its projects in memory
 * and is reused between test runs: without it, a test that created a project
 * would leave the next run's board one slot fuller than it found it.
 *
 * It removes a project file and nothing else. It removes no audio, as no route
 * in this application may.
 */
export async function DELETE(_request: Request, ctx: Ctx) {
  if (!MOCK_ENABLED) return notMocked();
  const { id } = await ctx.params;
  if (!mockDeleteProject(id)) {
    return NextResponse.json({ detail: "no such project" }, { status: 404 });
  }
  return NextResponse.json({ id, removed: true });
}
