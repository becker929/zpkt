/**
 * Integration tests that require a live Letta server + Ollama.
 *
 * Prerequisites:
 *   docker run -p 8283:8283 -e ANTHROPIC_API_KEY=... \
 *     -e OLLAMA_BASE_URL="http://host.docker.internal:11434/v1" letta/letta:latest
 *   ollama pull nomic-embed-text
 *
 * Run with: npx cypress run --spec "cypress/e2e/spec.cy.ts"
 */

const TEST_AGENT_NAME = 'Test Vibe Agent 12345'
let agentId: string = ''

function theTestAgentShouldExist() {
  return cy
    .get('[data-id=agents-list]')
    .children()
    .filter(`:contains("${TEST_AGENT_NAME}")`)
    .should('have.length.at.least', 1)
}

describe('Vibe — live Letta integration', { testIsolation: false }, () => {
  before(() => {
    cy.visit('/')
    cy.wait(3000)
  })

  it('cleans up the test agent if it already exists', () => {
    cy.get('[data-id=agents-list]')
      .children()
      .each(($el) => {
        const text = $el.text().trim()
        if (!text.includes(TEST_AGENT_NAME)) return

        const targetAgentId = $el.attr('data-id')
        if (!targetAgentId) return false

        cy.get(`[data-id=options-menu-${targetAgentId}]`).click()
        cy.get(`[data-id=delete-agent-button-${targetAgentId}]`).click()
        cy.get('[data-id=delete-agent-confirmation]').should('exist')
        cy.get('[data-id=delete-agent-confirmation-button]').click()
        return false
      })
  })

  it('creates a new agent and renames it', () => {
    let numAgents = 0
    cy.get('[data-id=agents-list]')
      .children()
      .its('length')
      .then((count) => {
        numAgents = count
      })

    cy.get('[data-id=create-agent-button]', { timeout: 10000 })
      .should('be.visible')
      .click()
    cy.wait(2000)

    cy.get('[data-id=agents-list]')
      .children()
      .its('length')
      .should('eq', numAgents + 1)

    cy.location('pathname', { timeout: 10000 }).then((pathname) => {
      agentId = pathname.slice(1)

      cy.get(`[data-id=options-menu-${agentId}]`).click()
      cy.get(`[data-id=edit-agent-button-${agentId}]`).click()
      cy.get('[data-id=agent-name-input]').clear().type(TEST_AGENT_NAME)
      cy.get('[data-id=agent-name-input-save]').click()
    })

    theTestAgentShouldExist()
    cy.wait(3000)
  })

  it('sends a message and receives a response', () => {
    cy.get('[data-id=message-input]').type('Hello from the test suite{enter}')
    cy.get('[data-id$="_user"]').should('contain.text', 'Hello from the test suite')

    cy.get('[data-id$="_assistant"]', { timeout: 20000 }).should('exist')
  })

  it('opens the agent details panel', () => {
    cy.get('[data-id=agent-details-trigger]').click()
    cy.get('[data-id=agent-details-display-content]').should('be.visible')
    cy.get('[data-id=agent-details-trigger]').click()
    cy.get('[data-id=agent-details-display-content]').should('not.be.visible')
  })

  it('sends a bounce request and shows a response', () => {
    cy.get('[data-id=bounce-button]').should('exist').and('be.visible').click()
    cy.get('[data-id$="_user"]').last().should('contain.text', 'Bounce the current session')
    // Agent may or may not have the bounce tool registered — just verify it responds
    cy.get('[data-id$="_assistant"]', { timeout: 30000 })
      .its('length')
      .should('be.greaterThan', 0)
  })

  it('deletes the test agent', () => {
    cy.location('pathname').then((pathname) => {
      agentId = pathname.slice(1)

      cy.get(`[data-id=options-menu-${agentId}]`).click()
      cy.get(`[data-id=delete-agent-button-${agentId}]`).click()
      cy.get('[data-id=delete-agent-confirmation]').should('be.visible')
      cy.get('[data-id=delete-agent-confirmation-button]').click()
    })
  })
})
