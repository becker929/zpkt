'use client'

import { type FC } from 'react'
import { ChevronUp, ChevronDown, Trash2 } from 'lucide-react'
import { type QueuedImprovement } from '@/types'

interface ImprovementQueueItemProps {
  item: QueuedImprovement
  isFirst: boolean
  isLast: boolean
  onRemove: (id: string) => void
  onMoveUp: (id: string) => void
  onMoveDown: (id: string) => void
}

export const ImprovementQueueItem: FC<ImprovementQueueItemProps> = ({
  item,
  isFirst,
  isLast,
  onRemove,
  onMoveUp,
  onMoveDown,
}) => {
  return (
    <div className='group flex items-start gap-2 rounded-lg border border-purple-500/20 bg-card px-3 py-2 text-sm'>
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
        <div className='flex flex-col gap-0.5'>
          <span className='font-medium text-sm break-words'>{item.description}</span>
          {item.prompt && (
            <span className='text-xs text-muted-foreground line-clamp-2 whitespace-pre-wrap'>
              {item.prompt}
            </span>
          )}
        </div>
      </div>

      <button
        onClick={() => onRemove(item.id)}
        className='shrink-0 mt-0.5 text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100'
        aria-label='Remove improvement'
      >
        <Trash2 className='h-3.5 w-3.5' />
      </button>
    </div>
  )
}
