# ═══════════════════════════════════════════════════════════════════════════════
#  hands/Makefile  —  Vibe stack management
# ═══════════════════════════════════════════════════════════════════════════════
#
#  make setup        Install all deps (npm, uv, docker pull, ollama pull)
#  make build        Production build (Next.js) + Python type check
#  make test         pytest + Cypress e2e  (intercepted, no live server needed)
#  make test-unit    Python pytest only
#  make test-e2e     Cypress only (auto-starts / stops the dev server)
#  make start        Start the full vibe stack
#  make stop         Stop all vibe services
#  make logs         Tail the last 20 lines from each service
#  make status       Show whether each service is running
#
# ═══════════════════════════════════════════════════════════════════════════════

SHELL        := /bin/bash
.DEFAULT_GOAL := help

# ── Paths ──────────────────────────────────────────────────────────────────────
FRONTEND_DIR := frontend
PID_DIR      := .pids

# ── Ports & container ──────────────────────────────────────────────────────────
LETTA_CONTAINER  := letta-vibe
LETTA_IMAGE      := letta/letta:latest
LETTA_PORT       := 8283
VIBE_PORT        := 8080
ABLETON_MCP_BRIDGE_PORT := 9010
FRONTEND_PORT    := 3000
VIBE_OUTPUT_DIR  ?= /tmp/vibe

# ── OS detection (macOS vs Linux for Docker→Ollama networking) ─────────────────
UNAME := $(shell uname -s)
ifeq ($(UNAME),Darwin)
  OLLAMA_DOCKER_HOST := host.docker.internal
  DOCKER_NETWORK_FLAGS :=
else
  OLLAMA_DOCKER_HOST := localhost
  DOCKER_NETWORK_FLAGS := --network host
endif

# ── Load .env for API keys ─────────────────────────────────────────────────────
-include $(FRONTEND_DIR)/.env
export ANTHROPIC_API_KEY
export LETTA_API_KEY
export GEMINI_API_KEY
export MCP_BRIDGE_TOKEN

# ── Colours (graceful fallback in CI) ─────────────────────────────────────────
BOLD  := $(shell tput bold   2>/dev/null || printf '')
GREEN := $(shell tput setaf 2 2>/dev/null || printf '')
CYAN  := $(shell tput setaf 6 2>/dev/null || printf '')
RESET := $(shell tput sgr0   2>/dev/null || printf '')

define ok
	@printf "$(GREEN)$(BOLD)  ✓  %s$(RESET)\n" "$(1)"
endef

define section
	@printf "\n$(CYAN)$(BOLD)── %s ──$(RESET)\n" "$(1)"
endef

# ═══════════════════════════════════════════════════════════════════════════════
.PHONY: help check-deps \
        setup setup-python setup-frontend setup-docker setup-ollama setup-tools \
        build build-frontend build-python \
        test test-unit test-e2e \
        start start-letta start-vibe start-frontend start-ableton-mcp \
        stop  stop-letta  stop-vibe  stop-frontend  stop-ableton-mcp \
        logs stream stream-letta stream-vibe stream-ableton-mcp stream-frontend \
        stream-agent stream-all \
        status self-improve \
        watchdog stop-watchdog watchdog-status

# ─── Dependency checks ────────────────────────────────────────────────────────
# Each check prints a clear error and exits 1 if the tool is missing.
# Targets that need a tool call the matching check- prerequisite explicitly.

check-uv:
	@command -v uv > /dev/null 2>&1 || { \
	  printf "$(BOLD)ERROR:$(RESET) 'uv' not found.\n"; \
	  printf "  Install: curl -LsSf https://astral.sh/uv/install.sh | sh\n"; \
	  exit 1; }

check-node:
	@command -v node > /dev/null 2>&1 || { \
	  printf "$(BOLD)ERROR:$(RESET) 'node' not found.\n"; \
	  printf "  Install: https://nodejs.org or 'brew install node'\n"; \
	  exit 1; }

