'use client'

import { useState, type FC } from 'react'
import { ChevronUp, ChevronDown, Trash2, Pencil, Check, X } from 'lucide-react'
import { type QueuedMessage } from '@/types'

interface QueueItemProps {
  item: QueuedMessage
  isFirst: boolean
  isLast: boolean
  onEdit: (id: string, text: string) => void
  onRemove: (id: string) => void
  onMoveUp: (id: string) => void
  onMoveDown: (id: string) => void
}

export const QueueItem: FC<QueueItemProps> = ({
  item,
  isFirst,
  isLast,
  onEdit,
  onRemove,
  onMoveUp,
  onMoveDown,
}) => {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(item.text)

  const save = () => {
    const trimmed = draft.trim()
    if (trimmed) onEdit(item.id, trimmed)
    setEditing(false)
  }

  const cancel = () => {
    setDraft(item.text)
    setEditing(false)
  }

  return (
    <div className='group flex items-start gap-2 rounded-lg border border-border/60 bg-card px-3 py-2 text-sm'>
      <div className='flex shrink-0 flex-col gap-0.5 mt-0.5'>
        <button
          onClick={() => onMoveUp(item.id)}
          disabled={isFirst}
          className='text-muted-foreground hover:text-foreground disabled:cursor-default disabled:opacity-20'
          aria-label='Move up'
        >
          <ChevronUp className='h-3.5 w-3.5' />
        </button>
        <button
          onClick={() => onMoveDown(item.id)}
          disabled={isLast}
          className='text-muted-foreground hover:text-foreground disabled:cursor-default disabled:opacity-20'
          aria-label='Move down'
        >
          <ChevronDown className='h-3.5 w-3.5' />
        </button>
      </div>

      <div className='min-w-0 flex-1'>
        {editing ? (
          <textarea
            autoFocus
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                save()
              }
              if (e.key === 'Escape') cancel()
            }}
            rows={Math.max(1, draft.split('\n').length)}
            className='w-full resize-none bg-transparent text-sm focus:outline-none'
          />
        ) : (
          <span className='whitespace-pre-wrap break-words'>{item.text}</span>
        )}
      </div>

      <div className='flex shrink-0 items-center gap-1'>
        {editing ? (
          <>
            <button
              onClick={save}
              className='text-muted-foreground hover:text-foreground'
              aria-label='Save edit'
            >
              <Check className='h-3.5 w-3.5' />
            </button>
            <button
              onClick={cancel}
              className='text-muted-foreground hover:text-foreground'
              aria-label='Cancel edit'
            >
              <X className='h-3.5 w-3.5' />
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => { setDraft(item.text); setEditing(true) }}
              className='text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100'
              aria-label='Edit message'
            >
              <Pencil className='h-3.5 w-3.5' />
            </button>
            <button
              onClick={() => onRemove(item.id)}
              className='text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100'
              aria-label='Delete message'
            >
              <Trash2 className='h-3.5 w-3.5' />
            </button>
          </>
        )}
      </div>
    </div>
  )
}
