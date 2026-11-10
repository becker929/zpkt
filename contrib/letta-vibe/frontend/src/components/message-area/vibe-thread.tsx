'use client'

import { useState, useRef, useEffect, useMemo, type FC } from 'react'
import dynamic from 'next/dynamic'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  AssistantRuntimeProvider,
  useExternalStoreRuntime,
  ThreadPrimitive,
  type ThreadMessageLike,
  type AppendMessage,
} from '@assistant-ui/react'
import { Ellipsis, ArrowUpIcon, Music, Brain, ChevronDown, ChevronRight, CheckCircle2, Sparkles } from 'lucide-react'
import { Button } from '@/components/ui/button'
import {
  type VibeMessage,
  type VibeMessagePart,
  type QueuedMessage,
  type QueuedImprovement,
  type ImprovementJobStatus,
} from '@/types'
import { MessageQueue } from './message-queue'
import { ImprovementQueue } from './improvement-queue'
import { TEXTBOX_PLACEHOLDER } from '@/app/lib/labels'

const WaveformPlayer = dynamic(
  () => import('@/components/waveform-player').then((m) => m.WaveformPlayer),
  { ssr: false }
)

const SelfImproveProgress = dynamic(
  () => import('@/components/self-improve-progress').then((m) => m.SelfImproveProgress),
  { ssr: false }
)

const BOUNCE_MESSAGE = 'Bounce the current session and let me hear it.'

const TOOL_CALL_LABELS: Record<string, string> = {
  execute: 'Running in Ableton',
  api: 'Browsing Live API',
  search_api: 'Searching Live API',
  check_improvement: 'Checking improvement status',
  run_shell_command: 'Running shell command',
  restart_vibe_server: 'Restarting vibe server',
  analyze_audio: 'Analyzing audio',
  profile_audio: 'Running ears profile',
}

// ── Collapsible tool call pill ────────────────────────────────────────────────

const ToolCallPill: FC<{ name: string; args: string; result?: string; completed?: boolean }> = ({
  name, args, result, completed,
}) => {
  const [open, setOpen] = useState(false)
  const label = TOOL_CALL_LABELS[name] ?? name

  let parsedArgs: Record<string, unknown> | null = null
  try { parsedArgs = JSON.parse(args) } catch { /* keep null */ }

  return (
    <div className='w-full max-w-xl rounded-lg border border-border/60 bg-muted/40 overflow-hidden text-xs'>
      <button
        onClick={() => setOpen((o) => !o)}
        className='flex w-full items-center gap-2 px-3 py-1.5 text-left hover:bg-muted/70 transition-colors'
      >
        {completed
          ? <CheckCircle2 className='h-3.5 w-3.5 text-muted-foreground shrink-0' />
          : <Ellipsis className='h-3.5 w-3.5 animate-pulse text-muted-foreground shrink-0' />
        }
        <span className='flex-1 text-muted-foreground'>{label}{completed ? '' : '…'}</span>
        {open
          ? <ChevronDown className='h-3 w-3 text-muted-foreground shrink-0' />
          : <ChevronRight className='h-3 w-3 text-muted-foreground shrink-0' />
        }
      </button>

      {open && (
        <div className='border-t border-border/40 bg-background/50 px-3 py-2 font-mono text-xs text-muted-foreground space-y-1.5'>
          {parsedArgs && Object.keys(parsedArgs).length > 0 && (
            <div>
              <span className='text-foreground/50 uppercase tracking-wider text-[10px]'>args</span>
              {Object.entries(parsedArgs).map(([k, v]) => (
                <div key={k} className='flex gap-2'>
                  <span className='text-foreground/60 shrink-0'>{k}:</span>
                  <span className='break-all'>{typeof v === 'string' ? v : JSON.stringify(v)}</span>
                </div>
              ))}
            </div>
          )}
          {result && (
            <div>
              <span className='text-foreground/50 uppercase tracking-wider text-[10px]'>result</span>
              <div className='whitespace-pre-wrap break-all'>{result}</div>
            </div>
          )}
        </div>
      )}
    </div>
  )
}

// ── Message conversion ────────────────────────────────────────────────────────
// Used only to feed the assistant-ui runtime (for scroll/composer wiring).

