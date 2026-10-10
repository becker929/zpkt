'use client'

import { type FC } from 'react'
import { Send } from 'lucide-react'
import { type QueuedMessage } from '@/types'
import { QueueItem } from './queue-item'

interface MessageQueueProps {
  items: QueuedMessage[]
  onEdit: (id: string, text: string) => void
  onRemove: (id: string) => void
  onMoveUp: (id: string) => void
  onMoveDown: (id: string) => void
  onFlushAll: () => void
}

export const MessageQueue: FC<MessageQueueProps> = ({
  items,
  onEdit,
  onRemove,
  onMoveUp,
  onMoveDown,
  onFlushAll,
}) => {
  if (items.length === 0) return null

  return (
    <div className='mx-auto w-full max-w-3xl px-4 pb-2'>
      <div className='rounded-xl border border-border bg-muted/30 p-2'>
        <div className='mb-1.5 flex items-center justify-between px-1'>
          <span className='text-xs text-muted-foreground'>
            {items.length} queued {items.length === 1 ? 'message' : 'messages'}
          </span>
          <button
            onClick={onFlushAll}
            className='flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground'
            aria-label='Send all queued messages now'
          >
            <Send className='h-3 w-3' />
            Send all
          </button>
        </div>
        <div className='flex flex-col gap-1'>
          {items.map((item, idx) => (
            <QueueItem
              key={item.id}
              item={item}
              isFirst={idx === 0}
              isLast={idx === items.length - 1}
              onEdit={onEdit}
              onRemove={onRemove}
              onMoveUp={onMoveUp}
              onMoveDown={onMoveDown}
            />
          ))}
        </div>
      </div>
    </div>
  )
}
