import { NextResponse } from 'next/server'
import fs from 'fs'
import path from 'path'

const VIBE_OUTPUT_DIR = process.env.VIBE_OUTPUT_DIR ?? '/tmp/vibe'
const VIBE_SERVER_URL = process.env.VIBE_SERVER_URL ?? 'http://localhost:8080'

export interface RenderEntry {
  filename: string
  timestamp: string
  beats?: number
  size?: number
}

export async function GET() {
  // Try vibe server first — it has beats metadata
  try {
    const res = await fetch(`${VIBE_SERVER_URL}/history`, {
      signal: AbortSignal.timeout(2000),
    })
    if (res.ok) {
      const data = await res.json() as { bounces: Array<{ filename: string; timestamp: string; beats: number }> }
      const renders: RenderEntry[] = (data.bounces ?? [])
        .map((b) => ({ filename: b.filename, timestamp: b.timestamp, beats: b.beats }))
        .reverse() // most recent first
      return NextResponse.json({ renders })
    }
  } catch {
    // fall through to filesystem
  }

  // Fallback: scan filesystem
  if (!fs.existsSync(VIBE_OUTPUT_DIR)) {
    return NextResponse.json({ renders: [] as RenderEntry[] })
  }

  try {
    const files = fs.readdirSync(VIBE_OUTPUT_DIR)
    const renders: RenderEntry[] = files
      .filter((f) => /\.(mp3|wav)$/i.test(f))
      .map((f) => {
        const filePath = path.join(VIBE_OUTPUT_DIR, f)
        const stat = fs.statSync(filePath)
        return { filename: f, timestamp: stat.mtime.toISOString(), size: stat.size }
      })
      .sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
    return NextResponse.json({ renders })
  } catch {
    return NextResponse.json({ renders: [] as RenderEntry[] })
  }
}