function convertVibeMessage(msg: VibeMessage): ThreadMessageLike {
  return {
    id: msg.id,
    role: msg.role,
    content: msg.parts.map((part) => {
      if (part.type === 'text') {
        return { type: 'text' as const, text: part.text }
      }
      return { type: 'text' as const, text: '' }
    }),
  }
}

// ── Reasoning / Thinking indicators ──────────────────────────────────────────

const ThinkingIndicator: FC = () => (
  <div data-id='thinking' className='flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground'>
    <Brain className='h-4 w-4 animate-pulse' />
    <span className='animate-pulse'>Thinking…</span>
  </div>
)

const ReasoningBlock: FC<{ text: string }> = ({ text }) => (
  <div data-id='reasoning' className='flex items-start gap-2 rounded-lg border border-border/50 bg-muted/50 px-3 py-2 text-xs text-muted-foreground'>
    <Brain className='mt-0.5 h-3 w-3 shrink-0 opacity-60' />
    <span className='italic whitespace-pre-wrap'>{text}</span>
  </div>
)

// ── Flat part renderer ────────────────────────────────────────────────────────
// Renders a single VibeMessagePart in strict chronological order.

const MD_CLASSES = 'rounded-lg bg-muted px-3 py-2 text-sm [&_pre]:overflow-x-auto [&_pre]:rounded-md [&_pre]:my-2 [&_code]:text-xs [&_p]:mb-2 [&_p:last-child]:mb-0 [&_ul]:list-disc [&_ul]:pl-4 [&_ol]:list-decimal [&_ol]:pl-4 [&_li]:mb-1 [&_h1]:text-base [&_h1]:font-bold [&_h2]:text-sm [&_h2]:font-semibold [&_a]:text-primary [&_a]:underline [&_table]:w-full [&_table]:border-collapse [&_table]:my-2 [&_th]:border [&_th]:border-border [&_th]:px-2 [&_th]:py-1 [&_th]:bg-background/60 [&_th]:text-left [&_th]:text-xs [&_th]:font-semibold [&_td]:border [&_td]:border-border [&_td]:px-2 [&_td]:py-1 [&_td]:text-xs'

const PartView: FC<{ part: VibeMessagePart; role: 'user' | 'assistant' }> = ({ part, role }) => {
  if (role === 'user') {
    if (part.type !== 'text') return null
    return (
      <div className='flex justify-end'>
        <div className='max-w-[75%] rounded-lg bg-primary px-3 py-2 text-sm text-primary-foreground'>
          <span className='whitespace-pre-wrap'>{part.text}</span>
        </div>
      </div>
    )
  }

  // assistant parts
  switch (part.type) {
    case 'text':
      return (
        <div className='flex justify-start'>
          <div className={`max-w-[75%] ${MD_CLASSES}`}>
            <ReactMarkdown remarkPlugins={[remarkGfm]}>{part.text}</ReactMarkdown>
          </div>
        </div>
      )
    case 'audio':
      return (
        <div className='flex justify-start'>
          <div data-id={`waveform-${part.filename}`}>
            <WaveformPlayer url={part.url} filename={part.filename} className='ml-0' />
          </div>
        </div>
      )
    case 'bounce-loading':
      return (
        <div className='flex justify-start'>
          <div data-id='bounce-loading' className='flex items-center gap-2 rounded-lg bg-muted px-3 py-2 text-sm text-muted-foreground'>
            <Ellipsis className='h-4 w-4 animate-pulse' />
            <span>Bouncing audio from Ableton…</span>
          </div>
        </div>
      )
    case 'tool-call':
      return (
        <div className='flex justify-start'>
          <ToolCallPill name={part.name} args={part.args} result={part.result} completed={part.completed} />
        </div>
      )
    case 'self-improve-progress':
      return (
        <div className='flex justify-start'>
          <SelfImproveProgress jobId={part.jobId} description={part.description} vibeUrl={part.vibeUrl} />
        </div>
      )
    case 'reasoning':
      return (
        <div className='flex justify-start'>
          <ReasoningBlock text={part.text} />
        </div>
      )
    case 'thinking':
      return (
        <div className='flex justify-start'>
          <ThinkingIndicator />
        </div>
      )
    case 'hidden_reasoning':
      return (
        <div className='flex justify-start'>
          <div className='border-l-2 border-yellow-500 pl-3 my-2 text-sm text-muted-foreground'>
            <div className='font-mono text-xs'>Hidden Reasoning ({part.state})</div>
            {part.hiddenReasoning && <pre className='mt-1 text-xs whitespace-pre-wrap'>{part.hiddenReasoning}</pre>}
          </div>
        </div>
      )
    case 'approval_request':
      return (
        <div className='flex justify-start'>
          <div className='border-l-2 border-orange-500 pl-3 my-2 text-sm'>
            <div className='font-mono text-xs'>Approval Request</div>
            <div className='mt-1 text-xs'>
              <div><strong>Tool:</strong> {part.toolCall.name}</div>
              <div><strong>Args:</strong> <pre className='inline'>{part.toolCall.arguments}</pre></div>
              <div className='text-muted-foreground'>ID: {part.toolCall.id}</div>
            </div>
          </div>
        </div>
      )
    case 'approval_response':
      return (
        <div className='flex justify-start'>
          <div className='border-l-2 border-green-500 pl-3 my-2 text-sm'>
            <div className='font-mono text-xs'>Approval {part.approve ? 'Granted' : 'Denied'}</div>
            {part.reason && <div className='mt-1 text-xs italic'>{part.reason}</div>}
            <div className='text-xs text-muted-foreground'>Request ID: {part.approvalRequestId}</div>
          </div>
        </div>
      )
    case 'metadata':
      return (
        <div className='flex justify-start'>
          <details className='my-1'>
            <summary className='text-xs text-muted-foreground cursor-pointer font-mono'>metadata</summary>
            <div className='text-xs font-mono mt-1 bg-muted p-2 rounded'>
              {part.otid && <div>otid: {part.otid}</div>}
              {part.senderId && <div>senderId: {part.senderId}</div>}
              {part.stepId && <div>stepId: {part.stepId}</div>}
              {part.isErr !== undefined && <div>isErr: {String(part.isErr)}</div>}
              {part.seqId !== undefined && <div>seqId: {part.seqId}</div>}
              {part.runId && <div>runId: {part.runId}</div>}
            </div>
          </details>
        </div>
      )
    default:
      return null
  }
}

