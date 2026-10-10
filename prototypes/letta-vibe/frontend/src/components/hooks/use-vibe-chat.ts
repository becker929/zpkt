'use client'

import { useState, useCallback, useRef, useEffect } from 'react'
import { toast } from 'sonner'
import { VibeMessage, VibeSseChunk } from '@/types'

type ChatStatus = 'ready' | 'submitted' | 'streaming' | 'error'

interface UseVibeChatOptions {
  agentId: string
  initialMessages?: VibeMessage[]
  onBounce?: () => void
}

interface UseVibeChatReturn {
  messages: VibeMessage[]
  setMessages: React.Dispatch<React.SetStateAction<VibeMessage[]>>
  status: ChatStatus
  sendMessage: (text: string) => Promise<void>
}

const VIBE_URL = process.env.NEXT_PUBLIC_VIBE_SERVER_URL ?? 'http://localhost:8080'

/** Extract job_id from the return string "Improvement job started (id: abc123). ..." */
function extractJobId(returnStr: string): string | null {
  const match = returnStr.match(/\(id:\s*([a-f0-9-]+)\)/i)
  return match ? match[1] : null
}

function isAudioFilename(value: string): boolean {
  return /\.(wav|mp3)$/i.test(value)
}

export function useVibeChat({ agentId, initialMessages = [], onBounce }: UseVibeChatOptions): UseVibeChatReturn {
  const [messages, setMessages] = useState<VibeMessage[]>(initialMessages)
  const [status, setStatus] = useState<ChatStatus>('ready')
  // Track the last tool call name so tool_return can correlate to it
  const lastToolCallRef = useRef<string | null>(null)
  // FIFO queue of messages submitted while the agent is busy
  const pendingQueue = useRef<string[]>([])

  const sendMessage = useCallback(
    async (text: string) => {
      if (status === 'submitted' || status === 'streaming') {
        pendingQueue.current.push(text)
        return
      }

      const userMsg: VibeMessage = {
        id: crypto.randomUUID(),
        role: 'user',
        parts: [{ type: 'text', text }],
        timestamp: new Date().toISOString(),
      }

      // Thinking placeholder — removed on first real chunk
      const thinkingId = crypto.randomUUID()
      const pendingAssistant: VibeMessage = {
        id: thinkingId,
        role: 'assistant',
        parts: [{ type: 'thinking' as const }],
        timestamp: new Date().toISOString(),
      }

      setMessages((prev) => [...prev, userMsg, pendingAssistant])
      setStatus('submitted')
      lastToolCallRef.current = null

      // Track whether the thinking placeholder has been removed this turn
      let thinkingRemoved = false

      try {
        const response = await fetch(`/api/agents/${agentId}/messages`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ text }),
        })

        if (!response.ok) throw new Error(`HTTP ${response.status}`)
        if (!response.body) throw new Error('No response body')

        setStatus('streaming')

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''

        const applyChunk = (chunk: VibeSseChunk) => {
          setMessages((prev) => {
            // Remove thinking placeholder on first real chunk
            let base = prev
            if (!thinkingRemoved) {
              base = prev.filter((m) => m.id !== thinkingId)
              thinkingRemoved = true
            }

            const newId = crypto.randomUUID()
            const ts = new Date().toISOString()

            if (chunk.type === 'reasoning') {
              return [...base, { id: newId, role: 'assistant' as const, parts: [{ type: 'reasoning' as const, text: chunk.text }], timestamp: ts }]
            }

            if (chunk.type === 'text') {
              return [...base, { id: newId, role: 'assistant' as const, parts: [{ type: 'text' as const, text: chunk.text }], timestamp: ts }]
            }

            if (chunk.type === 'tool_call') {
              lastToolCallRef.current = chunk.name

              if (chunk.name === 'run_bounce') {
                return [...base, { id: newId, role: 'assistant' as const, parts: [{ type: 'bounce-loading' as const }], timestamp: ts }]
              }

              if (chunk.name === 'request_improvement') {
                let description = 'improvement'
                try {
                  const parsed = JSON.parse(chunk.args)
                  description = parsed.description ?? description
                } catch { /* ignore */ }
                return [
                  ...base,
                  {
                    id: newId,
                    role: 'assistant' as const,
                    parts: [{ type: 'self-improve-progress' as const, jobId: '', description, vibeUrl: VIBE_URL }],
                    timestamp: ts,
                  },
                ]
              }

              return [...base, { id: newId, role: 'assistant' as const, parts: [{ type: 'tool-call' as const, name: chunk.name, args: chunk.args }], timestamp: ts }]
            }

            if (chunk.type === 'tool_return') {
              const toolName = lastToolCallRef.current
              lastToolCallRef.current = null

              if (toolName === 'request_improvement') {
                const jobId = extractJobId(chunk.returnValue ?? '') ?? ''
                return base.map((m) => {
                  const hasPending = m.parts.some((p) => p.type === 'self-improve-progress' && p.jobId === '')
                  if (!hasPending) return m
                  return {
                    ...m,
                    parts: m.parts.map((p) =>
                      p.type === 'self-improve-progress' && p.jobId === '' ? { ...p, jobId } : p
                    ),
                  }
                })
              }

              if (toolName === 'run_bounce') {
                if (chunk.filename && isAudioFilename(chunk.filename)) {
                  onBounce?.()
                  const withoutBounce = base.filter((m) => !m.parts.some((p) => p.type === 'bounce-loading'))
                  return [
                    ...withoutBounce,
                    {
                      id: newId,
                      role: 'assistant' as const,
                      parts: [{ type: 'audio' as const, filename: chunk.filename, url: `/api/audio/${chunk.filename}` }],
                      timestamp: ts,
                    },
                  ]
                }
                return base.filter((m) => !m.parts.some((p) => p.type === 'bounce-loading'))
              }

              // For all other tools: mark the matching tool-call part as completed
              return base.map((m) => {
                const hasMatch = m.parts.some((p) => p.type === 'tool-call' && p.name === toolName && !p.completed)
                if (!hasMatch) return m
                return {
                  ...m,
                  parts: m.parts.map((p) =>
                    p.type === 'tool-call' && p.name === toolName && !p.completed
                      ? { ...p, completed: true, result: chunk.returnValue ?? '' }
                      : p
                  ),
                }
              })
            }

            return base
          })
        }

        while (true) {
          const { done, value } = await reader.read()
          if (done) break

          buffer += decoder.decode(value, { stream: true })
          const lines = buffer.split('\n')
          buffer = lines.pop() ?? ''

          for (const line of lines) {
            if (!line.startsWith('data: ')) continue
            const data = line.slice(6).trim()
            if (!data) continue

            try {
              const chunk = JSON.parse(data) as VibeSseChunk
              if (chunk.type === 'done') {
                // Clean up any stray thinking placeholder
                setMessages((prev) => prev.filter((m) => m.id !== thinkingId))
                setStatus('ready')
                return
              }
              if (chunk.type === 'error') {
                toast.error(chunk.message ?? 'Agent error')
                setMessages((prev) => prev.filter((m) => m.id !== thinkingId))
                setStatus('error')
                return
              }
              applyChunk(chunk)
            } catch {
              // skip malformed line
            }
          }
        }

        setMessages((prev) => prev.filter((m) => m.id !== thinkingId))
        setStatus('ready')
      } catch (err) {
        console.error('sendMessage error:', err)
        toast.error('Failed to send message. Check Letta server connection.')
        setMessages((prev) => prev.filter((m) => m.id !== thinkingId))
        setStatus('error')
      }
    },
    [agentId, status]
  )

  // Drain the queue one item at a time whenever the agent finishes
  useEffect(() => {
    if (status === 'ready' && pendingQueue.current.length > 0) {
      const next = pendingQueue.current.shift()!
      sendMessage(next)
    }
  }, [status, sendMessage])

  return { messages, setMessages, status, sendMessage }
}
