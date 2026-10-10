'use client'

import { useState, useCallback } from 'react'
import dynamic from 'next/dynamic'
import { Music, Loader2 } from 'lucide-react'
import {
  SidebarContent,
  SidebarGroup,
  SidebarGroupContent,
  SidebarMenu,
  SidebarMenuItem,
} from '@/components/ui/sidebar'
import { useRenderHistory } from '@/components/hooks/use-render-history'

const WaveformPlayer = dynamic(
  () => import('@/components/waveform-player').then((m) => m.WaveformPlayer),
  { ssr: false }
)

export function RenderHistory() {
  const { data } = useRenderHistory()
  const [activeFilename, setActiveFilename] = useState<string | null>(null)
  const [playingFilename, setPlayingFilename] = useState<string | null>(null)
  const [loadingFilename, setLoadingFilename] = useState<string | null>(null)
  const renders = data?.renders ?? []

  const handlePlayingChange = useCallback(
    (filename: string) => (isPlaying: boolean) => {
      setPlayingFilename(isPlaying ? filename : null)
    },
    []
  )

  const handleReadyChange = useCallback(
    (filename: string) => (isReady: boolean) => {
      if (isReady) setLoadingFilename((prev) => (prev === filename ? null : prev))
    },
    []
  )

  const handleClick = (filename: string) => {
    if (activeFilename === filename) {
      setActiveFilename(null)
      setPlayingFilename(null)
      setLoadingFilename(null)
    } else {
      setActiveFilename(filename)
      setLoadingFilename(filename)
    }
  }

  if (renders.length === 0) {
    return (
      <SidebarContent>
        <div className='p-4 text-xs text-muted-foreground'>No renders yet.</div>
      </SidebarContent>
    )
  }

  return (
    <SidebarContent id='renders-list'>
      <SidebarGroup>
        <SidebarGroupContent>
          <SidebarMenu>
            {renders.map((render) => {
              const isActive = activeFilename === render.filename
              const isPlaying = playingFilename === render.filename
              const isLoading = loadingFilename === render.filename && isActive

              return (
                <SidebarMenuItem key={render.filename}>
                  <div
                    className={`flex flex-col gap-1 p-2 cursor-pointer border-l-2 rounded-sm hover:bg-sidebar-accent transition-colors ${
                      isActive ? 'border-primary' : 'border-transparent'
                    }`}
                    onClick={() => handleClick(render.filename)}
                  >
                    <div className='flex items-center gap-1.5 min-w-0'>
                      {isLoading ? (
                        <Loader2 size={11} className='shrink-0 text-muted-foreground animate-spin' />
                      ) : isPlaying ? (
                        <span className='shrink-0 inline-block h-2 w-2 rounded-full bg-primary animate-pulse' />
                      ) : (
                        <Music size={11} className='shrink-0 text-muted-foreground' />
                      )}
                      <span className='text-xs font-mono truncate'>{render.filename}</span>
                    </div>
                    <div className='flex gap-2 text-[10px] text-muted-foreground pl-4'>
                      <span>
                        {new Date(render.timestamp).toLocaleTimeString([], {
                          hour: '2-digit',
                          minute: '2-digit',
                        })}
                      </span>
                      {render.beats != null && <span>{render.beats}b</span>}
                    </div>
                  </div>
                  {isActive && (
                    <div className='px-2 pb-2'>
                      <WaveformPlayer
                        url={`/api/audio/${render.filename}`}
                        filename={render.filename}
                        onPlayingChange={handlePlayingChange(render.filename)}
                        onReadyChange={handleReadyChange(render.filename)}
                      />
                    </div>
                  )}
                </SidebarMenuItem>
              )
            })}
          </SidebarMenu>
        </SidebarGroupContent>
      </SidebarGroup>
    </SidebarContent>
  )
}