// ── Composer ──────────────────────────────────────────────────────────────────

interface VibeComposerProps {
  sendMessage: (text: string) => Promise<void>
  onEnqueue: (text: string) => void
  isRunning: boolean
  improvementCount: number
  onToggleImprovements: () => void
}

const VibeComposer: FC<VibeComposerProps> = ({ sendMessage, onEnqueue, isRunning, improvementCount, onToggleImprovements }) => {
  const [input, setInput] = useState('')
  const textAreaRef = useRef<HTMLTextAreaElement>(null)

  // Auto-resize textarea
  useEffect(() => {
    const el = textAreaRef.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = el.scrollHeight > 500 ? '500px' : `${el.scrollHeight}px`
  }, [input])

  const submit = () => {
    const trimmed = input.trim()
    if (!trimmed) return
    onEnqueue(trimmed)
    setInput('')
  }

  return (
    <div className='relative mx-auto w-full max-w-3xl px-4 pb-4'>
      <form
        onSubmit={(e) => { e.preventDefault(); submit() }}
        className='flex flex-col gap-2 rounded-xl border border-border bg-card p-3 shadow-sm'
      >
        <textarea
          ref={textAreaRef}
          data-id='message-input'
          rows={1}
          placeholder={TEXTBOX_PLACEHOLDER}
          value={input}
          onChange={(e) => setInput(e.target.value)}
          className='w-full resize-none bg-transparent text-sm placeholder:text-muted-foreground focus:outline-none max-h-[50dvh] overflow-y-auto'
          onKeyDown={(e) => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault()
              submit()
            }
          }}
        />
        <div className='flex items-center justify-between'>
          <div className='flex items-center gap-1.5'>
            <Button
              type='button'
              data-id='bounce-button'
              variant='outline'
              size='sm'
              className='gap-1.5 text-xs'
              disabled={isRunning}
              onClick={() => { if (!isRunning) sendMessage(BOUNCE_MESSAGE) }}
              title='Ask Letta to bounce the current session'
            >
              <Music className='h-3.5 w-3.5' />
              Bounce
            </Button>
            <Button
              type='button'
              variant='outline'
              size='sm'
              className='gap-1.5 text-xs'
              onClick={onToggleImprovements}
              title='Improvement queue'
            >
              <span className='relative'>
                <Sparkles className='h-3.5 w-3.5' />
                {improvementCount > 0 && (
                  <span className='absolute -top-1.5 -right-2 flex h-4 w-4 items-center justify-center rounded-full bg-purple-500 text-[10px] font-bold text-white'>
                    {improvementCount}
                  </span>
                )}
              </span>
            </Button>
          </div>

          <Button
            type='submit'
            size='icon'
            className='h-8 w-8'
            disabled={!input.trim()}
            aria-label='Send message'
          >
            <ArrowUpIcon className='h-4 w-4' />
          </Button>
        </div>
      </form>
    </div>
  )
}

