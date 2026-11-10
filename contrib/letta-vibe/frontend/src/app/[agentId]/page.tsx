'use client'

import { useEffect, useCallback, useState } from 'react'
import { VibeThread } from '@/components/message-area/vibe-thread'
import { useAgentDetails } from '@/components/ui/agent-details'
import { AgentDetailDisplay } from '@/components/agent-details/agent-details-display'
import { useIsMobile } from '@/components/hooks/use-mobile'
import { useAgentMessages } from '@/components/hooks/use-agent-messages'
import { useAgentIdParam } from '@/components/hooks/use-agentId-param'
import { useVibeChat } from '@/components/hooks/use-vibe-chat'
import { useMessageQueue } from '@/components/hooks/use-message-queue'
import { useImprovementQueue } from '@/components/hooks/use-improvement-queue'
import { toast } from 'sonner'
import { Toaster } from '@/components/ui/sonner'
import { useQueryClient } from '@tanstack/react-query'
import { type ImprovementJobStatus } from '@/types'

const VIBE_URL = 'http://localhost:8080'

export default function Home() {
  const agentId = useAgentIdParam()
  const { isOpen } = useAgentDetails()
  const isMobile = useIsMobile()
  const queryClient = useQueryClient()

  const {
    data: agentMessages,
    isLoading: agentMessagesIsLoading,
    error: agentMessagesError,
  } = useAgentMessages(agentId ?? '')

  useEffect(() => {
    if (agentMessagesError) {
      toast.error('Failed to load messages. Check your Letta server connection.')
    }
  }, [agentMessagesError])

  const handleBounce = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ['render-history'] })
  }, [queryClient])

  const { messages, setMessages, status, sendMessage } = useVibeChat({
    agentId: agentId ?? '',
    initialMessages: agentMessages ?? [],
    onBounce: handleBounce,
  })

  const [currentJob, setCurrentJob] = useState<ImprovementJobStatus | null>(null)

  useEffect(() => {
    const poll = async () => {
      try {
        const res = await fetch(`${VIBE_URL}/self-improve/status`)
        if (!res.ok) return
        const data = await res.json()
        if (data.status && data.status !== 'idle') {
          setCurrentJob({
            jobId: data.job_id ?? '',
            description: data.description ?? '',
            status: data.status as 'running' | 'completed' | 'failed',
            startedAt: data.started_at ?? new Date().toISOString(),
            error: data.error,
          })
        } else {
          setCurrentJob(null)
        }
      } catch { /* vibe server not running */ }
    }
    poll()
    const id = setInterval(poll, 5000)
    return () => clearInterval(id)
  }, [])

  const { queue, enqueue, editItem, removeItem, moveUp, moveDown, flushQueue } = useMessageQueue(
    agentId ?? ''
  )

  const {
    queue: improvementQueue,
    enqueue: enqueueImprovement,
    editItem: editImprovementItem,
    removeItem: removeImprovementItem,
    moveUp: moveImprovementUp,
    moveDown: moveImprovementDown,
    flushQueue: flushImprovementQueue,
  } = useImprovementQueue(agentId ?? '')

  // Auto-send all queued messages whenever the agent is idle and the queue is non-empty.
  // This covers both: agent just finished a turn, and items added while agent is already idle.
  useEffect(() => {
    if (status === 'ready' && queue.length > 0) {
      const texts = flushQueue()
      if (texts.length > 0) {
        sendMessage(texts.join('\n\n'))
      }
    }
  }, [status, queue, flushQueue, sendMessage])

  // Manual flush — send all queued messages now regardless of agent state.
  const handleFlushQueue = useCallback(() => {
    const texts = flushQueue()
    if (texts.length > 0) {
      sendMessage(texts.join('\n\n'))
    }
  }, [flushQueue, sendMessage])

  // Submit all improvements sequentially — each is sent as a separate message
  // and the internal pendingQueue in useVibeChat sequences them automatically.
  const handleSubmitAllImprovements = useCallback(() => {
    const items = flushImprovementQueue()
    for (const item of items) {
      sendMessage(`[Self-Improvement Request] ${item.description}\n\n${item.prompt}`)
    }
  }, [flushImprovementQueue, sendMessage])

  // Sync server messages into local state when the agent is idle.
  // The `status === 'ready'` guard prevents polling updates from clobbering an active stream.
  useEffect(() => {
    if (status === 'ready' && agentMessages !== undefined) {
      setMessages(agentMessages)
    }
  }, [agentMessages, status, setMessages])

  if (!agentId) return null

  return (
    <>
      <div className='flex flex-1 overflow-hidden'>
        {(!isMobile || (isMobile && !isOpen)) && (
          <div className='flex flex-1 flex-col overflow-hidden'>
            {!agentMessagesIsLoading && (
              <VibeThread
                messages={messages}
                status={status}
                sendMessage={sendMessage}
                queue={queue}
                onEnqueue={enqueue}
                onEditQueueItem={editItem}
                onRemoveQueueItem={removeItem}
                onMoveQueueItemUp={moveUp}
                onMoveQueueItemDown={moveDown}
                onFlushQueue={handleFlushQueue}
                improvementQueue={improvementQueue}
                currentJob={currentJob}
                onRemoveImprovementItem={removeImprovementItem}
                onMoveImprovementItemUp={moveImprovementUp}
                onMoveImprovementItemDown={moveImprovementDown}
                onSubmitAllImprovements={handleSubmitAllImprovements}
              />
            )}
          </div>
        )}

        {isOpen && (
          <div
            className={`${isMobile ? 'w-full' : 'w-80 border-l border-border'} overflow-y-auto`}
          >
            <AgentDetailDisplay />
          </div>
        )}
      </div>
      <Toaster />
    </>
  )
}
