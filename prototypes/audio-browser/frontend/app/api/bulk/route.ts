/**
 * Mock `POST /api/bulk`.
 *
 * One action over many hashes. The real route applies the batch in a single
 * transaction; this one is synchronous, so it is atomic for free. What it has
 * to reproduce is the contract: a cap of 1,000, counts rather than a per-hash
 * result, and unknown hashes skipped rather than refused.
 *
 * Two actions, because there are two decisions. Discard, and put it back.
 */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockBulk } from "@/lib/mock";
import { MAX_BULK_HASHES, type BulkAction } from "@/lib/types";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

const ACTIONS: BulkAction[] = ["delete", "restore"];

export async function POST(request: Request) {
  if (!MOCK_ENABLED) return notMocked();
  const body = (await request.json().catch(() => ({}))) as { hashes?: unknown; action?: unknown };

  const hashes = Array.isArray(body.hashes) ? body.hashes.filter((h): h is string => typeof h === "string") : [];
  const action = ACTIONS.includes(body.action as BulkAction) ? (body.action as BulkAction) : null;

  if (!action) return NextResponse.json({ detail: "unknown action" }, { status: 422 });
  if (hashes.length > MAX_BULK_HASHES) {
    return NextResponse.json({ detail: `at most ${MAX_BULK_HASHES} hashes` }, { status: 422 });
  }

  return NextResponse.json(mockBulk(hashes, action));
}