// ── VibeThread ────────────────────────────────────────────────────────────────

interface VibeThreadProps {
  messages: VibeMessage[]
  status: 'ready' | 'submitted' | 'streaming' | 'error'
  sendMessage: (text: string) => Promise<void>
  queue: QueuedMessage[]
  onEnqueue: (text: string) => void
  onEditQueueItem: (id: string, text: string) => void
  onRemoveQueueItem: (id: string) => void
  onMoveQueueItemUp: (id: string) => void
  onMoveQueueItemDown: (id: string) => void
  onFlushQueue: () => void
  improvementQueue: QueuedImprovement[]
  currentJob: ImprovementJobStatus | null
  onRemoveImprovementItem: (id: string) => void
  onMoveImprovementItemUp: (id: string) => void
  onMoveImprovementItemDown: (id: string) => void
  onSubmitAllImprovements: () => void
}

export const VibeThread: FC<VibeThreadProps> = ({
  messages,
  status,
  sendMessage,
  queue,
  onEnqueue,
  onEditQueueItem,
  onRemoveQueueItem,
  onMoveQueueItemUp,
  onMoveQueueItemDown,
  onFlushQueue,
  improvementQueue,
  currentJob,
  onRemoveImprovementItem,
  onMoveImprovementItemUp,
  onMoveImprovementItemDown,
  onSubmitAllImprovements,
}) => {
  const [improvementPanelOpen, setImprovementPanelOpen] = useState(false)
  const isRunning = status === 'submitted' || status === 'streaming'

  // Deduplicate by id before handing to the runtime.
  const dedupedMessages = useMemo(() => {
    const seen = new Set<string>()
    return messages.filter((m) => {
      if (seen.has(m.id)) return false
      seen.add(m.id)
      return true
    })
  }, [messages])

  // Sort by timestamp for strict chronological rendering.
  const sortedMessages = useMemo(() =>
    [...dedupedMessages].sort((a, b) =>
      new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime()
    ),
    [dedupedMessages]
  )

  const onNew = async (msg: AppendMessage) => {
    const text =
      typeof msg.content === 'string'
        ? msg.content
        : msg.content.find((p) => p.type === 'text')?.text
    if (text) onEnqueue(text)
  }

  const runtime = useExternalStoreRuntime({
    isRunning,
    messages: dedupedMessages,
    convertMessage: convertVibeMessage,
    onNew,
  })

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      <ImprovementQueue
        open={improvementPanelOpen}
        onClose={() => setImprovementPanelOpen(false)}
        currentJob={currentJob}
        queue={improvementQueue}
        onRemove={onRemoveImprovementItem}
        onMoveUp={onMoveImprovementItemUp}
        onMoveDown={onMoveImprovementItemDown}
        onSubmitAll={onSubmitAllImprovements}
      />
      <ThreadPrimitive.Root className='flex flex-1 flex-col overflow-hidden'>
        <ThreadPrimitive.Viewport className='flex flex-1 flex-col gap-2 overflow-y-auto px-4 py-4'>
          {sortedMessages.map((msg) =>
            msg.parts.map((part, i) => (
              <PartView key={`${msg.id}-${i}`} part={part} role={msg.role} />
            ))
          )}
        </ThreadPrimitive.Viewport>

        <MessageQueue
          items={queue}
          onEdit={onEditQueueItem}
          onRemove={onRemoveQueueItem}
          onMoveUp={onMoveQueueItemUp}
          onMoveDown={onMoveQueueItemDown}
          onFlushAll={onFlushQueue}
        />

        <VibeComposer
          sendMessage={sendMessage}
          onEnqueue={onEnqueue}
          isRunning={isRunning}
          improvementCount={improvementQueue.length}
          onToggleImprovements={() => setImprovementPanelOpen((o) => !o)}
        />
      </ThreadPrimitive.Root>
    </AssistantRuntimeProvider>
  )
}
