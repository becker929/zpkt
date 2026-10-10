'use client'

import { useEffect, useRef, useState, type ReactNode } from 'react'
import { ChevronDown, ChevronRight, CheckCircle, XCircle, Loader2 } from 'lucide-react'

/** Render **bold** and *italic* markers inside a single log line. */
function renderLogLine(text: string): ReactNode {
  const tokens = text.split(/(\*\*[^*\n]+\*\*|\*[^*\n]+\*)/g)
  return tokens.map((token, i) => {
    if (token.startsWith('**') && token.endsWith('**')) {
      return <strong key={i} className='font-semibold text-foreground'>{token.slice(2, -2)}</strong>
    }
    if (token.startsWith('*') && token.endsWith('*')) {
      return <em key={i}>{token.slice(1, -1)}</em>
    }
    return token
  })
}

interface SseLogLine {
  line?: string
  index?: number
  status?: 'completed' | 'failed'
  changed_files?: string[]
  restarted_services?: string[]
  agent_result?: string
  error?: string
  setup_tools_run?: boolean
}

type JobStatus = 'connecting' | 'running' | 'completed' | 'failed'

interface Props {
  jobId: string
  description: string
  vibeUrl: string
}

const MAX_RECONNECTS = 4
const RECONNECT_DELAYS_MS = [2000, 4000, 8000, 12000]

export function SelfImproveProgress({ jobId, description, vibeUrl }: Props) {
  const [logLines, setLogLines] = useState<string[]>([])
  const [jobStatus, setJobStatus] = useState<JobStatus>('connecting')
  const [summary, setSummary] = useState<string | null>(null)
  const [errorMsg, setErrorMsg] = useState<string | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const logEndRef = useRef<HTMLDivElement>(null)
  const esRef = useRef<EventSource | null>(null)
  // Track reconnect attempts so onerror retries before giving up
  const reconnectCountRef = useRef(0)
  const reconnectTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const isFinalRef = useRef(false)

  useEffect(() => {
    if (!vibeUrl) return

    function connect() {
      const es = new EventSource(`${vibeUrl}/self-improve/stream`)
      esRef.current = es

      es.onopen = () => {
        reconnectCountRef.current = 0
        setJobStatus((s) => s === 'connecting' ? 'running' : s)
      }

      es.onmessage = (event) => {
        try {
          const data: SseLogLine = JSON.parse(event.data)

          if (data.line !== undefined) {
            setLogLines((prev) => [...prev, data.line!])
            return
          }

          if (data.status === 'completed') {
            const parts: string[] = []
            if (data.changed_files?.length) parts.push(`Changed: ${data.changed_files.join(', ')}`)
            if (data.restarted_services?.length) parts.push(`Restarted: ${data.restarted_services.join(', ')}`)
            if (data.setup_tools_run) parts.push('Re-registered tools')
            if (data.agent_result) parts.push(data.agent_result.slice(0, 200))
            setSummary(parts.join(' | ') || 'Done.')
            isFinalRef.current = true
            setJobStatus('completed')
            es.close()
            return
          }

          if (data.status === 'failed') {
            setErrorMsg(data.error ?? 'Unknown error')
            isFinalRef.current = true
            setJobStatus('failed')
            es.close()
            return
          }

          // "idle" after a reconnect means the server restarted and cleared in-memory
          // state. The job may have completed — retry to pick up the persisted result.
          if (data.status === 'idle') {
            es.close()
            scheduleReconnect()
          }
        } catch {
          // ignore malformed events
        }
      }

      es.onerror = () => {
        es.close()
        if (!isFinalRef.current) {
          scheduleReconnect()
        }
      }
    }

    function scheduleReconnect() {
      if (isFinalRef.current) return
      const attempt = reconnectCountRef.current
      if (attempt >= MAX_RECONNECTS) {
        setErrorMsg('Lost connection to vibe server after retries.')
        setJobStatus('failed')
        return
      }
      reconnectCountRef.current += 1
      const delay = RECONNECT_DELAYS_MS[attempt] ?? 12000
      reconnectTimerRef.current = setTimeout(connect, delay)
    }

    connect()

    return () => {
      isFinalRef.current = true
      esRef.current?.close()
      esRef.current = null
      if (reconnectTimerRef.current) clearTimeout(reconnectTimerRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [vibeUrl])

  // Auto-scroll log to bottom as lines arrive
  useEffect(() => {
    if (!collapsed) {
      logEndRef.current?.scrollIntoView({ behavior: 'smooth' })
    }
  }, [logLines, collapsed])

  const statusIcon = () => {
    if (jobStatus === 'completed') return <CheckCircle className='h-4 w-4 text-green-500 shrink-0' />
    if (jobStatus === 'failed') return <XCircle className='h-4 w-4 text-destructive shrink-0' />
    return <Loader2 className='h-4 w-4 animate-spin text-muted-foreground shrink-0' />
  }

  const statusLabel = () => {
    if (jobStatus === 'connecting') return 'Connecting…'
    if (jobStatus === 'running') return `Improving agent${jobId ? ` (${jobId})` : ''}…`
    if (jobStatus === 'completed') return 'Improvement complete'
    return 'Improvement failed'
  }

  return (
    <div className='w-full max-w-xl rounded-lg border border-border bg-muted/50 overflow-hidden text-sm'>
      {/* Header row */}
      <button
        onClick={() => setCollapsed((c) => !c)}
        className='flex w-full items-center gap-2 px-3 py-2 text-left hover:bg-muted/80 transition-colors'
      >
        {statusIcon()}
        <span className='flex-1 font-medium text-foreground truncate'>{statusLabel()}</span>
        <span className='text-xs text-muted-foreground break-words'>{description}</span>
        {collapsed
          ? <ChevronRight className='h-3.5 w-3.5 text-muted-foreground shrink-0' />
          : <ChevronDown className='h-3.5 w-3.5 text-muted-foreground shrink-0' />
        }
      </button>

      {!collapsed && (
        <>
          {/* Log panel */}
          {logLines.length > 0 && (
            <div className='max-h-48 overflow-y-auto border-t border-border bg-background/60 px-3 py-2 font-mono text-xs text-muted-foreground leading-relaxed'>
              {logLines.map((line, i) => (
                <div key={i} className='whitespace-pre-wrap break-all mb-0.5 last:mb-0'>
                  {renderLogLine(line)}
                </div>
              ))}
              <div ref={logEndRef} />
            </div>
          )}

          {/* Summary / error footer */}
          {(summary || errorMsg) && (
            <div className={`border-t border-border px-3 py-2 text-xs ${
              jobStatus === 'failed' ? 'text-destructive' : 'text-muted-foreground'
            }`}>
              {summary ?? errorMsg}
            </div>
          )}
        </>
      )}
    </div>
  )
}
