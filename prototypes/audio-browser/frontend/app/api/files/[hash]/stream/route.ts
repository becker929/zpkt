/**
 * Mock `GET /api/files/{hash}/stream`, with HTTP range support so the audio
 * element can seek exactly as it will against the real server.
 */

import { MOCK_ENABLED, mockFile, mockWavLength, mockWavStream } from "@/lib/mock";
import { notMocked } from "../../../guard";

export const dynamic = "force-dynamic";

export async function GET(request: Request, ctx: { params: Promise<{ hash: string }> }) {
  if (!MOCK_ENABLED) return notMocked();
  const { hash } = await ctx.params;
  const file = mockFile(hash);
  if (!file) return new Response("unknown hash", { status: 404 });

  const total = mockWavLength(file);
  const range = request.headers.get("range");

  const headers: Record<string, string> = {
    "content-type": "audio/wav",
    "accept-ranges": "bytes",
    "cache-control": "no-store",
  };

  // The real server pipes AIF through ffmpeg, so those responses carry no byte
  // offsets and cannot be seeked. Mirror that here, or mock mode would let a
  // seek work that fails against the backend.
  if (file.transcoded) {
    headers["accept-ranges"] = "none";
    headers["x-transcoded-from"] = file.ext;
    headers["content-length"] = String(total);
    return new Response(mockWavStream(file, 0, total - 1), { status: 200, headers });
  }

  let start = 0;
  let end = total - 1;
  let status = 200;

  if (range) {
    const match = /bytes=(\d*)-(\d*)/.exec(range);
    if (match) {
      start = match[1] === "" ? 0 : Number(match[1]);
      end = match[2] === "" ? total - 1 : Math.min(Number(match[2]), total - 1);
      if (start >= total || start > end) {
        return new Response(null, {
          status: 416,
          headers: { ...headers, "content-range": `bytes */${total}` },
        });
      }
      status = 206;
      headers["content-range"] = `bytes ${start}-${end}/${total}`;
    }
  }

  headers["content-length"] = String(end - start + 1);
  return new Response(mockWavStream(file, start, end), { status, headers });
}