check-docker:
	@command -v docker > /dev/null 2>&1 || { \
	  printf "$(BOLD)ERROR:$(RESET) 'docker' not found.\n"; \
	  printf "  Install Docker Desktop: https://www.docker.com/products/docker-desktop\n"; \
	  printf "  Alternative (macOS): brew install --cask docker\n"; \
	  printf "\n"; \
	  printf "  If you prefer not to use Docker, run Letta via pip instead:\n"; \
	  printf "    pip install letta && letta server\n"; \
	  exit 1; }
	@docker info > /dev/null 2>&1 || { \
	  printf "$(BOLD)ERROR:$(RESET) Docker daemon is not running.\n"; \
	  printf "  Start Docker Desktop, then retry.\n"; \
	  exit 1; }

check-ollama:
	@command -v ollama > /dev/null 2>&1 || { \
	  printf "$(BOLD)ERROR:$(RESET) 'ollama' not found.\n"; \
	  printf "  Install: https://ollama.com or 'brew install ollama'\n"; \
	  exit 1; }

check-deps: check-uv check-node check-docker check-ollama
	$(call ok,All required tools found)

# ─── Help ─────────────────────────────────────────────────────────────────────
help:
	@printf "\n$(BOLD)Vibe — hands package$(RESET)\n\n"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make setup"           "Install all dependencies (npm, uv, Docker, Ollama)"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make setup-tools"     "Register Letta custom tools + MCP server"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make build"      "Production build: Next.js + Python type check"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make test"       "Run all tests: pytest + Cypress e2e"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make test-unit"  "Python pytest only"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make test-e2e"   "Cypress only (auto-starts/stops dev server)"
	@printf "\n"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make start"      "Start the full vibe stack"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make stop"       "Stop all vibe services"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make stream-all"    "★ Live: agent + infra combined"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make stream-agent"  "Live: TMS messages, tool calls, returns"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make stream"       "Live: follow all infrastructure services"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make stream-letta" "Live: Letta container (filtered, agent-only)"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make logs"         "Snapshot: last 20 lines from each service"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make status"       "Show running/stopped status"
	@printf "\n"
	@printf "  Individual targets: start-letta, start-vibe, start-frontend\n"
	@printf "                      stop-letta,  stop-vibe,  stop-frontend\n\n"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make watchdog"      "Start self-healing watchdog (independent of stack)"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make stop-watchdog"  "Stop watchdog (also: touch .watchdog-stop)"
	@printf "  $(BOLD)%-20s$(RESET) %s\n" "make watchdog-status" "Show watchdog state + recent log"
	@printf "\n"

# ═══════════════════════════════════════════════════════════════════════════════
#  SETUP
# ═══════════════════════════════════════════════════════════════════════════════
setup: check-deps setup-python setup-frontend setup-docker setup-ollama
	$(call ok,All dependencies installed)

setup-tools: check-uv
	$(call section,Letta tools)
	uv run scripts/setup_letta_tools.py
	$(call ok,Letta tools registered)

setup-python: check-uv
	$(call section,Python)
	uv pip install -e ".[vibe,dev]"
	$(call ok,Python deps ready)

setup-frontend: check-node
	$(call section,Node)
	cd $(FRONTEND_DIR) && npm install
	@if [ ! -f $(FRONTEND_DIR)/.env ]; then \
	  cp $(FRONTEND_DIR)/.env.template $(FRONTEND_DIR)/.env; \
	  printf "  Created $(FRONTEND_DIR)/.env — fill in ANTHROPIC_API_KEY\n"; \
	fi
	$(call ok,Frontend deps ready)

setup-docker: check-docker
	$(call section,Docker / Letta)
	docker pull $(LETTA_IMAGE)
	$(call ok,Letta image ready)

setup-ollama: check-ollama
	$(call section,Ollama)
	ollama pull nomic-embed-text
	$(call ok,nomic-embed-text ready)

# ═══════════════════════════════════════════════════════════════════════════════
#  BUILD
# ═══════════════════════════════════════════════════════════════════════════════
build: build-python build-frontend

build-python: check-uv
	$(call section,Python type check)
	uv run mypy src/hands --ignore-missing-imports --no-error-summary
	$(call ok,Python checks done)

