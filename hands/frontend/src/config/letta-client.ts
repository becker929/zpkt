import { LettaClient } from '@letta-ai/letta-client'
import { config } from 'dotenv'

config()

const client = new LettaClient({
  token: process.env.LETTA_API_KEY || undefined,
  baseUrl: process.env.LETTA_BASE_URL ?? 'http://localhost:8283',
})

export default client
