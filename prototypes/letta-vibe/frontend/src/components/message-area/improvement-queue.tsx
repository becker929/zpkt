'use client'

import { useRef, type FC } from 'react'
import { X } from 'lucide-react'
import { type QueuedImprovement, type ImprovementJobStatus } from '@/types'
import { ImprovementQueueItem } from './improvement-queue-item'
import { SelfImproveInlineStatus } from './improvement-queue-status'

interface ImprovementQueueProps {
  open: boolean
  onClose: () => void
  currentJob: ImprovementJobStatus | null
  queue: QueuedImprovement[]
  onRemove: (id: string) => void
  onMoveUp: (id: string) => void
  onMoveDown: (id: string) => void
  onSubmitAll: () => void
}

export const ImprovementQueue: FC<ImprovementQueueProps> = ({
  open,
  onClose,
  currentJob,
  queue,
  onRemove,
  onMoveUp,
  onMoveDown,
  onSubmitAll,
}) => {
  const posRef = useRef<{ left: number; top: number } | null>(null)
  const popoverRef = useRef<HTMLDivElement>(null)

  const handleMouseDown = (e: React.MouseEvent) => {
    // Don't start drag on the close button
    if ((e.target as HTMLElement).closest('button')) return
    e.preventDefault()

    const el = popoverRef.current
    if (!el) return

    // On first drag: capture current rendered position and switch to left/top
    if (!posRef.current) {
      const rect = el.getBoundingClientRect()
      posRef.current = { left: rect.left, top: rect.top }
      el.style.right = 'unset'
      el.style.left = `${posRef.current.left}px`
      el.style.top = `${posRef.current.top}px`
    }

    const handleMove = (ev: MouseEvent) => {
      if (!posRef.current || !el) return
      posRef.current.left += ev.movementX
      posRef.current.top += ev.movementY
      el.style.left = `${posRef.current.left}px`
      el.style.top = `${posRef.current.top}px`
    }

    const handleUp = () => {
      window.removeEventListener('mousemove', handleMove)
      window.removeEventListener('mouseup', handleUp)
    }

    window.addEventListener('mousemove', handleMove)
    window.addEventListener('mouseup', handleUp)
  }

  if (!open) return null

  const isEmpty = !currentJob && queue.length === 0

  return (
    <div
      ref={popoverRef}
      className='fixed z-50 w-80 rounded-xl border border-purple-500/30 bg-background shadow-xl overflow-hidden'
      style={{ right: 16, top: 64 }}
    >
      {/* Header — draggable */}
      <div
        onMouseDown={handleMouseDown}
        className='flex items-center justify-between border-b border-border px-3 py-2 cursor-grab active:cursor-grabbing bg-purple-500/5 select-none'
      >
        <span className='text-sm font-medium text-purple-400'>Improvements</span>
        <button
          onClick={onClose}
          className='text-muted-foreground hover:text-foreground transition-colors'
          aria-label='Close improvements panel'
        >
          <X className='h-4 w-4' />
        </button>
      </div>

      {/* Body */}
      <div className='flex flex-col gap-1 p-2 max-h-96 overflow-y-auto'>
        {isEmpty ? (
          <div className='py-4 text-center text-xs text-muted-foreground'>
            No improvements queued
          </div>
        ) : (
          <>
            {currentJob && <SelfImproveInlineStatus job={currentJob} />}

            {queue.map((item, idx) => (
              <ImprovementQueueItem
                key={item.id}
                item={item}
                isFirst={idx === 0}
                isLast={idx === queue.length - 1}
                onRemove={onRemove}
                onMoveUp={onMoveUp}
                onMoveDown={onMoveDown}
              />
            ))}

            {queue.length > 0 && (
              <button
                onClick={onSubmitAll}
                className='w-full mt-1 rounded-lg bg-purple-600 hover:bg-purple-700 px-3 py-1.5 text-xs font-medium text-white transition-colors'
              >
                Submit {queue.length} improvement{queue.length > 1 ? 's' : ''}
              </button>
            )}
          </>
        )}
      </div>
    </div>
  )
}