build-frontend: check-node
	$(call section,Next.js production build)
	cd $(FRONTEND_DIR) && npm run build
	$(call ok,Frontend built)

# ═══════════════════════════════════════════════════════════════════════════════
#  TEST
# ═══════════════════════════════════════════════════════════════════════════════
test: test-unit test-e2e

test-unit: check-uv
	$(call section,pytest)
	uv pip install -e . -q
	uv run pytest tests/ -v
	$(call ok,pytest passed)

test-e2e: check-node
	$(call section,Cypress e2e)
	@mkdir -p $(PID_DIR)
	@printf "  Starting Next.js dev server …\n"
	@cd $(FRONTEND_DIR) && \
	  USE_COOKIE_BASED_AUTHENTICATION=false npm run dev > /tmp/vibe-dev-test.log 2>&1 & \
	  echo $$! > $(CURDIR)/$(PID_DIR)/frontend-test.pid
	@printf "  Waiting for http://localhost:$(FRONTEND_PORT) …"
	@for i in $$(seq 1 30); do \
	  curl -sf http://localhost:$(FRONTEND_PORT) > /dev/null 2>&1 && break; \
	  printf "."; sleep 1; \
	done; printf "\n"
	@cd $(FRONTEND_DIR) && npx cypress run \
	  --spec "cypress/e2e/vibe.cy.ts" \
	  --headless \
	  2>&1; \
	STATUS=$$?; \
	kill "$$(cat $(CURDIR)/$(PID_DIR)/frontend-test.pid)" 2>/dev/null || true; \
	rm -f $(CURDIR)/$(PID_DIR)/frontend-test.pid; \
	exit $$STATUS

# ═══════════════════════════════════════════════════════════════════════════════
#  START
# ═══════════════════════════════════════════════════════════════════════════════
start: start-letta start-vibe start-ableton-mcp start-frontend status

start-letta: check-docker
	$(call section,Letta)
	@[ -n "$(LETTA_API_KEY)" ] || { printf "  LETTA_API_KEY is not set (frontend/.env). It is Letta's server password;\n  Letta drives tools that run code on this Mac, so it does not start without one.\n"; exit 1; }
	@mkdir -p $(VIBE_OUTPUT_DIR) $(PID_DIR)
	@docker inspect $(LETTA_CONTAINER) > /dev/null 2>&1 && \
	  docker rm -f $(LETTA_CONTAINER) > /dev/null || true
	@# Secrets go through a private env file, not docker's argv (visible in ps/inspect history).
	@umask 077; printf 'ANTHROPIC_API_KEY=%s\nGEMINI_API_KEY=%s\nOLLAMA_BASE_URL=%s\nSECURE=true\nLETTA_SERVER_PASSWORD=%s\n' \
	  "$(ANTHROPIC_API_KEY)" "$(GEMINI_API_KEY)" "http://$(OLLAMA_DOCKER_HOST):11434/v1" "$(LETTA_API_KEY)" > $(PID_DIR)/letta.env
	@# Published on loopback only: Letta can call execute (Python in Live).
	docker run -d \
	  --name $(LETTA_CONTAINER) \
	  $(DOCKER_NETWORK_FLAGS) \
	  -v ~/.letta/.persist/pgdata:/var/lib/postgresql/data \
	  -p 127.0.0.1:$(LETTA_PORT):8283 \
	  --env-file $(PID_DIR)/letta.env \
	  $(LETTA_IMAGE) > /dev/null
	@rm -f $(PID_DIR)/letta.env
	@printf "  Waiting for Letta on port $(LETTA_PORT) …"
	@for i in $$(seq 1 30); do \
	  curl -sf -H "Authorization: Bearer $(LETTA_API_KEY)" http://localhost:$(LETTA_PORT)/v1/health > /dev/null 2>&1 && break; \
	  printf "."; sleep 2; \
	done; printf "\n"
	$(call ok,Letta running on 127.0.0.1:$(LETTA_PORT) (password required))

