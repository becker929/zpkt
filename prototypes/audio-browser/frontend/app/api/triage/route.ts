/** Mock `GET /api/triage`: triaged over total, and the split by state. */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockTriage } from "@/lib/mock";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

export function GET() {
  if (!MOCK_ENABLED) return notMocked();
  return NextResponse.json(mockTriage());
}
