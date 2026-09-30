import { LettaMessageUnion } from '@letta-ai/letta-client/api'

export enum MESSAGE_TYPE {
  USER_MESSAGE = 'user_message',
  SYSTEM_MESSAGE = 'system_message',
}

export enum ROLE_TYPE {
  USER = 'user',
}

export const LETTA_UID = 'letta-uid'

export type Context<T> = { params: Promise<T> }

// ── Vibe message part types ──────────────────────────────────────────────────

export type VibeTextPart = { type: 'text'; text: string }
export type VibeAudioPart = { type: 'audio'; filename: string; url: string }
export type VibeBounceLoadingPart = { type: 'bounce-loading' }
export type VibeToolCallPart = {
  type: 'tool-call'
  name: string
  args: string
  result?: string
  completed?: boolean
}
export type VibeReasoningPart = { type: 'reasoning'; text: string }
export type VibeThinkingPart = { type: 'thinking' }
export type VibeSelfImproveProgressPart = {
  type: 'self-improve-progress'
  jobId: string
  description: string
  vibeUrl: string
}

export type VibeHiddenReasoningPart = {
  type: 'hidden_reasoning'
  state: 'redacted' | 'omitted'
  hiddenReasoning?: string
}

export type VibeApprovalRequestPart = {
  type: 'approval_request'
  toolCall: { name: string; arguments: string; id: string }
}

export type VibeApprovalResponsePart = {
  type: 'approval_response'
  approve: boolean
  approvalRequestId: string
  reason?: string
}

export type VibeMetadataPart = {
  type: 'metadata'
  otid?: string
  senderId?: string
  stepId?: string
  isErr?: boolean
  seqId?: number
  runId?: string
}

export type VibeMessagePart =
  | VibeTextPart
  | VibeAudioPart
  | VibeBounceLoadingPart
  | VibeToolCallPart
  | VibeReasoningPart
  | VibeThinkingPart
  | VibeSelfImproveProgressPart
  | VibeHiddenReasoningPart
  | VibeApprovalRequestPart
  | VibeApprovalResponsePart
  | VibeMetadataPart

export type VibeMessage = {
  id: string
  role: 'user' | 'assistant'
  parts: VibeMessagePart[]
  timestamp: string
}

// ── SSE chunk types streamed from the API route to the client ────────────────

export type VibeSseTextChunk = { type: 'text'; text: string }
export type VibeSseReasoningChunk = { type: 'reasoning'; text: string }
export type VibeSseToolCallChunk = { type: 'tool_call'; name: string; args: string }
export type VibeSseToolReturnChunk = { type: 'tool_return'; filename?: string; returnValue?: string }
export type VibeSseDoneChunk = { type: 'done' }
export type VibeSseErrorChunk = { type: 'error'; message: string }

export type VibeSseChunk =
  | VibeSseTextChunk
  | VibeSseReasoningChunk
  | VibeSseToolCallChunk
  | VibeSseToolReturnChunk
  | VibeSseDoneChunk
  | VibeSseErrorChunk

// ── Message queue ─────────────────────────────────────────────────────────────

export type QueuedMessage = {
  id: string
  text: string
  addedAt: string
}

// ── Improvement queue ─────────────────────────────────────────────────────────

export type QueuedImprovement = {
  id: string
  description: string
  prompt: string
  addedAt: string
}

export type ImprovementJobStatus = {
  jobId: string
  description: string
  status: 'running' | 'completed' | 'failed'
  startedAt: string
  error?: string
}

// Re-export for helpers
export type { LettaMessageUnion }
