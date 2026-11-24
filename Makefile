# zpkt: the core (zpkt.live, zpkt.audio) is one uv project at the repo root; contrib and prototypes are their own.
CONTRIB  := contrib/booth
PYTEST   := uv run pytest -q -p no:cacheprovider

.PHONY: setup remote-script test test-all

setup: remote-script  ## install the core's environment (every extra) and the Live Remote Script
	uv sync -q --all-extras
	@echo "Now restart Live and pick AbletonLiveMCP as a Control Surface (docs/getting-started.md)."

remote-script:
	src/zpkt/live/remote_scripts/install.sh

test:  ## the supported parts: offline, no Live
	uv run --all-extras pytest -q -p no:cacheprovider

test-all: test  ## contrib and prototypes too
	@for p in $(CONTRIB); do echo "== $$p"; (cd $$p && $(PYTEST)) || exit 1; done
	cd contrib/harness && uv run --extra dev pytest -q -p no:cacheprovider
	uv run --all-extras pytest -q -p no:cacheprovider contrib/arranger/tests
	uv run --all-extras pytest -q -p no:cacheprovider contrib/mixdesk/tests
	cd prototypes/audio-browser && $(PYTEST) --ignore tests/test_segment.py
	cd prototypes/checklist && uv run --extra dev pytest -q -p no:cacheprovider
	cd contrib/bot && npm ci --ignore-scripts --no-audit --no-fund && npm test
