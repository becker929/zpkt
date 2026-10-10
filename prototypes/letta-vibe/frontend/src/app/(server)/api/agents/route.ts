import { NextRequest, NextResponse } from 'next/server'
import client from '@/config/letta-client'
import defaultAgent from '@/default-agent'
import { getUserTagId, getUserId } from './helpers'

async function getAgents(req: NextRequest) {
  const userId = getUserId(req)
  if (!userId) {
    return NextResponse.json({ error: 'User ID is required' }, { status: 400 })
  }

  try {
    const agents = await client.agents.list({
      tags: getUserTagId(userId),
      matchAllTags: true,
    })
    const sortedAgents = (agents as any[]).sort(
      (a: any, b: any) => {
        const dateA = a.updatedAt ? new Date(a.updatedAt).getTime() : 0
        const dateB = b.updatedAt ? new Date(b.updatedAt).getTime() : 0
        return dateB - dateA
      }
    )
    return NextResponse.json(sortedAgents)
  } catch (error) {
    console.error('Error fetching agents:', error)
    return NextResponse.json(
      { error: 'Error fetching agents' },
      { status: 500 }
    )
  }
}

async function createAgent(req: NextRequest) {
  // ADD YOUR OWN AGENTS HERE
  const DEFAULT_MEMORY_BLOCKS = defaultAgent.DEFAULT_MEMORY_BLOCKS
  const DEFAULT_LLM = defaultAgent.DEFAULT_LLM
  const FALLBACK_LLM = (defaultAgent as any).FALLBACK_LLM as string | undefined
  const DEFAULT_EMBEDDING = defaultAgent.DEFAULT_EMBEDDING

  const userId = getUserId(req)
  if (!userId) {
    return NextResponse.json({ error: 'User ID is required' }, { status: 400 })
  }

  const agentParams = {
    memoryBlocks: DEFAULT_MEMORY_BLOCKS,
    embedding: DEFAULT_EMBEDDING,
    tags: getUserTagId(userId),
  }

  try {
    const newAgent = await client.agents.create({ ...agentParams, model: DEFAULT_LLM })
    return NextResponse.json(newAgent)
  } catch (primaryError) {
    if (!FALLBACK_LLM) {
      console.error('Error creating agent:', primaryError)
      return NextResponse.json({ error: 'Error creating agent' }, { status: 500 })
    }
    console.warn(`Failed to create agent with ${DEFAULT_LLM}, retrying with fallback ${FALLBACK_LLM}:`, primaryError)
    try {
      const newAgent = await client.agents.create({ ...agentParams, model: FALLBACK_LLM })
      return NextResponse.json(newAgent)
    } catch (fallbackError) {
      console.error('Error creating agent (fallback also failed):', fallbackError)
      return NextResponse.json({ error: 'Error creating agent' }, { status: 500 })
    }
  }
}

export const GET = getAgents
export const POST = createAgent
