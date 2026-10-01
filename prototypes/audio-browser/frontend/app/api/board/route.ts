/** Mock `GET /api/board`: the three columns, their caps, and their occupancy. */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockBoard } from "@/lib/mock";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

export function GET() {
  if (!MOCK_ENABLED) return notMocked();
  return NextResponse.json(mockBoard());
}
