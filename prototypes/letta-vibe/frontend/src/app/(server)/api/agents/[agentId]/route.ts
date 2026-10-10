import { NextRequest, NextResponse } from 'next/server'
import client from '@/config/letta-client'
import { validateAgentOwner } from '../helpers'
import { Context } from '@/types'

async function getAgentById(
  req: NextRequest,
  context: Context<{ agentId: string }>
) {
  const result = await validateAgentOwner(req, context)
  if (result instanceof NextResponse) {
    return result
  }
  const { agent } = result

  try {
    return NextResponse.json(agent)
  } catch (error) {
    console.error('Error fetching agent:', error)
    return NextResponse.json({ error: 'Error fetching agent' }, { status: 500 })
  }
}

async function modifyAgentById(
  req: NextRequest,
  context: Context<{ agentId: string }>
) {
  // Only fields the UI edits. Passing the raw body let a caller rewrite the
  // agent's tools, system prompt or model endpoint.
  const raw = await req.json()
  const body: { name?: string } = {}
  if (typeof raw?.name === 'string') body.name = raw.name.slice(0, 200)
  if (Object.keys(body).length === 0) {
    return NextResponse.json({ error: 'only "name" can be modified' }, { status: 400 })
  }

  const result = await validateAgentOwner(req, context)
  if (result instanceof NextResponse) {
    return result
  }
  const { agentId } = result

  try {
    const updatedAgent = await client.agents.modify(agentId, body)
    if (!updatedAgent) {
      return NextResponse.json({ error: 'Agent not found' }, { status: 404 })
    }
    return NextResponse.json(updatedAgent)
  } catch (error) {
    console.error('Error updating agent:', error)
    return NextResponse.json({ error: 'Error updating agent' }, { status: 500 })
  }
}

async function deleteAgentById(
  req: NextRequest,
  context: Context<{ agentId: string }>
) {
  const result = await validateAgentOwner(req, context)
  if (result instanceof NextResponse) {
    console.error('Error:', result)
    return result
  }
  const { agentId } = result

  try {
    await client.agents.delete(agentId)
    return NextResponse.json({ message: 'Agent deleted successfully' })
  } catch (error) {
    console.error('Error deleting agent:', error)
    return NextResponse.json({ error: 'Error deleting agent' }, { status: 500 })
  }
}

export const GET = getAgentById
export const PATCH = modifyAgentById
export const DELETE = deleteAgentById