start-vibe: check-uv
	$(call section,Vibe server)
	@uv pip install -e ".[vibe]" -q
	@mkdir -p $(PID_DIR) $(VIBE_OUTPUT_DIR)
	@if [ -f $(PID_DIR)/vibe.pid ] && kill -0 "$$(cat $(PID_DIR)/vibe.pid)" 2>/dev/null; then \
	  printf "  Vibe server already running (pid %s)\n" "$$(cat $(PID_DIR)/vibe.pid)"; \
	else \
	  VIBE_OUTPUT_DIR=$(VIBE_OUTPUT_DIR) uv run hands vibe --port $(VIBE_PORT) \
	    > /tmp/vibe-server.log 2>&1 & echo $$! > $(PID_DIR)/vibe.pid; \
	  sleep 2; \
	  printf "  Log: /tmp/vibe-server.log\n"; \
	fi
	$(call ok,Vibe server on port $(VIBE_PORT))

start-ableton-mcp: check-uv
	$(call section,Ableton MCP bridge)
	@[ -n "$$MCP_BRIDGE_TOKEN" ] || { printf "  MCP_BRIDGE_TOKEN is not set. The bridge runs Python inside Live;\n  it will not start without a token. Export one and rerun setup_letta_tools.py.\n"; exit 1; }
	@uv pip install -e ".[vibe]" -q
	@mkdir -p $(PID_DIR)
	@if [ -f $(PID_DIR)/ableton-mcp.pid ] && kill -0 "$$(cat $(PID_DIR)/ableton-mcp.pid)" 2>/dev/null; then \
	  printf "  Ableton MCP bridge already running (pid %s)\n" "$$(cat $(PID_DIR)/ableton-mcp.pid)"; \
	else \
	  uv run hands ableton-mcp --bridge-port $(ABLETON_MCP_BRIDGE_PORT) \
	    > /tmp/ableton-mcp-bridge.log 2>&1 & echo $$! > $(PID_DIR)/ableton-mcp.pid; \
	  sleep 1; \
	  printf "  Log: /tmp/ableton-mcp-bridge.log\n"; \
	fi
	$(call ok,Ableton MCP bridge on port $(ABLETON_MCP_BRIDGE_PORT))

