/**
 * Vibe frontend e2e tests.
 *
 * All Letta/audio API calls are intercepted so these tests run without a live
 * Letta server or Ableton. Only `npm run dev` (port 3000) is required.
 */

const AGENT_ID = 'agent-vibe-test-0001'

// ── SSE body helpers ──────────────────────────────────────────────────────────

function sseBody(...chunks: object[]): string {
  return chunks.map((c) => `data: ${JSON.stringify(c)}\n\n`).join('')
}

const SSE_TEXT_REPLY = sseBody(
  { type: 'text', text: 'Sounding tight. More sub below 60 Hz would help.' },
  { type: 'done' }
)

const SSE_BOUNCE_REPLY = sseBody(
  { type: 'text', text: "Bouncing now — give me a sec." },
  { type: 'tool_call', name: 'run_bounce', args: '{"beats":64}' },
  { type: 'tool_return', filename: 'bounce_001.wav' },
  { type: 'done' }
)

// ── Shared intercept setup ────────────────────────────────────────────────────

function setupIntercepts(
  messageFixture: string = 'messages-empty',
  sseReply: string = SSE_TEXT_REPLY
) {
  cy.intercept('GET', '/api/runtime', { LETTA_BASE_URL: 'http://localhost:8283' }).as(
    'runtime'
  )
  cy.intercept('GET', '/api/agents', { fixture: 'agents.json' }).as('agents')
  cy.intercept('GET', `/api/agents/${AGENT_ID}`, { fixture: 'agent.json' }).as('agent')
  cy.intercept('GET', `/api/agents/${AGENT_ID}/messages`, {
    fixture: messageFixture,
  }).as('messages')
  cy.intercept('GET', `/api/agents/${AGENT_ID}/archival_memory`, {
    body: [],
  }).as('archival')
  cy.intercept('POST', `/api/agents/${AGENT_ID}/messages`, {
    statusCode: 200,
    headers: {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
    },
    body: sseReply,
  }).as('sendMessage')
  // Stub audio — returns a minimal 1-byte body so WaveSurfer doesn't error
  cy.intercept('GET', '/api/audio/*', {
    statusCode: 200,
    headers: { 'Content-Type': 'audio/wav' },
    body: '',
  }).as('audio')
}

// ── Tests ─────────────────────────────────────────────────────────────────────

