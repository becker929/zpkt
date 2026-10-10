import { clsx, type ClassValue } from 'clsx'
import { twMerge } from 'tailwind-merge'
import { VibeMessage } from '@/types'

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs))
}

/** Extract the last user-facing text from a list of VibeMessages (used for labels). */
export const extractMessageText = (messages: VibeMessage[]): string | null => {
  for (let i = messages.length - 1; i >= 0; i--) {
    const parts = messages[i]?.parts ?? []
    const textParts = parts.filter((p) => p.type === 'text')
    if (textParts.length > 0) {
      return textParts
        .map((p) => (p.type === 'text' ? p.text : ''))
        .join(' ')
    }
  }
  return null
}
