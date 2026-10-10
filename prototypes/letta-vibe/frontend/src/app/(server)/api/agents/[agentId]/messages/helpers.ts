import path from 'path'
import { MESSAGE_TYPE, VibeMessage, LettaMessageUnion } from '@/types'

const VIBE_URL = process.env.VIBE_SERVER_URL ?? 'http://localhost:8080'

/** Extract job_id from a tool_return string like "Improvement job started (id: abc123). ..." */
function extractJobId(returnStr: string): string | null {
  const match = returnStr.match(/\(id:\s*([a-f0-9-]+)\)/i)
  return match ? match[1] : null
}

export function filterMessages(messages: LettaMessageUnion[]) {
  const MESSAGE_TYPES_TO_HIDE = [MESSAGE_TYPE.SYSTEM_MESSAGE]

  return (
    messages
      .filter((message: any) => {
        try {
          if (
            message.messageType === MESSAGE_TYPE.USER_MESSAGE &&
            typeof message.content === 'string'
          ) {
            const parsed = JSON.parse(message.content)
            if (parsed?.type === 'heartbeat') return false
          }
        } catch {
          if (MESSAGE_TYPES_TO_HIDE.includes(<MESSAGE_TYPE>message.messageType)) return false
          return true
        }
        if (MESSAGE_TYPES_TO_HIDE.includes(<MESSAGE_TYPE>message.messageType)) return false
        return true
      })
      // @ts-ignore
      .sort((a, b) => a.date - b.date)
  )
}

/** Extract a bare filename from a tool_return value that may be JSON or a raw path. */
export function extractAudioFilename(toolReturn: string): string | null {
  try {
    const parsed = JSON.parse(toolReturn)
    const filePath: string = parsed?.path ?? parsed?.filename ?? ''
    if (/\.(wav|mp3)$/i.test(filePath)) return path.basename(filePath)
  } catch {
    // not JSON — try raw string
    const match = toolReturn.match(/[\w/\\.-]+\.(wav|mp3)/i)
    if (match) return path.basename(match[0])
  }
  return null
}

/** Convert filtered Letta messages to VibeMessage[].
 *  Each Letta message becomes its own VibeMessage — no grouping. */
