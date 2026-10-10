'use client'

import { useRef, useEffect } from 'react'
import { useWavesurfer } from '@wavesurfer/react'
import { Play, Pause, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'

// Module-level singleton: tracks the wavesurfer that is currently playing.
// When a new player starts, we pause this one first — enforcing exclusive playback.
let activeWavesurfer: ReturnType<typeof useWavesurfer>['wavesurfer'] = null

interface WaveformPlayerProps {
  url: string
  filename: string
  className?: string
  onPlayingChange?: (isPlaying: boolean) => void
  onReadyChange?: (isReady: boolean) => void
}

export function WaveformPlayer({ url, filename, className, onPlayingChange, onReadyChange }: WaveformPlayerProps) {
  const containerRef = useRef<HTMLDivElement>(null)

  const { wavesurfer, isReady, isPlaying } = useWavesurfer({
    container: containerRef,
    url,
    waveColor: 'hsl(265, 70%, 50%)',
    progressColor: 'hsl(265, 90%, 75%)',
    cursorColor: 'hsl(265, 90%, 85%)',
    height: 48,
    barWidth: 2,
    barGap: 1,
    barRadius: 2,
    normalize: true,
    interact: true,
  })

  useEffect(() => { onPlayingChange?.(isPlaying) }, [isPlaying])
  useEffect(() => { onReadyChange?.(isReady) }, [isReady])

  // Clear the global reference when this instance unmounts so a stale ref
  // can't pause a player that no longer exists.
  useEffect(() => {
    return () => {
      if (activeWavesurfer === wavesurfer) activeWavesurfer = null
    }
  }, [wavesurfer])

  const togglePlay = () => {
    if (!wavesurfer) return
    if (!isPlaying) {
      // Pause whatever is currently playing before starting this one.
      if (activeWavesurfer && activeWavesurfer !== wavesurfer) {
        activeWavesurfer.pause()
      }
      activeWavesurfer = wavesurfer
    } else {
      activeWavesurfer = null
    }
    wavesurfer.playPause()
  }

  return (
    <div
      className={cn(
        'flex items-center gap-3 rounded-lg border border-border bg-card px-3 py-2 w-full max-w-sm',
        className
      )}
    >
      <Button
        variant='ghost'
        size='icon'
        className='h-8 w-8 shrink-0'
        onClick={togglePlay}
        disabled={!isReady}
        aria-label={isPlaying ? 'Pause' : 'Play'}
      >
        {!isReady ? (
          <Loader2 className='h-4 w-4 animate-spin text-muted-foreground' />
        ) : isPlaying ? (
          <Pause className='h-4 w-4' />
        ) : (
          <Play className='h-4 w-4' />
        )}
      </Button>

      <div className='flex min-w-0 flex-1 flex-col gap-0.5'>
        <div ref={containerRef} className='w-full' />
        <span className='truncate text-[10px] text-muted-foreground'>{filename}</span>
      </div>
    </div>
  )
}