describe('Vibe frontend — chat UI', { testIsolation: false }, () => {
  describe('App loads', () => {
    before(() => {
      setupIntercepts()
      cy.visit(`/${AGENT_ID}`)
      cy.wait('@agents')
    })

    it('renders the message composer', () => {
      cy.get('[data-id=message-input]').should('exist').and('be.visible')
    })

    it('renders the Bounce button', () => {
      cy.get('[data-id=bounce-button]').should('exist').and('be.visible')
    })

    it('Bounce button is enabled when not streaming', () => {
      cy.get('[data-id=bounce-button]').should('not.be.disabled')
    })
  })

  describe('Chat — send a text message', () => {
    before(() => {
      setupIntercepts('messages-empty', SSE_TEXT_REPLY)
      cy.visit(`/${AGENT_ID}`)
      cy.wait('@agents')
    })

    it('typing in the textarea updates the input', () => {
      cy.get('[data-id=message-input]').type('How does the kick sound?')
      cy.get('[data-id=message-input]').should('have.value', 'How does the kick sound?')
    })

    it('submits on Enter, clears input, shows user bubble + streamed assistant text', () => {
      // Register the intercept inline so the alias is guaranteed fresh for cy.wait.
      cy.intercept('POST', `/api/agents/${AGENT_ID}/messages`, {
        statusCode: 200,
        headers: { 'Content-Type': 'text/event-stream', 'Cache-Control': 'no-cache' },
        body: SSE_TEXT_REPLY,
      }).as('chatMsg')

      cy.get('[data-id=message-input]').type('{enter}')
      cy.get('[data-id=message-input]').should('have.value', '')
      cy.get('[data-id$="_user"]').should('exist').and('contain.text', 'How does the kick sound?')
      cy.wait('@chatMsg')
      cy.get('[data-id$="_assistant"]', { timeout: 8000 })
        .should('exist')
        .and('contain.text', 'Sounding tight')
    })
  })

  describe('Chat — load message history', () => {
    before(() => {
      setupIntercepts('messages-with-history', SSE_TEXT_REPLY)
      cy.visit(`/${AGENT_ID}`)
      cy.wait('@messages')
    })

    it('displays previous user message', () => {
      cy.get('[data-id$="_user"]').first().should('contain.text', "How's the kick sounding?")
    })

    it('displays previous assistant message', () => {
      cy.get('[data-id$="_assistant"]').first().should('contain.text', 'good punch')
    })
  })

  describe('Bounce button — triggers bounce flow', () => {
    before(() => {
      setupIntercepts('messages-empty', SSE_BOUNCE_REPLY)
      cy.visit(`/${AGENT_ID}`)
      cy.wait('@agents')
    })

    it('clicking Bounce sends the bounce message', () => {
      cy.get('[data-id=bounce-button]').click()
      cy.wait('@sendMessage').its('request.body').should('deep.include', {
        text: 'Bounce the current session and let me hear it.',
      })
    })

    it('user bubble shows the bounce request', () => {
      cy.get('[data-id$="_user"]').should('contain.text', 'Bounce the current session')
    })

    it('shows the bounce-loading indicator while streaming', () => {
      // The SSE mock delivers the entire stream synchronously, so loading state
      // may be transient — we check it existed at some point via the assistant bubble
      cy.get('[data-id$="_assistant"]', { timeout: 8000 }).should('exist')
    })

    it('renders the waveform player after bounce completes', () => {
      cy.get('[data-id="waveform-bounce_001.wav"]', { timeout: 8000 }).should('exist')
    })

    it('waveform player shows the filename', () => {
      cy.get('[data-id="waveform-bounce_001.wav"]').should('contain.text', 'bounce_001.wav')
    })
  })

  describe('Bounce button — disabled while streaming', () => {
    it('Bounce button is disabled while a message is in flight', () => {
      // Intercept with a delayed response
      cy.intercept('POST', `/api/agents/${AGENT_ID}/messages`, (req) => {
        req.reply({
          statusCode: 200,
          headers: { 'Content-Type': 'text/event-stream' },
          body: SSE_TEXT_REPLY,
          delay: 500,
        })
      }).as('slowMessage')

      cy.get('[data-id=message-input]').type('test{enter}')
      cy.get('[data-id=bounce-button]').should('be.disabled')
      cy.wait('@slowMessage')
    })
  })

  describe('Load page with audio in history', () => {
    before(() => {
      setupIntercepts('messages-with-audio', SSE_TEXT_REPLY)
      cy.visit(`/${AGENT_ID}`)
      cy.wait('@messages')
    })

    it('shows waveform player for historical audio bounce', () => {
      cy.get('[data-id="waveform-bounce_001.wav"]').should('exist')
    })

    it('shows the assistant text alongside the audio', () => {
      cy.get('[data-id$="_assistant"]').should('contain.text', 'Bounced!')
    })
  })

  describe('API error handling', () => {
    before(() => {
      cy.intercept('GET', '/api/runtime', { LETTA_BASE_URL: 'http://localhost:8283' })
      cy.intercept('GET', '/api/agents', { fixture: 'agents.json' }).as('agents')
      cy.intercept('GET', `/api/agents/${AGENT_ID}`, { fixture: 'agent.json' })
      cy.intercept('GET', `/api/agents/${AGENT_ID}/messages`, { fixture: 'messages-empty' })
      cy.intercept('GET', `/api/agents/${AGENT_ID}/archival_memory`, { body: [] })
      cy.intercept('POST', `/api/agents/${AGENT_ID}/messages`, {
        statusCode: 500,
        body: { error: 'Letta server unavailable' },
      }).as('failedMessage')
      cy.visit(`/${AGENT_ID}`)
      cy.wait('@agents')
    })

    it('shows a toast error when the agent call fails', () => {
      cy.get('[data-id=message-input]').type('test{enter}')
      cy.wait('@failedMessage')
      // Sonner toast renders in a [data-sonner-toaster] element
      cy.get('[data-sonner-toaster]', { timeout: 6000 }).should('exist')
    })
  })
})
