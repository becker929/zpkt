.PHONY: help install install-segment test typecheck check test-e2e test-e2e-install serve scan rescan dupes dedupe-dry-run stats segment bakeoff clean-db

# Which root `dedupe-dry-run` inspects. Override on the command line.
ROOT ?= audio-library

help:
	@echo "install    install dependencies into .venv"
	@echo "install-segment  add the stage 3 model dependencies (~3 GB)"
	@echo "test       run the offline unit tests"
	@echo "typecheck  run mypy"
	@echo "check      test and typecheck"
	@echo "test-e2e   run the browser tests (needs the stack on 3100 for the live project)"
	@echo "serve      run the HTTP API on 0.0.0.0:8090"
	@echo "scan       index every configured root"
	@echo "dupes      report duplicates and the redundancy verdict"
	@echo "dedupe-dry-run  propose deletions for ROOT=$(ROOT); deletes nothing"
	@echo "stats      summarise the index"
	@echo "segment    run one classifier over the collection: make segment METHOD=yamnet"
	@echo "bakeoff    report where the classifiers agree and where they do not"

install:
	uv sync

install-segment:
	uv sync --extra segment

test:
	uv run pytest tests/ -v

typecheck:
	uv run mypy

check: test typecheck

# Playwright starts its own mock server. The `live` project needs the real
# stack already listening on 3100.
test-e2e:
	cd frontend && npm run test:e2e

test-e2e-install:
	cd frontend && npm install && npm run test:e2e:install

serve:
	uv run audio-browser serve

scan:
	uv run audio-browser scan

rescan:
	uv run audio-browser scan --reprobe

dupes:
	uv run audio-browser dupes

# Dry run only. There is deliberately no `make dedupe-apply`: deleting files is
# a decision, so it is typed out in full.
dedupe-dry-run:
	uv run audio-browser dedupe --root $(ROOT) --plan-out /tmp/dedupe-plan.txt

stats:
	uv run audio-browser stats

# Which classifier `segment` runs. There is no default: naming it is the point.
METHOD ?=

segment:
	@test -n "$(METHOD)" || (echo "give METHOD=yamnet|vad|clap" >&2; exit 2)
	PYTORCH_ENABLE_MPS_FALLBACK=1 uv run audio-browser segment $(METHOD)

bakeoff:
	uv run audio-browser bakeoff

# Removes only the index. Never touches the audio roots.
clean-db:
	rm -f audio-browser.db audio-browser.db-wal audio-browser.db-shm
