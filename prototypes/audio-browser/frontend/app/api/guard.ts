import { NextResponse } from "next/server";

/**
 * Returned when a mock route is hit while mock mode is off. It means the
 * rewrite to the FastAPI server did not take, which is worth seeing rather
 * than silently answering with fake data.
 */
export function notMocked() {
  return NextResponse.json(
    { detail: "mock mode is off; /api should be rewritten to the backend on port 8090" },
    { status: 503 },
  );
}
