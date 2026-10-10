import { NextRequest, NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'
import { Readable } from 'stream'

const VIBE_OUTPUT_DIR = process.env.VIBE_OUTPUT_DIR ?? '/tmp/vibe'

const MIME: Record<string, string> = {
  '.wav': 'audio/wav',
  '.mp3': 'audio/mpeg',
}

export async function GET(
  _req: NextRequest,
  context: { params: Promise<{ filename: string }> }
) {
  const { filename } = await context.params

  // Reject path traversal attempts
  if (filename.includes('/') || filename.includes('..')) {
    return NextResponse.json({ error: 'invalid filename' }, { status: 400 })
  }

  const ext = path.extname(filename).toLowerCase()
  const mimeType = MIME[ext]
  if (!mimeType) {
    return NextResponse.json({ error: 'unsupported file type' }, { status: 415 })
  }

  const filePath = path.join(VIBE_OUTPUT_DIR, filename)

  if (!fs.existsSync(filePath)) {
    return NextResponse.json({ error: 'not found' }, { status: 404 })
  }

  const stat = fs.statSync(filePath)
  const fileStream = fs.createReadStream(filePath)

  // Node.js Readable → Web ReadableStream
  const webStream = Readable.toWeb(fileStream) as ReadableStream

  return new Response(webStream, {
    headers: {
      'Content-Type': mimeType,
      'Content-Length': String(stat.size),
      'Cache-Control': 'no-store',
      'Accept-Ranges': 'bytes',
    },
  })
}