start-frontend: check-node
	$(call section,Next.js)
	@mkdir -p $(PID_DIR)
	@STALE=$$(lsof -ti tcp:$(FRONTEND_PORT) 2>/dev/null); \
	if [ -n "$$STALE" ]; then \
	  echo "$$STALE" | xargs kill -9 2>/dev/null || true; \
	  printf "  Cleared stale processes on port $(FRONTEND_PORT)\n"; \
	fi
	@rm -f $(PID_DIR)/frontend.pid
	@cd $(FRONTEND_DIR) && npm run dev -- --hostname 127.0.0.1 > /tmp/vibe-frontend.log 2>&1 & \
	echo $$! > $(CURDIR)/$(PID_DIR)/frontend.pid; \
	printf "  Waiting for http://localhost:$(FRONTEND_PORT) …"; \
	for i in $$(seq 1 30); do \
	  curl -sf http://localhost:$(FRONTEND_PORT) > /dev/null 2>&1 && break; \
	  printf "."; sleep 1; \
	done; printf "\n"; \
	printf "  Log: /tmp/vibe-frontend.log\n"; \
	TAILSCALE_IP=$$(tailscale ip --4 2>/dev/null); \
	if [ -n "$$TAILSCALE_IP" ]; then \
	  printf "  Tailscale: http://$$TAILSCALE_IP:$(FRONTEND_PORT)\n"; \
	fi
	$(call ok,Frontend on http://localhost:$(FRONTEND_PORT))

# ═══════════════════════════════════════════════════════════════════════════════
#  STOP
# ═══════════════════════════════════════════════════════════════════════════════
stop: stop-frontend stop-vibe stop-ableton-mcp stop-letta
	$(call ok,All services stopped)

stop-frontend:
	@if [ -f $(PID_DIR)/frontend.pid ]; then \
	  kill "$$(cat $(PID_DIR)/frontend.pid)" 2>/dev/null || true; \
	  rm -f $(PID_DIR)/frontend.pid; \
	fi
	@PIDS=$$(lsof -ti tcp:$(FRONTEND_PORT) 2>/dev/null); \
	if [ -n "$$PIDS" ]; then \
	  echo "$$PIDS" | xargs kill -9 2>/dev/null || true; \
	  printf "  Stopped frontend (port $(FRONTEND_PORT) cleared)\n"; \
	else \
	  printf "  Frontend not running\n"; \
	fi

stop-vibe:
	@if [ -f $(PID_DIR)/vibe.pid ]; then \
	  kill "$$(cat $(PID_DIR)/vibe.pid)" 2>/dev/null \
	    && printf "  Stopped vibe server\n" \
	    || printf "  Vibe server was not running\n"; \
	  rm -f $(PID_DIR)/vibe.pid; \
	else printf "  Vibe server not running\n"; fi

stop-ableton-mcp:
	@if [ -f $(PID_DIR)/ableton-mcp.pid ]; then \
	  kill "$$(cat $(PID_DIR)/ableton-mcp.pid)" 2>/dev/null \
	    && printf "  Stopped Ableton MCP bridge\n" \
	    || printf "  Ableton MCP bridge was not running\n"; \
	  rm -f $(PID_DIR)/ableton-mcp.pid; \
	else printf "  Ableton MCP bridge not running\n"; fi

stop-letta:
	@if ! command -v docker > /dev/null 2>&1; then \
	  printf "  Letta skipped (docker not installed)\n"; \
	else \
	  docker stop $(LETTA_CONTAINER) 2>/dev/null \
	    && printf "  Stopped Letta\n" \
	    || printf "  Letta not running\n"; \
	  docker rm $(LETTA_CONTAINER) 2>/dev/null || true; \
	fi

# ═══════════════════════════════════════════════════════════════════════════════
#  LOGS / STATUS
# ═══════════════════════════════════════════════════════════════════════════════
logs:
	@printf "\n$(BOLD)=== Letta (Docker) ===$(RESET)\n"
	@if ! command -v docker > /dev/null 2>&1; then \
	  printf "  docker not installed\n"; \
	else \
	  docker logs --tail=20 $(LETTA_CONTAINER) 2>/dev/null || printf "  not running\n"; \
	fi
	@printf "\n$(BOLD)=== Vibe server ===$(RESET)\n"
	@tail -20 /tmp/vibe-server.log 2>/dev/null || printf "  no log yet\n"
	@printf "\n$(BOLD)=== Ableton MCP bridge ===$(RESET)\n"
	@tail -20 /tmp/ableton-mcp-bridge.log 2>/dev/null || printf "  no log yet\n"
	@printf "\n$(BOLD)=== Frontend ===$(RESET)\n"
	@tail -20 /tmp/vibe-frontend.log 2>/dev/null || printf "  no log yet\n"

stream-agent: check-uv
	@printf "$(CYAN)$(BOLD)── TMS agent activity (Ctrl-C to stop) ──$(RESET)\n"
	uv run scripts/stream_agent.py

stream-all: check-uv
	@printf "$(CYAN)$(BOLD)── Agent + infra combined (Ctrl-C to stop) ──$(RESET)\n"
	@trap 'kill 0' INT TERM; \
	  uv run scripts/stream_agent.py --history 10 2>&1 & \
	  { docker logs -f $(LETTA_CONTAINER) 2>&1 \
	      | grep --line-buffered -E \
	          'MCP Result:|HTTP Request: POST https://api\.anthropic|HTTP Request: POST http://host\.docker\.internal|Context (token|window)|Summariz|ERROR|Exception|timed out' \
	      | sed 's/^/\x1b[2m[infra]\x1b[0m /'; } & \
	  wait

stream-letta:
	@if ! command -v docker > /dev/null 2>&1; then \
	  printf "  docker not installed\n"; exit 1; fi
	@printf "$(CYAN)$(BOLD)── Letta live log — filtered (Ctrl-C to stop) ──$(RESET)\n"
	@printf "$(CYAN)  (showing: agent steps, LLM calls, MCP results, errors)$(RESET)\n\n"
	@docker logs -f $(LETTA_CONTAINER) 2>&1 \
	  | grep --line-buffered -E \
	      'Letta\.agent-|MCP Result:|HTTP Request: POST https://api\.anthropic|HTTP Request: POST http://host\.docker\.internal|Context (token|window)|Summariz|ERROR|Exception|timed out|FINISHED'

stream-letta-raw:
	@if ! command -v docker > /dev/null 2>&1; then \
	  printf "  docker not installed\n"; exit 1; fi
	@printf "$(CYAN)$(BOLD)── Letta raw log (Ctrl-C to stop) ──$(RESET)\n"
	docker logs -f $(LETTA_CONTAINER) 2>&1

stream-vibe:
	@printf "$(CYAN)$(BOLD)── Vibe server live log (Ctrl-C to stop) ──$(RESET)\n"
	@tail -f /tmp/vibe-server.log 2>/dev/null || printf "  no log yet — is 'make start-vibe' running?\n"

stream-ableton-mcp:
	@printf "$(CYAN)$(BOLD)── Ableton MCP bridge live log (Ctrl-C to stop) ──$(RESET)\n"
	@tail -f /tmp/ableton-mcp-bridge.log 2>/dev/null || printf "  no log yet — is 'make start-ableton-mcp' running?\n"

stream-frontend:
	@printf "$(CYAN)$(BOLD)── Frontend live log (Ctrl-C to stop) ──$(RESET)\n"
	@tail -f /tmp/vibe-frontend.log 2>/dev/null || printf "  no log yet — is 'make start-frontend' running?\n"

# Follows all four services in parallel with coloured prefixes.
# Each sub-process is placed in its own process group so Ctrl-C cleans up everything.
stream:
	@printf "$(CYAN)$(BOLD)── Streaming all services (Ctrl-C to stop) ──$(RESET)\n"
	@trap 'kill 0' INT TERM; \
	  { docker logs -f $(LETTA_CONTAINER) 2>&1 \
	      | sed 's/^/\x1b[36m[letta]\x1b[0m /'; } & \
	  { tail -F /tmp/vibe-server.log 2>/dev/null \
	      | sed 's/^/\x1b[33m[vibe]\x1b[0m /'; } & \
	  { tail -F /tmp/ableton-mcp-bridge.log 2>/dev/null \
	      | sed 's/^/\x1b[35m[ableton]\x1b[0m /'; } & \
	  { tail -F /tmp/vibe-frontend.log 2>/dev/null \
	      | sed 's/^/\x1b[32m[frontend]\x1b[0m /'; } & \
	  wait

## ─── Self-improvement ────────────────────────────────────────────────────────
## Run: make self-improve DESCRIPTION="..." PROMPT="..."
## Or:  make self-improve DESCRIPTION="..." PROMPT="..." SERVICES="vibe ableton-mcp"
self-improve: check-uv
	$(call section,Self-improvement — Claude Agent SDK)
	@if [ -z "$(DESCRIPTION)" ] || [ -z "$(PROMPT)" ]; then \
	  printf "$(BOLD)Usage:$(RESET)\n"; \
	  printf "  make self-improve DESCRIPTION=\"short label\" PROMPT=\"full instructions\"\n"; \
	  printf "  make self-improve DESCRIPTION=\"...\" PROMPT=\"...\" SERVICES=\"vibe ableton-mcp\"\n"; \
	  exit 1; \
	fi
	@if [ -n "$(SERVICES)" ]; then \
	  SERVICE_FLAGS=$$(echo "$(SERVICES)" | tr ' ' '\n' | sed 's/^/--service /'); \
	  uv run hands self-improve "$(DESCRIPTION)" --prompt "$(PROMPT)" $$SERVICE_FLAGS; \
	else \
	  uv run hands self-improve "$(DESCRIPTION)" --prompt "$(PROMPT)"; \
	fi
	$(call ok,Improvement applied)

# ═══════════════════════════════════════════════════════════════════════════════
#  WATCHDOG
#  Runs independently of the vibe stack — NOT included in make start/stop.
#  To enable self-healing: make watchdog
#  To disable:             make stop-watchdog   (or: touch .watchdog-stop)
# ═══════════════════════════════════════════════════════════════════════════════
watchdog: check-uv
	$(call section,Watchdog)
	@mkdir -p $(PID_DIR)
	@rm -f .watchdog-stop
	@if [ -f $(PID_DIR)/watchdog.pid ] && kill -0 "$$(cat $(PID_DIR)/watchdog.pid)" 2>/dev/null; then \
	  printf "  Watchdog already running (pid %s)\n" "$$(cat $(PID_DIR)/watchdog.pid)"; \
	else \
	  uv run scripts/watchdog.py --pid-file $(PID_DIR)/watchdog.pid \
	    > /tmp/vibe-watchdog.log 2>&1 & \
	  sleep 1; \
	  printf "  Log: /tmp/vibe-watchdog.log\n"; \
	fi
	$(call ok,Watchdog running (pid $$(cat $(PID_DIR)/watchdog.pid 2>/dev/null || echo unknown)))

stop-watchdog:
	@touch .watchdog-stop
	@if [ -f $(PID_DIR)/watchdog.pid ]; then \
	  kill "$$(cat $(PID_DIR)/watchdog.pid)" 2>/dev/null \
	    && printf "  Stopped watchdog\n" \
	    || printf "  Watchdog was not running\n"; \
	  rm -f $(PID_DIR)/watchdog.pid; \
	else printf "  Watchdog not running\n"; fi

watchdog-status:
	@printf "\n$(BOLD)Watchdog status:$(RESET)\n"
	@if [ -f $(PID_DIR)/watchdog.pid ] && kill -0 "$$(cat $(PID_DIR)/watchdog.pid)" 2>/dev/null; then \
	  printf "  Running  (pid %s)\n" "$$(cat $(PID_DIR)/watchdog.pid)"; \
	else \
	  printf "  Stopped\n"; \
	fi
	@if [ -f .watchdog-stop ]; then \
	  printf "  $(BOLD)Stop sentinel present$(RESET) — remove .watchdog-stop to allow restart\n"; \
	fi
	@printf "\n$(BOLD)Recent watchdog log:$(RESET)\n"
	@tail -20 /tmp/vibe-watchdog.log 2>/dev/null || printf "  no log yet\n"
	@printf "\n"

status:
	@printf "\n$(BOLD)Service status:$(RESET)\n"
	@if ! command -v docker > /dev/null 2>&1; then \
	  printf "  Letta     $(BOLD)docker not installed$(RESET)\n"; \
	elif ! docker info > /dev/null 2>&1; then \
	  printf "  Letta     $(BOLD)docker daemon not running$(RESET)\n"; \
	else \
	  docker inspect $(LETTA_CONTAINER) --format \
	    '  Letta     {{ .State.Status }}  (port $(LETTA_PORT))' 2>/dev/null \
	    || printf "  Letta     stopped\n"; \
	fi
	@if [ -f $(PID_DIR)/vibe.pid ] && kill -0 "$$(cat $(PID_DIR)/vibe.pid)" 2>/dev/null; then \
	  printf "  Vibe      running  (pid %s, port $(VIBE_PORT))\n" "$$(cat $(PID_DIR)/vibe.pid)"; \
	else printf "  Vibe      stopped\n"; fi
	@if [ -f $(PID_DIR)/ableton-mcp.pid ] && kill -0 "$$(cat $(PID_DIR)/ableton-mcp.pid)" 2>/dev/null; then \
	  printf "  AbletonMCP running  (pid %s, port $(ABLETON_MCP_BRIDGE_PORT))\n" "$$(cat $(PID_DIR)/ableton-mcp.pid)"; \
	else printf "  AbletonMCP stopped\n"; fi
	@if [ -f $(PID_DIR)/frontend.pid ] && kill -0 "$$(cat $(PID_DIR)/frontend.pid)" 2>/dev/null; then \
	  printf "  Frontend  running  (pid %s, http://localhost:$(FRONTEND_PORT))\n" \
	    "$$(cat $(PID_DIR)/frontend.pid)"; \
	else printf "  Frontend  stopped\n"; fi
	@printf "\n"
