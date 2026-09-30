'use client'

import { type FC } from 'react'
import { Loader2, CheckCircle, XCircle } from 'lucide-react'
import { type ImprovementJobStatus } from '@/types'

export const SelfImproveInlineStatus: FC<{ job: ImprovementJobStatus }> = ({ job }) => {
  const icon =
    job.status === 'completed' ? (
      <CheckCircle className='h-3.5 w-3.5 text-green-500 shrink-0' />
    ) : job.status === 'failed' ? (
      <XCircle className='h-3.5 w-3.5 text-destructive shrink-0' />
    ) : (
      <Loader2 className='h-3.5 w-3.5 animate-spin text-purple-400 shrink-0' />
    )

  const label =
    job.status === 'running'
      ? `Running (${job.jobId})`
      : job.status === 'completed'
        ? `Completed (${job.jobId})`
        : `Failed (${job.jobId})`

  return (
    <div className='flex items-center gap-2 rounded-lg border border-purple-500/20 bg-purple-500/5 px-3 py-2 text-xs'>
      {icon}
      <div className='min-w-0 flex-1'>
        <div className='font-medium text-foreground truncate'>{label}</div>
        <div className='text-muted-foreground break-words'>{job.description}</div>
        {job.status === 'failed' && job.error && (
          <div className='text-destructive mt-0.5 line-clamp-2'>{job.error}</div>
        )}
      </div>
    </div>
  )
}
