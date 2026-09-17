/**
 * Mock `POST /api/bulk`.
 *
 * One action over many hashes. The real route applies the batch in a single
 * transaction; this one is synchronous, so it is atomic for free. What it has
 * to reproduce is the contract: a cap of 1,000, counts rather than a per-hash
 * result, and unknown hashes skipped rather than refused.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockBulk } from "@/lib/mock";
import { MAX_BULK_HASHES, type BulkAction } from "@/lib/types";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

const ACTIONS: BulkAction[] = ["star", "unstar", "delete", "restore", "add_to_list", "remove_from_list"];

export async function POST(request: Request) {
  if (!MOCK_ENABLED) return notMocked();
  const body = (await request.json().catch(() => ({}))) as {
    hashes?: unknown;
    action?: unknown;
    list_id?: unknown;
  };

  const hashes = Array.isArray(body.hashes) ? body.hashes.filter((h): h is string => typeof h === "string") : [];
  const action = ACTIONS.includes(body.action as BulkAction) ? (body.action as BulkAction) : null;
  const listId = typeof body.list_id === "number" ? body.list_id : null;

  if (!action) return NextResponse.json({ detail: "unknown action" }, { status: 422 });
  if (hashes.length > MAX_BULK_HASHES) {
    return NextResponse.json({ detail: `at most ${MAX_BULK_HASHES} hashes` }, { status: 422 });
  }

  const result = mockBulk(hashes, action, listId);
  if (!result) return NextResponse.json({ detail: "unknown list" }, { status: 404 });
  return NextResponse.json(result);
}
