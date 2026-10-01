/** Mock `GET /api/stats`. */

import { NextResponse } from "next/server";

import { MOCK_ENABLED, mockStats } from "@/lib/mock";
import { notMocked } from "../guard";

export const dynamic = "force-dynamic";

export function GET() {
  if (!MOCK_ENABLED) return notMocked();
  return NextResponse.json(mockStats());
}
