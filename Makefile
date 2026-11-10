# zpkt: each part is its own uv project. These targets run them from the repo root.
CORE     := hands ears ears/mlab
CONTRIB  := contrib/booth contrib/letta-vibe
PROTO    := prototypes/taste prototypes/engineer
PYTEST   := uv run pytest -q -p no:cacheprovider

.PHONY: setup remote-script test test-all

setup: remote-script  ## install each core part's environment and the Live Remote Script
	@for p in $(CORE); do (cd $$p && uv sync -q) || exit 1; done
	@echo "Now restart Live and pick AbletonLiveMCP as a Control Surface (docs/getting-started.md)."

remote-script:
	hands/remote_scripts/install.sh

test:  ## the supported parts: offline, no Live
	cd hands && uv run --all-extras pytest -q -p no:cacheprovider
	cd ears && $(PYTEST)
	cd ears/mlab && $(PYTEST)

test-all: test  ## contrib and prototypes too
	@for p in $(CONTRIB) $(PROTO); do echo "== $$p"; (cd $$p && $(PYTEST)) || exit 1; done
	cd contrib/voice && uv run --extra dev pytest -q -p no:cacheprovider
	cd contrib/harness && uv run --extra dev pytest -q -p no:cacheprovider
	cd prototypes/audio-browser && $(PYTEST) --ignore tests/test_segment.py
	cd contrib/bot && npm ci --ignore-scripts --no-audit --no-fund && npm test