export function lettaToVibeMessages(messages: LettaMessageUnion[]): VibeMessage[] {
  const vibeMessages: VibeMessage[] = []
  const seenIds = new Set<string>()
  let pendingToolCall: { id: string; name: string; args: string; timestamp: string } | null = null

  for (const msg of messages) {
    const m = msg as any
    const rawId: string = m.id ?? crypto.randomUUID()
    // Letta can occasionally return duplicate message IDs; deduplicate defensively.
    const id = seenIds.has(rawId) ? crypto.randomUUID() : rawId
    seenIds.add(id)
    const timestamp: string = m.date ?? m.createdAt ?? new Date().toISOString()

    if (m.messageType === 'user_message') {
      let text = typeof m.content === 'string' ? m.content : JSON.stringify(m.content)
      try {
        const parsed = JSON.parse(text)
        if (parsed?.message) text = parsed.message
      } catch {}
      vibeMessages.push({ id, role: 'user', parts: [{ type: 'text', text }], timestamp })
      continue
    }

    if (m.messageType === 'assistant_message') {
      const text = typeof m.content === 'string' ? m.content : JSON.stringify(m.content)
      vibeMessages.push({ id, role: 'assistant', parts: [{ type: 'text', text }], timestamp })
      continue
    }

    if (m.messageType === 'reasoning_message') {
      const text = typeof m.reasoning === 'string' ? m.reasoning
        : typeof m.content === 'string' ? m.content
        : JSON.stringify(m.reasoning ?? m.content ?? '')
      vibeMessages.push({ id, role: 'assistant', parts: [{ type: 'reasoning', text }], timestamp })
      continue
    }

    if (m.messageType === 'hidden_reasoning_message') {
      vibeMessages.push({
        id, role: 'assistant', timestamp,
        parts: [{
          type: 'hidden_reasoning',
          state: m.state as 'redacted' | 'omitted',
          hiddenReasoning: m.hiddenReasoning ?? m.hidden_reasoning,
        }],
      })
      continue
    }

    if (m.messageType === 'approval_request_message') {
      vibeMessages.push({
        id, role: 'assistant', timestamp,
        parts: [{
          type: 'approval_request',
          toolCall: {
            name: m.toolCall?.name ?? m.tool_call?.name ?? '',
            arguments: m.toolCall?.arguments ?? m.tool_call?.arguments ?? '',
            id: m.toolCall?.id ?? m.tool_call?.id ?? '',
          },
        }],
      })
      continue
    }

    if (m.messageType === 'approval_response_message') {
      vibeMessages.push({
        id, role: 'assistant', timestamp,
        parts: [{
          type: 'approval_response',
          approve: m.approve,
          approvalRequestId: m.approvalRequestId ?? m.approval_request_id ?? '',
          reason: m.reason,
        }],
      })
      continue
    }

    if (m.messageType === 'tool_call_message') {
      // Store pending; will be merged with the next tool_return_message
      pendingToolCall = {
        id,
        name: m.toolCall?.name ?? m.tool_call?.name ?? '',
        args: m.toolCall?.arguments ?? m.tool_call?.arguments ?? '',
        timestamp,
      }
      continue
    }

    if (m.messageType === 'tool_return_message') {
      const returnStr = typeof m.toolReturn === 'string' ? m.toolReturn : JSON.stringify(m.toolReturn ?? '')

      if (!pendingToolCall) {
        // orphaned tool_return with no matching call — skip
        continue
      }

      const { id: callId, name, args, timestamp: callTimestamp } = pendingToolCall
      pendingToolCall = null

      if (name === 'run_bounce') {
        const filename = extractAudioFilename(returnStr)
        if (filename) {
          vibeMessages.push({
            id: callId,
            role: 'assistant',
            parts: [{ type: 'audio', filename, url: `/api/audio/${filename}` }],
            timestamp: callTimestamp,
          })
        }
        continue
      }

      if (name === 'request_improvement') {
        let description = 'improvement'
        try {
          const parsed = JSON.parse(args)
          description = parsed.description ?? description
        } catch {}
        const jobId = extractJobId(returnStr) ?? ''
        vibeMessages.push({
          id: callId,
          role: 'assistant',
          parts: [{ type: 'self-improve-progress', jobId, description, vibeUrl: VIBE_URL }],
          timestamp: callTimestamp,
        })
        continue
      }

      vibeMessages.push({
        id: callId,
        role: 'assistant',
        parts: [{ type: 'tool-call', name, args, result: returnStr, completed: true }],
        timestamp: callTimestamp,
      })
      continue
    }

    // Unhandled message type — expose metadata if present
    const meta = m as any
    if (meta.otid || meta.senderId || meta.sender_id || meta.stepId || meta.step_id ||
        meta.isErr !== undefined || meta.is_err !== undefined ||
        meta.seqId !== undefined || meta.seq_id !== undefined || meta.runId || meta.run_id) {
      vibeMessages.push({
        id, role: 'assistant', timestamp,
        parts: [{
          type: 'metadata',
          otid: meta.otid,
          senderId: meta.senderId ?? meta.sender_id,
          stepId: meta.stepId ?? meta.step_id,
          isErr: meta.isErr ?? meta.is_err,
          seqId: meta.seqId ?? meta.seq_id,
          runId: meta.runId ?? meta.run_id,
        }],
      })
    }
  }

  // Flush any tool_call_message that had no matching tool_return (edge case: last message)
  if (pendingToolCall) {
    vibeMessages.push({
      id: pendingToolCall.id,
      role: 'assistant',
      parts: [{ type: 'tool-call', name: pendingToolCall.name, args: pendingToolCall.args, completed: false }],
      timestamp: pendingToolCall.timestamp,
    })
  }

  return vibeMessages
}
