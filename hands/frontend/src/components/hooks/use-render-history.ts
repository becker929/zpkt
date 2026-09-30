'use client'

import { useQuery } from '@tanstack/react-query'

export interface RenderEntry {
  filename: string
  timestamp: string
  beats?: number
  size?: number
}

export function useRenderHistory() {
  return useQuery<{ renders: RenderEntry[] }>({
    queryKey: ['render-history'],
    queryFn: () => fetch('/api/history').then((r) => r.json()),
    refetchInterval: 3000,
    initialData: { renders: [] },
  })
}
