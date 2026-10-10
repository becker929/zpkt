import { NextRequest, NextResponse } from 'next/server'
import client from '@/config/letta-client'
import { filterMessages, lettaToVibeMessages, extractAudioFilename } from './helpers'
import { validateAgentOwner } from '../../helpers'
import { Context, VibeSseChunk } from '@/types'

async function getAgentMessages(
  req: NextRequest,
  context: Context<{ agentId: string }>
) {
  const result = await validateAgentOwner(req, context)
  if (result instanceof NextResponse) return result
  const { agentId } = result

  try {
    const messages = await client.agents.messages.list(agentId, { limit: 100 })
    const filtered = filterMessages(messages)
    return NextResponse.json(lettaToVibeMessages(filtered))
  } catch (error) {
    console.error('Error fetching messages:', error)
    return NextResponse.json({ error: 'Error fetching messages' }, { status: 500 })
  }
}

function emitChunk(controller: ReadableStreamDefaultController, chunk: VibeSseChunk) {
  const encoder = new TextEncoder()
  controller.enqueue(encoder.encode(`data: ${JSON.stringify(chunk)}\n\n`))
}

async function sendMessage(
  req: NextRequest,
  context: Context<{ agentId: string }>
) {
  const validate = await validateAgentOwner(req, context)
  if (validate instanceof NextResponse) return validate
  const { agentId } = validate

  const { text } = await req.json()
  if (!text?.trim()) {
    return NextResponse.json({ error: 'text is required' }, { status: 400 })
  }

  const encoder = new TextEncoder()

  const sendHeartbeat = (controller: ReadableStreamDefaultController) => {
    try { controller.enqueue(encoder.encode(': heartbeat\n\n')) } catch { /* stream closed */ }
  }

  const readable = new ReadableStream({
    async start(controller) {
      // Periodic heartbeat flushes the OS TCP send buffer so SSE chunks
      // (especially tool_call events for long-running tools like request_improvement)
      // are delivered to the browser immediately rather than sitting in the buffer
      // for minutes waiting for more data.
      const heartbeat = setInterval(() => sendHeartbeat(controller), 3000)

      try {
        const stream = await client.agents.messages.createStream(agentId, {
          messages: [{ role: 'user', content: text }],
        })

        // Track the most recent tool call name so we only extract audio filenames
        // for run_bounce returns — not for analyze_audio or other tools whose
        // return strings may happen to contain a .mp3 filename.
        let lastToolName = ''

        for await (const chunk of stream) {
          const c = chunk as any
          const mt: string = c.messageType ?? c.message_type ?? ''

          if (mt === 'reasoning_message') {
            const text: string = c.reasoning ?? c.content ?? ''
            if (text) emitChunk(controller, { type: 'reasoning', text })
            continue
          }

          if (mt === 'assistant_message') {
            const text: string = c.content ?? ''
            if (text) emitChunk(controller, { type: 'text', text })
            continue
          }

          if (mt === 'tool_call_message') {
            const name: string = c.toolCall?.name ?? c.tool_call?.name ?? ''
            const args: string = c.toolCall?.arguments ?? c.tool_call?.arguments ?? ''
            lastToolName = name
            emitChunk(controller, { type: 'tool_call', name, args })
            // Send an immediate heartbeat after tool_call to guarantee the chunk
            // is flushed before the tool starts executing (which may take minutes).
            sendHeartbeat(controller)
            continue
          }

          if (mt === 'tool_return_message') {
            const returnStr: string =
              typeof c.toolReturn === 'string'
                ? c.toolReturn
                : typeof c.tool_return === 'string'
                  ? c.tool_return
                  : JSON.stringify(c.toolReturn ?? c.tool_return ?? '')
            // Only extract audio filenames for run_bounce — other tools (analyze_audio,
            // run_shell_command, etc.) may return strings containing .mp3 paths that
            // must NOT trigger a waveform player in the UI.
            const filename = lastToolName === 'run_bounce' ? extractAudioFilename(returnStr) : null
            lastToolName = ''
            emitChunk(controller, {
              type: 'tool_return',
              ...(filename ? { filename } : {}),
              returnValue: returnStr,
            })
          }
        }

        emitChunk(controller, { type: 'done' })
      } catch (err) {
        const message = err instanceof Error ? err.message : String(err)
        emitChunk(controller, { type: 'error', message })
      } finally {
        clearInterval(heartbeat)
        controller.close()
      }
    },
  })

  return new Response(readable, {
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      Connection: 'keep-alive',
      'X-Accel-Buffering': 'no',
    },
  })
}

export const GET = getAgentMessages
export const POST = sendMessage
