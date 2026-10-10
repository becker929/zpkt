'use client'

import { useState, useCallback, useEffect } from 'react'
import { QueuedMessage } from '@/types'

const STORAGE_KEY_PREFIX = 'vibe-queue-'

export function useMessageQueue(agentId: string) {
  const storageKey = `${STORAGE_KEY_PREFIX}${agentId}`

  const [queue, setQueue] = useState<QueuedMessage[]>([])

  // Hydrate from localStorage after mount (avoids SSR mismatch)
  useEffect(() => {
    try {
      const stored = localStorage.getItem(storageKey)
      if (stored) {
        const parsed = JSON.parse(stored) as QueuedMessage[]
        if (parsed.length > 0) setQueue(parsed)
      }
    } catch { /* ignore */ }
  }, [storageKey])

  useEffect(() => {
    try {
      localStorage.setItem(storageKey, JSON.stringify(queue))
    } catch { /* ignore */ }
  }, [queue, storageKey])

  const enqueue = useCallback((text: string) => {
    setQueue((prev) => [
      ...prev,
      { id: crypto.randomUUID(), text, addedAt: new Date().toISOString() },
    ])
  }, [])

  const editItem = useCallback((id: string, text: string) => {
    setQueue((prev) => prev.map((item) => (item.id === id ? { ...item, text } : item)))
  }, [])

  const removeItem = useCallback((id: string) => {
    setQueue((prev) => prev.filter((item) => item.id !== id))
  }, [])

  const moveUp = useCallback((id: string) => {
    setQueue((prev) => {
      const idx = prev.findIndex((item) => item.id === id)
      if (idx <= 0) return prev
      const next = [...prev]
      ;[next[idx - 1], next[idx]] = [next[idx], next[idx - 1]]
      return next
    })
  }, [])

  const moveDown = useCallback((id: string) => {
    setQueue((prev) => {
      const idx = prev.findIndex((item) => item.id === id)
      if (idx === -1 || idx >= prev.length - 1) return prev
      const next = [...prev]
      ;[next[idx], next[idx + 1]] = [next[idx + 1], next[idx]]
      return next
    })
  }, [])

  const flushQueue = useCallback((): string[] => {
    const texts = queue.map((item) => item.text)
    setQueue([])
    return texts
  }, [queue])

  return { queue, enqueue, editItem, removeItem, moveUp, moveDown, flushQueue }
}
